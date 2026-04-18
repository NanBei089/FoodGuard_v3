import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { ChangePasswordForm } from './ChangePasswordForm';

afterEach(() => {
  cleanup();
});

describe('ChangePasswordForm', () => {
  it('marks password fields with the correct autocomplete attributes', () => {
    const { container } = render(
      <ChangePasswordForm
        accountEmail="qa@example.com"
        currentPassword=""
        newPassword=""
        confirmNewPassword=""
        changingPassword={false}
        passwordMessage=""
        passwordErrors={{}}
        onCurrentPasswordChange={() => {}}
        onNewPasswordChange={() => {}}
        onConfirmNewPasswordChange={() => {}}
        onSubmit={(event) => event.preventDefault()}
        onLogout={() => {}}
      />,
    );

    const passwordInputs = Array.from(
      container.querySelectorAll<HTMLInputElement>('input[type="password"]'),
    );
    const usernameInput = container.querySelector<HTMLInputElement>(
      'input[autocomplete="username"]',
    );

    expect(passwordInputs).toHaveLength(3);
    expect(usernameInput?.value).toBe('qa@example.com');
    expect(passwordInputs[0]?.getAttribute('autocomplete')).toBe('current-password');
    expect(passwordInputs[1]?.getAttribute('autocomplete')).toBe('new-password');
    expect(passwordInputs[2]?.getAttribute('autocomplete')).toBe('new-password');
  });
});
