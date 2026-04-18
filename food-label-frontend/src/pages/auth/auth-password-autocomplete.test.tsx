import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from './Login';
import Register from './Register';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe('auth input autocomplete', () => {
  it('marks login fields for saved-credential autofill', () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );

    expect(document.getElementById('login-email')?.getAttribute('autocomplete')).toBe(
      'username',
    );
    expect(document.getElementById('login-password')?.getAttribute('autocomplete')).toBe(
      'current-password',
    );
  });

  it('marks register fields for username, one-time-code, and new-password autofill', () => {
    render(
      <MemoryRouter>
        <Register />
      </MemoryRouter>,
    );

    expect(document.getElementById('register-email')?.getAttribute('autocomplete')).toBe(
      'username',
    );
    expect(document.getElementById('register-code')?.getAttribute('autocomplete')).toBe(
      'one-time-code',
    );
    expect(document.getElementById('register-password')?.getAttribute('autocomplete')).toBe(
      'new-password',
    );
    expect(
      document.getElementById('register-confirm-password')?.getAttribute('autocomplete'),
    ).toBe('new-password');
  });
});
