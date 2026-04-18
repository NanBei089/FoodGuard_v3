import { LockKeyhole, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';

interface ChangePasswordFormProps {
  accountEmail: string;
  currentPassword: string;
  newPassword: string;
  confirmNewPassword: string;
  changingPassword: boolean;
  passwordMessage: string;
  passwordErrors: Partial<Record<string, string>>;
  onCurrentPasswordChange: (value: string) => void;
  onNewPasswordChange: (value: string) => void;
  onConfirmNewPasswordChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => void;
  onLogout: () => void | Promise<void>;
}

export function ChangePasswordForm({
  accountEmail,
  currentPassword,
  newPassword,
  confirmNewPassword,
  changingPassword,
  passwordMessage,
  passwordErrors,
  onCurrentPasswordChange,
  onNewPasswordChange,
  onConfirmNewPasswordChange,
  onSubmit,
  onLogout,
}: ChangePasswordFormProps) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50/60 p-5">
        <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
          <ShieldCheck className="h-4 w-4 text-slate-500" />
          账号安全与操作
        </h2>
      </div>
      <div className="space-y-5 p-5">
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-900">修改密码</h3>
          <p className="mb-3 text-xs text-slate-500">
            修改后会立即更新账号密码，后续登录请使用新密码。
          </p>
          <form className="space-y-3" onSubmit={onSubmit}>
            <input
              type="email"
              name="profile-password-username"
              autoComplete="username"
              value={accountEmail}
              readOnly
              tabIndex={-1}
              aria-hidden="true"
              className="sr-only"
            />
            {passwordMessage && (
              <div
                className={`rounded-xl px-3 py-2 text-sm ${
                  passwordMessage.includes('成功')
                    ? 'border border-emerald-100 bg-emerald-50 text-emerald-700'
                    : 'border border-rose-100 bg-rose-50 text-rose-600'
                }`}
              >
                {passwordMessage}
              </div>
            )}

            <PasswordField
              label="当前密码"
              placeholder="请输入当前密码"
              value={currentPassword}
              error={passwordErrors.current_password}
              autoComplete="current-password"
              onChange={onCurrentPasswordChange}
            />
            <PasswordField
              label="新密码"
              placeholder="8-32 位，需包含大写字母、小写字母和数字"
              value={newPassword}
              error={passwordErrors.new_password}
              autoComplete="new-password"
              onChange={onNewPasswordChange}
            />
            <PasswordField
              label="确认新密码"
              placeholder="请再次输入新密码"
              value={confirmNewPassword}
              error={passwordErrors.confirmNewPassword}
              autoComplete="new-password"
              onChange={onConfirmNewPasswordChange}
            />

            <p className="text-[11px] leading-relaxed text-slate-500">
              新密码需为 8-32 位，并同时包含大写字母、小写字母和数字。
            </p>

            <Button type="submit" isLoading={changingPassword} className="w-full bg-slate-900 hover:bg-slate-800">
              修改密码
            </Button>
          </form>
        </div>

        <div className="h-px bg-slate-100" />

        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-900">退出登录</h3>
          <p className="mb-3 text-xs text-slate-500">退出当前设备上的 FoodGuard 登录状态。</p>
          <button
            type="button"
            onClick={onLogout}
            className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            退出登录
          </button>
        </div>
      </div>
    </div>
  );
}

function PasswordField({
  label,
  placeholder,
  value,
  error,
  autoComplete,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  error?: string;
  autoComplete: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="mb-2 block text-xs font-medium text-slate-600">{label}</label>
      <div className="relative">
        <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <Input
          type="password"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete}
          className="bg-slate-50 pl-10 focus:bg-white"
          error={error}
          required
        />
      </div>
    </div>
  );
}
