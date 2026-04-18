import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiGet, apiPatch, apiPost, apiPut } from '@/api/client';
import { ChangePasswordForm } from '@/components/profile/ChangePasswordForm';
import { PreferencesSection } from '@/components/profile/PreferencesSection';
import { ProfileForm } from '@/components/profile/ProfileForm';
import { performManualLogout } from '@/lib/auth-session';
import { extractApiErrorDetails, getErrorMessage } from '@/lib/api-errors';
import { getUserInitial } from '@/lib/foodguard';
import { useAuthStore } from '@/store/auth';
import type { PageResponse } from '@/types/api';
import type { User, UserPreferences } from '@/types/auth';

interface ReportListMeta {
  total: number;
}

export default function Profile() {
  const navigate = useNavigate();
  const { user, setUser, preferences: storePreferences, setPreferences, logout } = useAuthStore();
  const [displayName, setDisplayName] = useState(user?.display_name || '');
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMessage, setProfileMessage] = useState('');
  const [totalReports, setTotalReports] = useState(0);
  const [preferences, setLocalPreferences] = useState<UserPreferences>(
    storePreferences ?? {
      focus_groups: [],
      health_conditions: [],
      allergies: [],
      updated_at: new Date().toISOString(),
    },
  );
  const [allergyInput, setAllergyInput] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState('');
  const [passwordErrors, setPasswordErrors] = useState<Partial<Record<string, string>>>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [userRes, prefRes, reportRes] = await Promise.all([
          apiGet<User>('/users/me'),
          apiGet<UserPreferences>('/preferences/me').catch(() => null),
          apiGet<PageResponse<unknown>>('/reports?page=1&page_size=1').catch(() => null),
        ]);

        if (userRes.code === 0) {
          setUser(userRes.data);
          setDisplayName(userRes.data.display_name || '');
        }

        if (prefRes?.code === 0) {
          setLocalPreferences(prefRes.data);
          setPreferences(prefRes.data);
        }

        if (reportRes?.code === 0) {
          const metadata = reportRes.data as ReportListMeta;
          setTotalReports(metadata.total || 0);
        }
      } catch (err) {
        setProfileMessage(getErrorMessage(err, '加载用户数据失败'));
      }
    };

    fetchData();
  }, [setPreferences, setUser]);

  const toggleArrayItem = (key: 'focus_groups' | 'health_conditions', value: string) => {
    setLocalPreferences((current) => {
      const items = current[key];
      return {
        ...current,
        [key]: items.includes(value) ? items.filter((item) => item !== value) : [...items, value],
      };
    });
  };

  const toggleAllergyCondition = () => {
    setLocalPreferences((current) => {
      const hasAllergy = current.health_conditions.includes('allergy');
      return {
        ...current,
        health_conditions: hasAllergy
          ? current.health_conditions.filter((item) => item !== 'allergy')
          : [...current.health_conditions, 'allergy'],
        allergies: hasAllergy ? [] : current.allergies,
      };
    });
  };

  const addAllergy = () => {
    const nextItem = allergyInput.trim();
    if (!nextItem || preferences.allergies.includes(nextItem)) {
      return;
    }

    setLocalPreferences((current) => ({
      ...current,
      allergies: [...current.allergies, nextItem],
      health_conditions: current.health_conditions.includes('allergy')
        ? current.health_conditions
        : [...current.health_conditions, 'allergy'],
    }));
    setAllergyInput('');
  };

  const removeAllergy = (item: string) => {
    setLocalPreferences((current) => ({
      ...current,
      allergies: current.allergies.filter((entry) => entry !== item),
    }));
  };

  const handleSave = async () => {
    setSavingProfile(true);
    setProfileMessage('');

    try {
      const [userRes, prefRes] = await Promise.all([
        apiPatch<User>('/users/me', {
          display_name: displayName.trim(),
        }),
        apiPut<UserPreferences>('/preferences/me', {
          focus_groups: preferences.focus_groups,
          health_conditions: preferences.health_conditions,
          allergies: preferences.allergies,
        }),
      ]);

      if (userRes.code !== 0) {
        throw new Error(userRes.message || '保存资料失败');
      }

      if (prefRes.code !== 0) {
        throw new Error(prefRes.message || '保存偏好失败');
      }

      setUser(userRes.data);
      setPreferences(prefRes.data);
      setProfileMessage('保存成功');
    } catch (err: unknown) {
      setProfileMessage(getErrorMessage(err, '网络请求失败'));
    } finally {
      setSavingProfile(false);
    }
  };

  const clearPasswordFieldError = (field: string) => {
    setPasswordMessage('');
    setPasswordErrors((current) => {
      if (!current[field]) {
        return current;
      }
      const next = { ...current };
      delete next[field];
      return next;
    });
  };

  const handleChangePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setPasswordMessage('');
    setPasswordErrors({});

    if (newPassword !== confirmNewPassword) {
      setPasswordMessage('两次输入的新密码不一致');
      setPasswordErrors({ confirmNewPassword: '两次输入的新密码不一致' });
      return;
    }

    setChangingPassword(true);

    try {
      const res = await apiPost<null>('/users/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      });

      if (res.code !== 0) {
        throw new Error(res.message || '修改密码失败');
      }

      setCurrentPassword('');
      setNewPassword('');
      setConfirmNewPassword('');
      setPasswordErrors({});
      setPasswordMessage('密码修改成功');
    } catch (err: unknown) {
      const errorPayload =
        typeof err === 'object' && err !== null && 'response' in err
          ? (err as { response?: { data?: unknown } }).response?.data
          : undefined;
      const { message, fieldErrors } = extractApiErrorDetails(
        errorPayload,
        getErrorMessage(err, '修改密码失败'),
      );
      if (Object.keys(fieldErrors).length === 0 && message.includes('当前密码')) {
        setPasswordErrors({ current_password: message });
      } else {
        setPasswordErrors(fieldErrors);
      }
      setPasswordMessage(message);
    } finally {
      setChangingPassword(false);
    }
  };

  const handleLogout = async () => {
    await performManualLogout({
      onLocalLogout: logout,
      onAfterLogout: () => navigate('/login'),
    });
  };

  const activePreferenceCount =
    preferences.focus_groups.length + preferences.health_conditions.length + preferences.allergies.length;

  return (
    <div className="flex w-full flex-col gap-8 md:flex-row">
      <aside className="flex w-full flex-col gap-6 md:w-80">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
          <div className="group relative mx-auto mb-4 flex h-24 w-24 items-center justify-center rounded-full border-4 border-white bg-gradient-to-br from-emerald-100 to-teal-100 shadow-md">
            <span className="text-3xl font-bold text-emerald-600">{getUserInitial(user)}</span>
          </div>
          <h2 className="mb-1 text-xl font-bold text-slate-900">{displayName || '未设置昵称'}</h2>
          <p className="text-sm text-slate-500">{user?.email || ''}</p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 font-bold text-slate-900">使用数据</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-xl bg-slate-50 p-4 text-center">
              <div className="mb-1 text-2xl font-bold text-slate-900">{totalReports}</div>
              <div className="text-xs text-slate-500">累计分析</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-4 text-center">
              <div className="mb-1 text-2xl font-bold text-emerald-600">{activePreferenceCount}</div>
              <div className="text-xs text-slate-500">已设偏好</div>
            </div>
          </div>
        </div>

        <ChangePasswordForm
          accountEmail={user?.email || ''}
          currentPassword={currentPassword}
          newPassword={newPassword}
          confirmNewPassword={confirmNewPassword}
          changingPassword={changingPassword}
          passwordMessage={passwordMessage}
          passwordErrors={passwordErrors}
          onCurrentPasswordChange={(value) => {
            setCurrentPassword(value);
            clearPasswordFieldError('current_password');
          }}
          onNewPasswordChange={(value) => {
            setNewPassword(value);
            clearPasswordFieldError('new_password');
          }}
          onConfirmNewPasswordChange={(value) => {
            setConfirmNewPassword(value);
            clearPasswordFieldError('confirmNewPassword');
          }}
          onSubmit={handleChangePassword}
          onLogout={() => {
            void handleLogout();
          }}
        />
      </aside>

      <section className="flex-1 space-y-6">
        <ProfileForm
          user={user}
          displayName={displayName}
          onDisplayNameChange={setDisplayName}
        />

        <PreferencesSection
          preferences={preferences}
          savingProfile={savingProfile}
          profileMessage={profileMessage}
          allergyInput={allergyInput}
          onSave={handleSave}
          onToggleArrayItem={toggleArrayItem}
          onToggleAllergyCondition={toggleAllergyCondition}
          onAllergyInputChange={setAllergyInput}
          onAddAllergy={addAllergy}
          onRemoveAllergy={removeAllergy}
        />
      </section>
    </div>
  );
}
