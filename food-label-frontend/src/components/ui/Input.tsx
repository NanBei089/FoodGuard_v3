import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: string;
  startIcon?: ReactNode;
  iconClassName?: string;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, startIcon, iconClassName, id, ...props }, ref) => {
    const errorId = error && id ? `${id}-error` : undefined;
    return (
      <div className="w-full">
        <div className="relative">
          {startIcon && (
            <span
              className={cn(
                'pointer-events-none absolute left-3 top-1/2 z-10 flex h-5 w-5 -translate-y-1/2 items-center justify-center text-slate-400 transition-colors duration-200',
                error
                  ? 'text-rose-400'
                  : 'group-focus-within:text-emerald-500 focus-within:text-emerald-500',
                iconClassName,
              )}
              aria-hidden="true"
            >
              {startIcon}
            </span>
          )}
          <input
            ref={ref}
            id={id}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={errorId}
            className={cn(
              'flex h-11 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-5 text-slate-900 transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
              startIcon && 'pl-11',
              error && 'border-red-500 focus-visible:ring-red-500',
              className,
            )}
            {...props}
          />
        </div>
        {error && (
          <p id={errorId} className="mt-1 text-sm text-red-500">
            {error}
          </p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';

export { Input };
