import { useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { apiPatch, apiPut } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { getErrorMessage } from '@/lib/api-errors';
import { healthConditionDescriptions } from '@/lib/foodguard';
import { useAuthStore } from '@/store/auth';
import type { User, UserPreferences } from '@/types/auth';

const focusGroupOptions = [
  { id: 'adult', emoji: '🧑', label: '自己 / 成年人' },
  { id: 'child', emoji: '🧒', label: '儿童' },
  { id: 'elder', emoji: '👴', label: '老年人' },
  { id: 'pregnant', emoji: '🤰', label: '孕妇' },
  { id: 'fitness', emoji: '🏋️', label: '健身 / 减脂' },
];

const healthConditionOptions = [
  { id: 'diabetes', label: '糖尿病 / 控糖' },
  { id: 'hypertension', label: '高血压 / 控钠' },
  { id: 'hyperuricemia', label: '高尿酸 / 痛风' },
];

export default function Onboarding() {
  const navigate = useNavigate();
  const { user, preferences, setSession } = useAuthStore();
  const [displayName, setDisplayName] = useState(user?.display_name ?? '');
  const [form, setForm] = useState<UserPreferences>(
    preferences ?? {
      focus_groups: [],
      health_conditions: [],
      allergies: [],
      updated_at: new Date().toISOString(),
    },
  );
  const [allergyInput, setAllergyInput] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const hasAllergyCondition = form.health_conditions.includes('allergy');

  const toggleArrayItem = (key: 'focus_groups' | 'health_conditions', value: string) => {
    setForm((current) => {
      const currentItems = current[key];
      return {
        ...current,
        [key]: currentItems.includes(value)
          ? currentItems.filter((item) => item !== value)
          : [...currentItems, value],
      };
    });
  };

  const toggleAllergyCondition = () => {
    setForm((current) => {
      const nextConditions = current.health_conditions.includes('allergy')
        ? current.health_conditions.filter((item) => item !== 'allergy')
        : [...current.health_conditions, 'allergy'];

      return {
        ...current,
        health_conditions: nextConditions,
        allergies: nextConditions.includes('allergy') ? current.allergies : [],
      };
    });
  };

  const addAllergy = () => {
    const value = allergyInput.trim();
    if (!value || form.allergies.includes(value)) {
      return;
    }

    setForm((current) => ({
      ...current,
      allergies: [...current.allergies, value],
      health_conditions: current.health_conditions.includes('allergy')
        ? current.health_conditions
        : [...current.health_conditions, 'allergy'],
    }));
    setAllergyInput('');
  };

  const removeAllergy = (item: string) => {
    setForm((current) => ({
      ...current,
      allergies: current.allergies.filter((entry) => entry !== item),
    }));
  };

  const handleSubmit = async () => {
    const normalizedDisplayName = displayName.trim();
    if (!normalizedDisplayName) {
      setError('请先填写昵称');
      return;
    }

    if (form.focus_groups.length === 0) {
      setError('请至少选择一个关注人群');
      return;
    }

    setSaving(true);
    setError('');

    try {
      const [userRes, preferenceRes] = await Promise.all([
        apiPatch<User>('/users/me', {
          display_name: normalizedDisplayName,
        }),
        apiPut<UserPreferences>('/preferences/me', {
          focus_groups: form.focus_groups,
          health_conditions: form.health_conditions,
          allergies: form.allergies,
        }),
      ]);

      if (userRes.code !== 0) {
        throw new Error(userRes.message || '保存昵称失败');
      }

      if (preferenceRes.code !== 0) {
        throw new Error(preferenceRes.message || '保存健康偏好失败');
      }

      setSession(userRes.data, preferenceRes.data);
      navigate('/');
    } catch (err: unknown) {
      setError(getErrorMessage(err, '保存引导信息失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-pattern flex min-h-[calc(100vh-180px)] w-full items-center justify-center py-4">
      <div className="w-full max-w-2xl">
        <div className="mb-10 text-center">
          <div className="mb-6 inline-flex h-16 w-16 items-center justify-center rounded-full border border-emerald-100 bg-white shadow-md">
            <span className="text-3xl">🧭</span>
          </div>
          <h1 className="mb-3 text-3xl font-extrabold tracking-tight text-slate-900">
            完成 FoodGuard 初始化
          </h1>
          <p className="text-lg text-slate-600">
            为了生成更准确的分析结果，请先完成以下必填设置。
          </p>
        </div>

        <div className="soft-panel rounded-[30px] p-8">
          {error && (
            <div className="mb-6 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">
              {error}
            </div>
          )}

          <div className="space-y-8">
            <section>
              <h2 className="mb-4 flex items-center gap-2 text-lg font-bold text-slate-900">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-100 text-sm text-emerald-600">
                  1
                </span>
                基本信息
              </h2>
              <div className="ml-8">
                <label
                  htmlFor="onboarding-display-name"
                  className="mb-2 block text-sm font-medium text-slate-700"
                >
                  你希望我们怎么称呼你？
                </label>
                <input
                  id="onboarding-display-name"
                  name="onboarding-display-name"
                  type="text"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="例如：小林 / 妈妈 / 健身中的我"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm transition-all focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            </section>

            <hr className="border-slate-100" />

            <section>
              <h2 className="mb-4 flex items-center gap-2 text-lg font-bold text-slate-900">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-100 text-sm text-emerald-600">
                  2
                </span>
                你通常为谁购买食品？
                <span className="text-sm font-normal text-slate-400">(多选)</span>
              </h2>
              <div className="ml-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
                {focusGroupOptions.map((option) => {
                  const selected = form.focus_groups.includes(option.id);
                  return (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => toggleArrayItem('focus_groups', option.id)}
                      className={`flex flex-col items-center justify-center rounded-2xl border-2 p-4 transition-all duration-300 ${
                        selected
                          ? 'border-emerald-500 bg-emerald-500 text-white'
                          : 'border-slate-100 bg-slate-50/50 text-slate-500 hover:border-emerald-200 hover:bg-emerald-50/50'
                      }`}
                    >
                      <span className="mb-2 text-3xl">{option.emoji}</span>
                      <span className="text-sm font-bold">{option.label}</span>
                    </button>
                  );
                })}
              </div>
            </section>

            <hr className="border-slate-100" />

            <section>
              <h2 className="mb-4 flex items-center gap-2 text-lg font-bold text-slate-900">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-100 text-sm text-emerald-600">
                  3
                </span>
                是否有需要特别关注的健康状况？
                <span className="text-sm font-normal text-slate-400">(可选)</span>
              </h2>
              <div className="ml-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
                {healthConditionOptions.map((option) => {
                  const selected = form.health_conditions.includes(option.id);
                  return (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => toggleArrayItem('health_conditions', option.id)}
                      className={`rounded-xl border-2 p-4 text-left transition-all ${
                        selected
                          ? 'border-emerald-500 bg-emerald-50'
                          : 'border-slate-100 bg-white hover:border-slate-200'
                      }`}
                    >
                      <div className="mb-1 font-bold text-slate-900">{option.label}</div>
                      <div className="text-xs text-slate-500">
                        {healthConditionDescriptions[option.id]}
                      </div>
                    </button>
                  );
                })}

                <div
                  className={`rounded-xl border-2 p-4 transition-all ${
                    hasAllergyCondition ? 'border-emerald-500 bg-emerald-50' : 'border-slate-100 bg-white'
                  }`}
                >
                  <button type="button" onClick={toggleAllergyCondition} className="w-full pr-10 text-left">
                    <div className="mb-1 font-bold text-slate-900">食物过敏</div>
                    <div className="text-xs text-slate-500">
                      填写后，系统会优先高亮与你过敏源相关的成分。
                    </div>
                  </button>

                  {hasAllergyCondition && (
                    <div className="mt-3 border-t border-slate-100 pt-3">
                      <label
                        htmlFor="onboarding-allergy-input"
                        className="mb-2 block text-xs font-semibold text-slate-700"
                      >
                        过敏源
                      </label>
                      <div className="flex gap-2">
                        <input
                          id="onboarding-allergy-input"
                          name="onboarding-allergy-input"
                          type="text"
                          value={allergyInput}
                          onChange={(event) => setAllergyInput(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                              event.preventDefault();
                              addAllergy();
                            }
                          }}
                          placeholder="例如：花生、牛奶、海鲜"
                          className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                        />
                        <Button type="button" onClick={addAllergy} className="bg-emerald-500 hover:bg-emerald-600">
                          添加
                        </Button>
                      </div>

                      {form.allergies.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {form.allergies.map((item) => (
                            <span
                              key={item}
                              className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700"
                            >
                              {item}
                              <button
                                type="button"
                                onClick={() => removeAllergy(item)}
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
            </section>

            <div className="ml-8 pt-4">
              <Button
                type="button"
                size="lg"
                onClick={handleSubmit}
                isLoading={saving}
                className="w-full rounded-xl bg-emerald-500 font-bold hover:bg-emerald-600"
              >
                完成设置，进入首页
                {!saving && <ArrowRight className="ml-2 h-5 w-5" />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
