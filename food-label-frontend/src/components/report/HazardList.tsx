import { Info, Sparkles } from 'lucide-react';
import type { ReportDetailData } from '@/types/report';

interface HazardListProps {
  report: ReportDetailData;
}

export function HazardList({ report }: HazardListProps) {
  const primaryHazard = report.analysis?.hazards[0];

  return (
    <div className="mb-8">
      <h3 className="mb-4 flex items-center gap-2 text-lg font-bold text-slate-900">
        <Sparkles className="h-5 w-5 text-emerald-500" />
        核心洞察
      </h3>

      <div className="rounded-2xl border-2 border-amber-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-amber-100">
            <span className="text-2xl">⚠️</span>
          </div>
          <div>
            <div className="mb-2 inline-flex items-center gap-1.5 rounded-md bg-amber-100 px-2.5 py-1 text-xs font-bold text-amber-800">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-600" />
              需要重点留意
            </div>
            <h4 className="text-xl font-bold text-slate-900">
              {primaryHazard ? primaryHazard.desc : '本次报告已生成完整健康总结'}
            </h4>
          </div>
        </div>

        <p className="mb-4 text-sm leading-relaxed text-slate-600">
          {report.analysis?.summary || '当前报告暂无总结，建议结合详细成分分析继续查看。'}
        </p>

        <div className="flex items-start gap-2 rounded-xl border border-amber-100 bg-amber-50 p-3 text-sm text-amber-800">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <strong>行动建议：</strong>
            {primaryHazard
              ? `优先关注“${primaryHazard.desc}”，并结合下方风险项与人群建议判断是否适合长期购买。`
              : '可继续查看营养成分与配料明细，辅助判断是否适合你的日常饮食。'}
          </p>
        </div>
      </div>
    </div>
  );
}
