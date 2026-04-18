import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamReportChat } from './report-chat';

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('streamReportChat', () => {
  it('fails fast when the response stream stays idle for too long', async () => {
    localStorage.setItem('access_token', 'test-access-token');

    const stalledStream = new ReadableStream<Uint8Array>({
      start() {
        // Intentionally never enqueue or close.
      },
    });

    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(stalledStream, {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
        },
      }),
    ) as typeof fetch;

    await expect(
      streamReportChat({
        reportId: 'report-1',
        message: 'hello',
        idleTimeoutMs: 20,
      }),
    ).rejects.toThrow('问答流长时间未返回新内容，请稍后重试');
  });
});
