import { useEffect, useRef, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  AlertCircle,
  Check,
  ClipboardCheck,
  Clock3,
  Database,
  FileImage,
  ImagePlus,
  Loader2,
  ScanLine,
  TableProperties,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiGet } from '@/api/client';
import { Button } from '@/components/ui/Button';
import {
  ANALYSIS_STEP_DEFINITIONS,
  getAnalysisProgress,
  type AnalysisTaskStatus,
} from '@/lib/analysis-progress';
import { getErrorMessage } from '@/lib/api-errors';
import { cn } from '@/lib/utils';

const INITIAL_POLL_INTERVAL_MS = 1500;
const MAX_POLL_INTERVAL_MS = 3000;
const MAX_ANALYSIS_WAIT_MS = 10 * 60 * 1000;
const MAX_CONSECUTIVE_POLL_FAILURES = 3;
const COMPLETION_REDIRECT_DELAY_MS = 450;

type StepStatus = 'pending' | 'processing' | 'completed';

type AnalysisStep = {
  title: string;
  description: string;
  threshold: number;
  icon: LucideIcon;
};

const ANALYSIS_STEPS: AnalysisStep[] = [
  {
    ...ANALYSIS_STEP_DEFINITIONS[0],
    icon: ImagePlus,
  },
  {
    ...ANALYSIS_STEP_DEFINITIONS[1],
    icon: ScanLine,
  },
  {
    ...ANALYSIS_STEP_DEFINITIONS[2],
    icon: TableProperties,
  },
  {
    ...ANALYSIS_STEP_DEFINITIONS[3],
    icon: Database,
  },
  {
    ...ANALYSIS_STEP_DEFINITIONS[4],
    icon: ClipboardCheck,
  },
];

