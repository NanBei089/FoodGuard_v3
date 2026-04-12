import { UserRound } from 'lucide-react';
import type { User } from '@/types/auth';

interface ProfileFormProps {
  user: User | null;
  displayName: string;
  onDisplayNameChange: (value: string) => void;
}

export function ProfileForm({
  user,
  displayName,
  onDisplayNameChange,
}: ProfileFormProps) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50/60 p-6">
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900">
          <UserRound className="h-5 w-5 text-emerald-600" />
          账号设置
        </h2>
        <p className="mt-1 text-sm text-slate-500">管理你的基本资料与默认分析配置。</p>
      </div>
      <div className="space-y-6 p-6">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">昵称</label>
            <input
              type="text"
              value={displayName}
              onChange={(event) => onDisplayNameChange(event.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-900 transition-all focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">邮箱账号</label>
            <input
              type="email"
              value={user?.email || ''}
              disabled
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-900"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
