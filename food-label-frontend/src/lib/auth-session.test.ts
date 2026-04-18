import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { performManualLogout } from './auth-session';

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  getApiBaseUrl: () => '/api/v1',
}));

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('performManualLogout', () => {
  it('sends the current refresh token to the logout endpoint before clearing local state', async () => {
    localStorage.setItem('refresh_token', 'refresh-token-1');
    const onLocalLogout = vi.fn();
    const onAfterLogout = vi.fn();

    fetchMock.mockResolvedValue({
      ok: true,
    });

    await performManualLogout({
      onLocalLogout,
      onAfterLogout,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/auth/logout',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          refresh_token: 'refresh-token-1',
        }),
      }),
    );
    expect(onLocalLogout).toHaveBeenCalledOnce();
    expect(onAfterLogout).toHaveBeenCalledOnce();
  });

  it('still clears local state and continues the navigation flow when server revocation fails', async () => {
    localStorage.setItem('refresh_token', 'refresh-token-2');
    const onLocalLogout = vi.fn();
    const onAfterLogout = vi.fn();

    fetchMock.mockRejectedValue(new Error('network down'));

    await performManualLogout({
      onLocalLogout,
      onAfterLogout,
    });

    expect(onLocalLogout).toHaveBeenCalledOnce();
    expect(onAfterLogout).toHaveBeenCalledOnce();
  });
});