function revokePreview(url: string | null) {
  if (url && url.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
  sessionStorage.removeItem('latest_upload_preview');
}

export default function Analyzing() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [status, setStatus] = useState<AnalysisTaskStatus | null>(null);
  const [error, setError] = useState('');
  const previewUrl = sessionStorage.getItem('latest_upload_preview') || '';
  const processingStartedAtMsRef = useRef<number | null>(null);

  useEffect(() => {
    if (!taskId) {
      return;
    }

    processingStartedAtMsRef.current = null;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    let redirectTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let pollInterval = INITIAL_POLL_INTERVAL_MS;
    let consecutiveFailures = 0;
    const fallbackStartedAtMs = Date.now();

    const stopPollingWithError = (message: string) => {
      if (cancelled) {
        return;
      }

      setError(message);
      revokePreview(previewUrl);
    };

    const checkStatus = async () => {
      if (cancelled) {
        return;
      }

      try {
        const res = await apiGet<AnalysisTaskStatus>(`/analysis/tasks/${taskId}`);

        if (res.code !== 0) {
          setError(res.message || '分析任务状态获取失败');
          return;
        }

        consecutiveFailures = 0;
        if (res.data.status === 'processing' && processingStartedAtMsRef.current === null) {
          processingStartedAtMsRef.current = Date.now();
        }
        setStatus(res.data);

        const parsedCreatedAtMs = Date.parse(res.data.created_at || '');
        const analysisStartedAtMs = Number.isNaN(parsedCreatedAtMs)
          ? fallbackStartedAtMs
          : parsedCreatedAtMs;

        if (Date.now() - analysisStartedAtMs >= MAX_ANALYSIS_WAIT_MS) {
          stopPollingWithError('分析耗时过长，当前 OCR/LLM 服务可能响应较慢，请稍后重试');
          return;
        }

        if (res.data.status === 'completed' && res.data.report_id) {
          redirectTimeoutId = setTimeout(() => {
            if (cancelled) {
              return;
            }

            revokePreview(previewUrl);
            navigate(`/reports/${res.data.report_id}`);
          }, COMPLETION_REDIRECT_DELAY_MS);
          return;
        }

        if (res.data.status === 'failed') {
          setError(res.data.error_message || '分析失败');
          revokePreview(previewUrl);
          return;
        }

        pollInterval = Math.min(pollInterval + 500, MAX_POLL_INTERVAL_MS);
        timeoutId = setTimeout(checkStatus, pollInterval);
      } catch (err: unknown) {
        consecutiveFailures += 1;

        if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          stopPollingWithError(
            getErrorMessage(err, '分析状态获取失败，请检查后端服务或稍后重试'),
          );
          return;
        }

        timeoutId = setTimeout(checkStatus, pollInterval);
      }
    };

    checkStatus();

    return () => {
      cancelled = true;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      if (redirectTimeoutId) {
        clearTimeout(redirectTimeoutId);
      }
    };
  }, [navigate, previewUrl, taskId]);

  const progress = getAnalysisProgress(
    status,
    Date.now(),
    processingStartedAtMsRef.current ?? undefined,
  );

  return (
    <div className="flex min-h-[calc(100vh-220px)] items-center justify-center py-4">
      <div className="w-full max-w-3xl overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl shadow-slate-200/80">
        {error || status?.status === 'failed' ? (
          <div className="p-8 text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-rose-100 text-rose-600">
              <AlertCircle className="h-8 w-8" />
            </div>
            <h2 className="text-2xl font-bold text-slate-900">分析失败</h2>
            <p className="mt-2 text-slate-600">{error || status?.error_message}</p>
            <Button onClick={() => navigate('/')} className="mt-6 w-full">
              返回首页重试
            </Button>
          </div>
        ) : (
          <div className="grid gap-8 p-6 md:grid-cols-[220px_1fr] md:p-8">
            <div className="md:pt-1">
              <div className="relative mx-auto h-48 w-48 overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-inner md:h-52 md:w-52">
                {previewUrl ? (
                  <img src={previewUrl} alt="分析中" className="h-full w-full object-contain opacity-80" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-slate-300">
                    <FileImage className="h-12 w-12" />
                  </div>
                )}
                <div className="absolute inset-0 rounded-2xl border-2 border-emerald-500/50" />
                <div className="scanner-line animate-scan z-10" />
                <div className="absolute left-[10%] top-[20%] h-[10%] w-[80%] rounded border border-emerald-400/80 bg-emerald-400/10" />
                <div className="absolute left-[10%] top-[40%] h-[8%] w-[60%] rounded border border-emerald-400/80 bg-emerald-400/10" />
                <div className="absolute left-[10%] top-[60%] h-[12%] w-[70%] rounded border border-emerald-400/80 bg-emerald-400/10" />
              </div>
            </div>

            <div>
              <div className="mb-5 text-left">
                <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {progress.headline}
                </div>
                <h2 className="text-2xl font-bold text-slate-950 md:text-3xl">AI 正在分析食品标签</h2>
                <p className="mt-2 min-h-5 text-sm text-slate-500">
                  {progress.detail}
                </p>
              </div>

              <div className="mb-6">
                <div className="mb-2 flex items-center justify-between text-xs font-medium text-slate-500">
                  <span>{status?.progress_message || '初始化分析引擎中...'}</span>
                  <span className="text-emerald-700">{progress.percent}%</span>
                </div>
                <div className="relative h-3 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="progress-bar-fill relative h-full rounded-full bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400"
                    style={{ width: `${progress.percent}%` }}
                  >
                    <div className="absolute inset-0 animate-[pulse_2s_linear_infinite] bg-gradient-to-r from-transparent via-white/45 to-transparent" />
                  </div>
                </div>
                <div className="mt-2 flex justify-between text-[11px] font-medium text-slate-400">
                  <span>0%</span>
                  <span>完成后自动进入报告</span>
                  <span>100%</span>
                </div>
              </div>

              <div className="space-y-3 text-left">
                {ANALYSIS_STEPS.map((step, index) => (
                  <Step
                    key={step.title}
                    step={step}
                    status={
                      status?.status === 'completed' || progress.percent >= step.threshold
                        ? 'completed'
                        : index === progress.activeStepIndex
                          ? 'processing'
                          : 'pending'
                    }
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Step({
  step,
  status,
}: {
  step: AnalysisStep;
  status: StepStatus;
}) {
  const Icon = step.icon;

  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-2xl border p-3 transition-colors duration-300',
        status === 'completed' && 'border-emerald-100 bg-emerald-50/70',
        status === 'processing' && 'border-emerald-200 bg-white shadow-sm ring-1 ring-emerald-100',
        status === 'pending' && 'border-slate-100 bg-slate-50/70',
      )}
    >
      <div
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl',
          status === 'completed' && 'bg-emerald-100 text-emerald-700',
          status === 'processing' && 'bg-emerald-600 text-white',
          status === 'pending' && 'bg-white text-slate-400 ring-1 ring-slate-200',
        )}
      >
        {status === 'completed' ? (
          <Check className="h-4 w-4" />
        ) : status === 'processing' ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Icon className="h-4 w-4" />
        )}
      </div>
      <div className="min-w-0">
        <p
          className={cn(
            'text-sm font-semibold',
            status === 'pending' ? 'text-slate-500' : 'text-slate-900',
          )}
        >
          {step.title}
        </p>
        <p className="mt-0.5 text-xs leading-5 text-slate-500">{step.description}</p>
      </div>
      {status === 'pending' && <Clock3 className="ml-auto mt-1 h-4 w-4 shrink-0 text-slate-300" />}
    </div>
  );
}
