import { ArrowLeft, ShieldAlert } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  formatReportDate,
  getScorePalette,
  scoreRingOffset,
} from '@/lib/foodguard';
import type { ReportDetailData } from '@/types/report';

interface ReportHeaderProps {
  report: ReportDetailData;
}

export function ReportHeader({ report }: ReportHeaderProps) {
  const score = report.analysis?.score || 0;
  const palette = getScorePalette(score);
  const ingredients = report.analysis?.ingredients || [];
  const dangerCount = ingredients.filter((item) => item.risk === 'danger').length;
  const warningCount = ingredients.filter((item) => item.risk === 'warning').length;

  return (
    <>
      <div className="mb-6">
        <Link
          to="/history"
          className="inline-flex items-center gap-2 text-sm text-slate-500 transition-colors hover:text-emerald-600"
        >
          <ArrowLeft className="h-4 w-4" />
          返回列表
        </Link>
      </div>

      <div className="mb-8 rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col items-center gap-10 lg:flex-row">
          <div className="group relative h-56 w-full overflow-hidden rounded-2xl shadow-inner lg:w-72 lg:shrink-0">
            <div className="absolute inset-0 z-10 bg-gradient-to-t from-black/20 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
            {report.image_url ? (
              <img
                src={report.image_url}
                alt="上传标签原图"
                className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
              />
            ) : (
              <div className="flex h-full items-center justify-center bg-slate-100 text-slate-400">
                暂无图片
              </div>
            )}
            <div className="absolute bottom-3 left-3 z-20 rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-slate-700 shadow-sm backdrop-blur">
              创建于 {formatReportDate(report.created_at)}
            </div>
          </div>

          <div className="flex w-full flex-1 flex-col items-center gap-10 md:flex-row">
            <div className="group relative shrink-0 cursor-default">
              <div className="absolute inset-0 rounded-full bg-emerald-400/20 blur-2xl transition-colors duration-500 group-hover:bg-emerald-400/30" />
              <svg className="-rotate-90 relative z-10 h-48 w-48" viewBox="0 0 100 100">
                <circle
                  cx="50"
                  cy="50"
                  r="45"
                  fill="none"
                  stroke="#f1f5f9"
                  strokeWidth="8"
                  className="report-score-ring-track"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="45"
                  fill="none"
                  stroke={palette.ring}
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDashoffset={scoreRingOffset(score)}
                  className="report-score-ring drop-shadow-md"
                />
              </svg>
              <div className="absolute inset-0 z-20 flex flex-col items-center justify-center">
                <span className="text-6xl font-black tracking-tight text-slate-900">{score}</span>
                <span className="mt-1 text-sm font-medium uppercase tracking-[0.24em] text-slate-500">
                  综合健康分
                </span>
              </div>
            </div>

            <div className="grid w-full flex-1 grid-cols-2 gap-4">
              <MetricCard
                dotClass="bg-amber-500"
                label="需关注成分"
                value={dangerCount + warningCount}
                suffix="项"
                surfaceClass="from-slate-50 to-slate-100/50"
              />
              <MetricCard
                dotClass="bg-emerald-500"
                label="营养亮点"
                value={report.analysis?.benefits?.length || 0}
                suffix="项"
                surfaceClass="from-emerald-50 to-emerald-50/30"
              />
              <MetricCard
                dotClass="bg-blue-500"
                label="总配料数"
                value={ingredients.length}
                suffix="项"
                surfaceClass="from-slate-50 to-slate-100/50"
              />
              <MetricCard
                dotClass="bg-rose-500"
                label="高置信匹配"
                value={report.rag_summary?.high_match_count || 0}
                suffix={`/${ingredients.length}项`}
                valueClass="text-rose-600"
                surfaceClass="from-rose-50 to-rose-50/30"
              />
            </div>
          </div>

          <div
            className={`flex h-full shrink-0 flex-col items-center justify-center gap-3 rounded-2xl border bg-gradient-to-b p-6 shadow-sm lg:w-48 ${palette.surfaceClass}`}
          >
            <div className="relative">
              <div className={`absolute inset-0 rounded-full blur opacity-30 ${palette.accentClass}`} />
              <div
                className={`relative z-10 flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br ${
                  score >= 80
                    ? 'from-emerald-400 to-emerald-600'
                    : score >= 60
                      ? 'from-amber-400 to-amber-600'
                      : 'from-rose-400 to-rose-600'
                } text-white shadow-lg`}
              >
                <ShieldAlert className="h-8 w-8" />
              </div>
            </div>
            <div className="text-center">
              <div className="mb-1 text-lg font-bold text-slate-900">{palette.badge}</div>
              <div className={`rounded-full px-2.5 py-1 text-xs font-medium ${palette.badgeClass}`}>
                {score >= 80
                  ? '可以放心选择'
                  : score >= 60
                    ? '建议适量食用'
                    : '建议谨慎购买'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function MetricCard({
  dotClass,
  label,
  value,
  suffix,
  surfaceClass,
  valueClass = 'text-slate-900',
}: {
  dotClass: string;
  label: string;
  value: number;
  suffix: string;
  surfaceClass: string;
  valueClass?: string;
}) {
  return (
    <div className={`rounded-2xl border border-slate-100 bg-gradient-to-br p-5 ${surfaceClass}`}>
      <div className="mb-2 flex items-center gap-2">
        <div className={`h-2 w-2 rounded-full ${dotClass}`} />
        <div className="text-sm font-medium text-slate-600">{label}</div>
      </div>
      <div className="flex items-baseline gap-1">
        <div className={`text-3xl font-bold ${valueClass}`}>{value}</div>
        <div className="text-sm text-slate-500">{suffix}</div>
      </div>
    </div>
  );
}
