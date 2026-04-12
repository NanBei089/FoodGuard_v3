import { Button } from '@/components/ui/Button';
import {
  healthConditionDescriptions,
  healthConditionLabels,
} from '@/lib/foodguard';
import type { UserPreferences } from '@/types/auth';

const focusGroupOptions = [
  { id: 'adult', label: '自己 / 成年人' },
  { id: 'child', label: '儿童' },
  { id: 'elder', label: '老年人' },
  { id: 'pregnant', label: '孕妇' },
  { id: 'fitness', label: '健身 / 减脂' },
];

const healthConditionOptions = [
  { id: 'diabetes', label: '糖尿病 / 控糖' },
  { id: 'hypertension', label: '高血压 / 控钠' },
  { id: 'hyperuricemia', label: '高尿酸 / 痛风' },
];

interface PreferencesSectionProps {
  preferences: UserPreferences;
  savingProfile: boolean;
  profileMessage: string;
  allergyInput: string;
  onSave: () => void;
  onToggleArrayItem: (
    key: 'focus_groups' | 'health_conditions',
    value: string,
  ) => void;
  onToggleAllergyCondition: () => void;
  onAllergyInputChange: (value: string) => void;
  onAddAllergy: () => void;
  onRemoveAllergy: (value: string) => void;
}

export function PreferencesSection({
  preferences,
  savingProfile,
  profileMessage,
  allergyInput,
  onSave,
  onToggleArrayItem,
  onToggleAllergyCondition,
  onAllergyInputChange,
  onAddAllergy,
  onRemoveAllergy,
}: PreferencesSectionProps) {
  const hasAllergyCondition = preferences.health_conditions.includes('allergy');

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/60 p-6">
        <div>
          <h2 className="text-lg font-bold text-slate-900">默认健康偏好</h2>
          <p className="mt-1 text-sm text-slate-500">
            这些设置会在每次分析时自动带入，作为个性化判断依据。
          </p>
        </div>
        <Button onClick={onSave} isLoading={savingProfile} className="bg-emerald-500 hover:bg-emerald-600">
          保存修改
        </Button>
      </div>

      <div className="space-y-8 p-6">
        {profileMessage && (
          <div
            className={`rounded-xl px-4 py-3 text-sm ${
              profileMessage.includes('成功')
                ? 'border border-emerald-100 bg-emerald-50 text-emerald-700'
                : 'border border-rose-100 bg-rose-50 text-rose-600'
            }`}
          >
            {profileMessage}
          </div>
        )}

        <div>
          <div className="mb-5 flex items-center gap-2">
            <div className="h-4 w-1.5 rounded-full bg-emerald-500" />
            <h3 className="text-base font-bold text-slate-800">常驻关注人群</h3>
            <span className="rounded border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              多选
            </span>
          </div>
          <div className="flex flex-wrap gap-3">
            {focusGroupOptions.map((item) => {
              const checked = preferences.focus_groups.includes(item.id);
              return (
                <label key={item.id} className="cursor-pointer">
                  <input
                    type="checkbox"
                    className="peer sr-only"
                    checked={checked}
                    onChange={() => onToggleArrayItem('focus_groups', item.id)}
                  />
                  <div
                    className={`flex items-center justify-center rounded-full border px-5 py-2.5 transition-all ${
                      checked
                        ? 'border-emerald-500 bg-emerald-500 text-white shadow-sm'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-emerald-300 hover:bg-emerald-50/30'
                    }`}
                  >
                    <span className="text-sm font-medium">{item.label}</span>
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        <div className="h-px bg-slate-100" />

        <div>
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-4 w-1.5 rounded-full bg-emerald-500" />
              <h3 className="text-base font-bold text-slate-800">个人特殊健康状况</h3>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-400">可多选</span>
            </div>
            <div className="rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
              已选 {preferences.health_conditions.length} 项
            </div>
          </div>

          <p className="mb-4 text-sm text-slate-500">
            用于在报告里优先突出与你相关的风险点和建议。
          </p>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {healthConditionOptions.map((item) => {
              const checked = preferences.health_conditions.includes(item.id);
              return (
                <label key={item.id} className="block cursor-pointer rounded-2xl">
                  <input
                    type="checkbox"
                    className="peer sr-only"
                    checked={checked}
                    onChange={() => onToggleArrayItem('health_conditions', item.id)}
                  />
                  <div
                    className={`flex h-full flex-col rounded-2xl border-2 p-5 transition-all ${
                      checked
                        ? 'border-emerald-500 bg-emerald-50/40'
                        : 'border-slate-200 bg-white hover:border-emerald-300'
                    }`}
                  >
                    <div className="mb-3 text-base font-bold text-slate-800">{item.label}</div>
                    <div className="text-[13px] leading-relaxed text-slate-500">
                      {healthConditionDescriptions[item.id]}
                    </div>
                  </div>
                </label>
              );
            })}

            <label className="block cursor-pointer rounded-2xl">
              <input
                type="checkbox"
                className="peer sr-only"
                checked={hasAllergyCondition}
                onChange={onToggleAllergyCondition}
              />
              <div
                className={`flex h-full flex-col rounded-2xl border-2 p-5 transition-all ${
                  hasAllergyCondition
                    ? 'border-emerald-500 bg-emerald-50/40'
                    : 'border-slate-200 bg-white hover:border-emerald-300'
                }`}
              >
                <div className="mb-3 text-base font-bold text-slate-800">
                  {healthConditionLabels.allergy}
                </div>
                <div className="text-[13px] leading-relaxed text-slate-500">
                  {healthConditionDescriptions.allergy}
                </div>
              </div>
            </label>
          </div>
        </div>

        {hasAllergyCondition && (
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
            <label className="mb-2 block text-sm font-bold text-slate-800">请填写你的食物过敏源</label>
            <p className="mb-4 text-xs text-slate-500">保存后，报告会优先标记这些成分。</p>
            <div className="flex gap-2">
              <input
                type="text"
                value={allergyInput}
                onChange={(event) => onAllergyInputChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    onAddAllergy();
                  }
                }}
                placeholder="例如：花生、牛奶、麸质、虾蟹"
                className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
              />
              <Button type="button" onClick={onAddAllergy} className="bg-emerald-500 hover:bg-emerald-600">
                添加
              </Button>
            </div>

            {preferences.allergies.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {preferences.allergies.map((item) => (
                  <span
                    key={item}
                    className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700"
                  >
                    {item}
                    <button
                      type="button"
                      onClick={() => onRemoveAllergy(item)}
                      className="ml-1 text-slate-400 transition-colors hover:text-rose-500"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
