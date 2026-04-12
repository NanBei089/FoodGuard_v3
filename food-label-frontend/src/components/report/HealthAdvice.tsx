import { CheckCircle2 } from 'lucide-react';
import { getIngredientRiskMeta } from '@/lib/foodguard';
import type { HealthAdviceItem } from '@/types/report';

interface HealthAdviceProps {
  healthAdvice: HealthAdviceItem[];
  benefits: string[];
}

export function HealthAdvice({ healthAdvice, benefits }: HealthAdviceProps) {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {healthAdvice.length > 0 ? (
          healthAdvice.map((item) => {
            const riskMeta = getIngredientRiskMeta(item.risk);
            return (
              <div key={item.group} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-3 flex items-center gap-2">
                  <span className={`rounded px-2 py-0.5 text-xs font-medium ${riskMeta.chipClass}`}>
                    {item.group}
                  </span>
                  <span className="text-xs text-slate-400">{riskMeta.label}</span>
                </div>
                <p className="text-sm leading-6 text-slate-700">{item.advice}</p>
                <div className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
                  {item.hint}
                </div>
              </div>
            );
          })
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-sm text-slate-400">
            暂无个性化人群建议
          </div>
        )}
      </div>

      {benefits.length > 0 && (
        <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-5">
          <h4 className="mb-4 flex items-center gap-2 text-sm font-semibold text-emerald-900">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            可能的营养亮点
          </h4>
          <div className="grid gap-3 md:grid-cols-2">
            {benefits.map((benefit) => (
              <div key={benefit} className="rounded-xl bg-white px-4 py-3 text-sm text-slate-700 shadow-sm">
                {benefit}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
