import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { apiGet } from '@/api/client';
import { HealthAdvice } from '@/components/report/HealthAdvice';
import { HazardList } from '@/components/report/HazardList';
import { IngredientList } from '@/components/report/IngredientList';
import { ReportChatPanel } from '@/components/report/ReportChatPanel';
import { ReportHeader } from '@/components/report/ReportHeader';
import { NutritionTable } from '@/components/report/NutritionTable';
import { getErrorMessage } from '@/lib/api-errors';
import { cn } from '@/lib/utils';
import type { ReportDetailData, ReportTab } from '@/types/report';

export default function ReportDetail() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<ReportTab>('ingredients');
  const {
    data: report,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['report-detail', id],
    enabled: Boolean(id),
    queryFn: async () => {
      const res = await apiGet<ReportDetailData>(`/reports/${id}`);
      if (res.code !== 0 || !res.data) {
        throw new Error(res.message || '获取报告失败');
      }
      return res.data;
    },
    staleTime: 30_000,
  });

  if (isLoading) {
    return <div className="py-12 text-center">加载中...</div>;
  }

  if (error) {
    return (
      <div className="py-12 text-center text-rose-500">
        {getErrorMessage(error, '请求失败')}
      </div>
    );
  }

  if (!report) {
    return <div className="py-12 text-center">未找到报告</div>;
  }

  const tabs: Array<{ id: ReportTab; label: string }> = [
    { id: 'ingredients', label: '配料分析' },
    { id: 'nutrition', label: '营养成分' },
    { id: 'advice', label: '人群建议' },
  ];

  const ingredients = report.analysis?.ingredients || [];
  const healthAdvice = report.analysis?.health_advice || [];

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.18fr)_360px] 2xl:gap-8 2xl:grid-cols-[minmax(0,1.26fr)_380px]">
      <div className="min-w-0">
        <ReportHeader report={report} />
        <HazardList report={report} />

        <div className="mb-6 rounded-2xl border border-slate-200 bg-white">
          <div className="flex flex-wrap border-b border-slate-200">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'px-6 py-4 text-sm font-medium transition-colors',
                  activeTab === tab.id
                    ? 'tab-active'
                    : 'text-slate-500 hover:text-slate-700',
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="p-6">
            {activeTab === 'ingredients' && (
              <IngredientList
                ingredients={ingredients}
                ingredientsText={report.ingredients_text}
              />
            )}

            {activeTab === 'nutrition' && (
              <NutritionTable
                nutritionTable={report.nutrition_table}
                nutritionParseSource={report.nutrition_parse_source}
              />
            )}

            {activeTab === 'advice' && (
              <HealthAdvice
                healthAdvice={healthAdvice}
                benefits={report.analysis?.benefits || []}
              />
            )}
          </div>
        </div>
      </div>

      <div className="min-w-0">
        <ReportChatPanel
          reportId={report.report_id}
          initialConversation={report.conversation}
        />
      </div>
    </div>
  );
}
