import { memo } from 'react';
import { getIngredientRiskMeta } from '@/lib/foodguard';
import type { IngredientAnalysisItem } from '@/types/report';

interface IngredientListProps {
  ingredients: IngredientAnalysisItem[];
  ingredientsText: string;
}

export const IngredientList = memo(
  function IngredientList({ ingredients, ingredientsText }: IngredientListProps) {
    const dangerCount = ingredients.filter((item) => item.risk === 'danger').length;
    const warningCount = ingredients.filter((item) => item.risk === 'warning').length;
    const safeCount = ingredients.filter((item) => item.risk === 'safe').length;

    return (
      <div className="space-y-6">
        <div className="rounded-xl bg-slate-50 p-5">
          <h4 className="mb-4 text-sm font-semibold text-slate-900">配料风险分布</h4>
          <RiskBar label="高风险" count={dangerCount} total={ingredients.length} colorClass="bg-rose-500" />
          <RiskBar label="中风险" count={warningCount} total={ingredients.length} colorClass="bg-amber-500" />
          <RiskBar label="安全" count={safeCount} total={ingredients.length} colorClass="bg-emerald-500" />
        </div>

        <div className="rounded-xl bg-white p-5">
          <h4 className="mb-4 text-sm font-semibold text-slate-900">识别到的原始配料信息</h4>
          <p className="whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-sm leading-7 text-slate-600">
            {ingredientsText || '未识别到原始配料文本'}
          </p>
        </div>

        <div>
          <h4 className="mb-4 text-sm font-semibold text-slate-900">详细配料列表</h4>
          {ingredients.length > 0 ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3">
              {ingredients.map((item) => {
                const riskMeta = getIngredientRiskMeta(item.risk);
                return (
                  <div
                    key={`${item.name}-${item.risk}`}
                    className={`rounded-xl border p-4 ${riskMeta.cardClass}`}
                  >
                    <div className="mb-3 flex items-center gap-2">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${riskMeta.chipClass}`}>
                        {riskMeta.label}
                      </span>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-sm font-medium text-slate-900">{item.name}</span>
                        <span className={`h-2.5 w-2.5 rounded-full ${riskMeta.dotClass}`} />
                      </div>
                      <p className="text-xs leading-5 text-slate-600">{item.description}</p>
                      {item.function_category && (
                        <div className="text-xs text-slate-500">
                          功能类别：{item.function_category}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-sm text-slate-400">
              暂无结构化配料风险结果
            </div>
          )}
        </div>
      </div>
    );
  },
  (prevProps, nextProps) =>
    prevProps.ingredients === nextProps.ingredients &&
    prevProps.ingredientsText === nextProps.ingredientsText,
);

function RiskBar({
  label,
  count,
  total,
  colorClass,
}: {
  label: string;
  count: number;
  total: number;
  colorClass: string;
}) {
  const percentage = total > 0 ? (count / total) * 100 : 0;

  return (
    <div className="mb-3 flex items-center gap-4 last:mb-0">
      <div className="flex w-20 items-center gap-1 text-xs text-slate-600">
        <div className={`h-2 w-2 rounded-full ${colorClass}`} />
        {label}
      </div>
      <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${percentage}%` }} />
      </div>
      <div className="w-12 text-right text-xs text-slate-600">{count}项</div>
    </div>
  );
}
