import { memo } from 'react';
import { AlertTriangle, BarChart3, Info } from 'lucide-react';
import { getNutritionLevelMeta } from '@/lib/foodguard';
import { cn } from '@/lib/utils';
import type { ReportNutritionTable } from '@/types/report';

interface NutritionTableProps {
  nutritionTable: ReportNutritionTable | null;
}

export const NutritionTable = memo(function NutritionTable({
  nutritionTable,
}: NutritionTableProps) {
  return (
    <div className="space-y-8 rounded-[32px] border border-slate-200 bg-white p-8 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-600">
            <BarChart3 className="h-7 w-7" />
          </div>
          <div>
            <h4 className="text-2xl font-bold text-slate-900">
              {nutritionTable?.title || '营养成分表'}
            </h4>
            <p className="mt-1 text-lg text-slate-500">
              {nutritionTable?.serving_basis || nutritionTable?.subtitle || '每100克 (Per 100g)'}
            </p>
          </div>
        </div>
      </div>

      {nutritionTable?.rows?.length ? (
        <div className="space-y-6">
          <div className="overflow-hidden rounded-[28px] bg-slate-50/70">
            <div className="overflow-x-auto">
              <div className="min-w-[820px] bg-white">
                <div className="grid grid-cols-[1.8fr_0.7fr_0.6fr_1.3fr] gap-4 border-b-2 border-slate-200 px-6 py-4 text-sm font-bold text-slate-700">
                  <div>营养成分</div>
                  <div>含量</div>
                  <div>NRV%</div>
                  <div>摄入建议</div>
                </div>

                {nutritionTable.rows.map((row) => {
                  const tone = getNutritionLevelMeta(row.level);
                  return (
                    <div
                      key={`${row.nutrient_key}-${row.display_name}`}
                      className={cn(
                        'grid grid-cols-[1.8fr_0.7fr_0.6fr_1.3fr] gap-4 border-b border-slate-100 px-6 py-5 text-sm last:border-b-0',
                        tone.rowClass,
                      )}
                    >
                      <div
                        className={cn(
                          'flex items-center text-slate-900',
                          row.is_child ? 'pl-5 text-[15px] text-slate-500' : 'text-[18px] font-semibold',
                        )}
                      >
                        {row.is_child ? `→ ${row.display_name}` : row.display_name}
                      </div>
                      <div className={cn('text-[18px] font-semibold', tone.amountClass)}>
                        {row.amount}
                      </div>
                      <div>
                        {row.nrv_label ? (
                          <span
                            className={cn(
                              'inline-flex rounded-full px-3 py-1 text-sm font-semibold',
                              tone.badgeClass,
                            )}
                          >
                            {row.nrv_label}
                          </span>
                        ) : (
                          <span className="text-sm text-slate-400">-</span>
                        )}
                      </div>
                      <div className={cn('flex items-center gap-2 text-[15px]', tone.recommendationClass)}>
                        {row.level === 'warning' && <AlertTriangle className="h-4 w-4 shrink-0" />}
                        <span>{row.recommendation}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="rounded-[24px] bg-amber-50/70 px-6 py-5">
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-100 text-amber-500">
                <Info className="h-5 w-5" />
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-900">
                  {nutritionTable.advice_title || '营养师建议'}
                </div>
              </div>
            </div>
            <p className="text-lg leading-8 text-slate-600">
              {nutritionTable.advice_summary ||
                '建议结合总能量、配料风险和个人健康目标综合判断。'}
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-6 py-14 text-center text-sm text-slate-400">
          未提取到结构化营养数据
        </div>
      )}
    </div>
  );
});
