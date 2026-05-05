export interface AnalysisTaskStatus {
  task_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress_message: string;
  created_at?: string;
  report_id: string | null;
  error_message: string | null;
}

export const ANALYSIS_STEP_DEFINITIONS = [
  {
    title: '图像准备与标签定位',
    description: '校验图片质量，定位可识别的标签区域',
    threshold: 22,
  },
  {
    title: 'OCR 文字与营养表识别',
    description: '读取包装文字、配料表和营养成分表',
    threshold: 44,
  },
  {
    title: '营养与配料结构化',
    description: '整理营养数值、配料清单和解析来源',
    threshold: 62,
  },
  {
    title: '风险检索与规则评分',
    description: '匹配成分知识库并计算健康评分',
    threshold: 78,
  },
  {
    title: '生成健康报告',
    description: '整合风险摘要、健康建议和报告内容',
    threshold: 92,
  },
] as const;

const PROCESSING_PROGRESS_POINTS = [
  { elapsedMs: 0, percent: 8 },
  { elapsedMs: 8_000, percent: 22 },
  { elapsedMs: 22_000, percent: 40 },
  { elapsedMs: 45_000, percent: 62 },
  { elapsedMs: 75_000, percent: 80 },
  { elapsedMs: 120_000, percent: 96 },
];

function getElapsedMs(
  createdAt?: string,
  nowMs = Date.now(),
  startedAtMsOverride?: number,
) {
  const parsedCreatedAtMs = Date.parse(createdAt || '');
  const startedAtMs =
    typeof startedAtMsOverride === 'number'
      ? startedAtMsOverride
      : Number.isNaN(parsedCreatedAtMs)
        ? nowMs
        : parsedCreatedAtMs;
  return Math.max(0, nowMs - startedAtMs);
}

function estimateProcessingPercent(
  createdAt?: string,
  nowMs = Date.now(),
  startedAtMsOverride?: number,
) {
  const elapsedMs = getElapsedMs(createdAt, nowMs, startedAtMsOverride);

  for (let index = 1; index < PROCESSING_PROGRESS_POINTS.length; index += 1) {
    const previous = PROCESSING_PROGRESS_POINTS[index - 1];
    const current = PROCESSING_PROGRESS_POINTS[index];

    if (elapsedMs <= current.elapsedMs) {
      const span = current.elapsedMs - previous.elapsedMs;
      const ratio = span === 0 ? 0 : (elapsedMs - previous.elapsedMs) / span;
      return Math.round(previous.percent + (current.percent - previous.percent) * ratio);
    }
  }

  return PROCESSING_PROGRESS_POINTS[PROCESSING_PROGRESS_POINTS.length - 1].percent;
}

export function getAnalysisProgress(
  status: AnalysisTaskStatus | null,
  nowMs = Date.now(),
  processingStartedAtMs?: number,
) {
  if (!status) {
    return {
      percent: 2,
      activeStepIndex: 0,
      headline: '初始化分析引擎',
      detail: '正在建立任务状态连接',
    };
  }

  if (status.status === 'queued') {
    return {
      percent: 6,
      activeStepIndex: 0,
      headline: '任务排队中',
      detail: '等待分析服务接收任务',
    };
  }

  if (status.status === 'completed') {
    return {
      percent: 100,
      activeStepIndex: ANALYSIS_STEP_DEFINITIONS.length - 1,
      headline: '分析完成',
      detail: '正在打开健康报告',
    };
  }

  if (status.status === 'failed') {
    return {
      percent: 0,
      activeStepIndex: 0,
      headline: '分析失败',
      detail: status.error_message || '任务未能完成',
    };
  }

  const percent = estimateProcessingPercent(
    status.created_at,
    nowMs,
    processingStartedAtMs,
  );
  const activeStepIndex = ANALYSIS_STEP_DEFINITIONS.findIndex(
    (step) => percent <= step.threshold,
  );
  const resolvedStepIndex =
    activeStepIndex === -1 ? ANALYSIS_STEP_DEFINITIONS.length - 1 : activeStepIndex;
  const activeStep = ANALYSIS_STEP_DEFINITIONS[resolvedStepIndex];

  return {
    percent,
    activeStepIndex: resolvedStepIndex,
    headline: activeStep.title,
    detail: activeStep.description,
  };
}
