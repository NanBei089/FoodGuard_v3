import { StrictMode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiGet, apiPost } from '@/api/client';
import { streamReportChat } from '@/lib/report-chat';
import type { ApiResponse } from '@/types/api';
import type { ReportChatSuggestionsResponse, ReportConversationResponse } from '@/types/report-chat';
import { ReportChatPanel } from './ReportChatPanel';

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock('@/lib/report-chat', () => ({
  streamReportChat: vi.fn(),
}));

const apiGetMock = vi.mocked(apiGet);
const apiPostMock = vi.mocked(apiPost);
const streamReportChatMock = vi.mocked(streamReportChat);

function createConversation(
  messages: ReportConversationResponse['messages'],
  suggestedQuestions: string[] = [],
): ReportConversationResponse {
  return {
    conversation_id: 'conversation-1',
    report_id: 'report-1',
    suggested_questions: suggestedQuestions,
    messages,
  };
}

function okResponse<T>(data: T): ApiResponse<T> {
  return {
    code: 0,
    message: 'ok',
    data,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('ReportChatPanel', () => {
  it('renders assistant replies as markdown with headings, emphasis, lists, and tables', async () => {
    const markdownConversation = createConversation([
      {
        message_id: 'message-1',
        role: 'assistant',
        content: [
          '### 核心结论',
          '',
          '这份产品的主要风险在于 **较高的碳水化合物含量**。',
          '',
          '- 建议控制单次食用量',
          '- 注意总糖摄入',
          '',
          '| 项目 | 结果 |',
          '| --- | --- |',
          '| 风险等级 | 中等 |',
        ].join('\n'),
        created_at: '2026-04-18T10:00:00Z',
      },
    ]);

    apiGetMock.mockResolvedValue(okResponse(markdownConversation));
    apiPostMock.mockResolvedValue(
      okResponse<ReportChatSuggestionsResponse>({ suggested_questions: [] }),
    );

    const { container } = render(
      <ReportChatPanel
        reportId="report-1"
        initialConversation={markdownConversation}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText('核心结论')).toBeTruthy();
    });

    expect(screen.getByText('核心结论').tagName).toBe('H3');
    expect(container.querySelector('strong')?.textContent).toContain('较高的碳水化合物含量');
    expect(screen.getByText('建议控制单次食用量')).toBeTruthy();
    expect(screen.getByText('注意总糖摄入')).toBeTruthy();
    expect(container.querySelector('table')).toBeTruthy();
    expect(screen.queryByText(/\*\*较高的碳水化合物含量\*\*/)).toBeNull();
  });

  it('refreshes the latest persisted conversation even when initialConversation exists', async () => {
    const initialConversation = createConversation(
      [
        {
          message_id: 'message-1',
          role: 'user',
          content: 'Old question',
          created_at: '2026-04-18T10:00:00Z',
        },
      ],
      ['Question A'],
    );
    const refreshedConversation = createConversation(
      [
        ...initialConversation.messages,
        {
          message_id: 'message-2',
          role: 'assistant',
          content: 'Fresh persisted answer',
          created_at: '2026-04-18T10:00:05Z',
        },
      ],
      ['Question A'],
    );

    apiGetMock.mockResolvedValue(okResponse(refreshedConversation));
    apiPostMock.mockResolvedValue(
      okResponse<ReportChatSuggestionsResponse>({ suggested_questions: ['Question A'] }),
    );

    render(
      <StrictMode>
        <ReportChatPanel
          reportId="report-1"
          initialConversation={initialConversation}
        />
      </StrictMode>,
    );

    expect(screen.getByText('Old question')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Fresh persisted answer')).toBeTruthy();
    });

    expect(apiGetMock).toHaveBeenCalledWith('/reports/report-1/chat');
  });

  it('recovers from a stuck stream when the assistant reply is already persisted on the server', async () => {
    const requestStartedAt = new Date().toISOString();
    const assistantCreatedAt = new Date(Date.now() + 1000).toISOString();
    const initialConversation = createConversation(
      [
        {
          message_id: 'message-1',
          role: 'assistant',
          content: 'Existing context',
          created_at: '2026-04-18T10:00:00Z',
        },
      ],
    );
    const recoveredConversation = createConversation(
      [
        ...initialConversation.messages,
        {
          message_id: 'user-message-2',
          role: 'user',
          content: 'Will this self-heal?',
          created_at: requestStartedAt,
        },
        {
          message_id: 'assistant-message-2',
          role: 'assistant',
          content: 'Recovered assistant answer',
          created_at: assistantCreatedAt,
        },
      ],
    );

    apiGetMock
      .mockResolvedValueOnce(okResponse(initialConversation))
      .mockResolvedValueOnce(okResponse(recoveredConversation));
    apiPostMock.mockResolvedValue(
      okResponse<ReportChatSuggestionsResponse>({ suggested_questions: [] }),
    );
    streamReportChatMock.mockImplementation(
      ({ signal }) =>
        new Promise((_, reject) => {
          signal?.addEventListener(
            'abort',
            () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })),
            { once: true },
          );
        }),
    );

    render(
      <StrictMode>
        <ReportChatPanel
          reportId="report-1"
          initialConversation={initialConversation}
        />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(
        apiGetMock.mock.calls.filter(([url]) => url === '/reports/report-1/chat').length,
      ).toBeGreaterThanOrEqual(1);
    });

    const input = document.getElementById('report-chat-message') as HTMLInputElement | null;
    expect(input).toBeTruthy();

    fireEvent.change(input!, { target: { value: 'Will this self-heal?' } });

    await waitFor(() => {
      expect(input?.value).toBe('Will this self-heal?');
    });

    const [sendButton] = screen.getAllByRole('button');
    await waitFor(() => {
      expect(sendButton?.hasAttribute('disabled')).toBe(false);
    });

    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(streamReportChatMock).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(
        apiGetMock.mock.calls.filter(([url]) => url === '/reports/report-1/chat').length,
      ).toBeGreaterThanOrEqual(2);
    }, { timeout: 4000 });

    await waitFor(() => {
      expect(screen.getByText('Recovered assistant answer')).toBeTruthy();
    }, { timeout: 4000 });

    expect(
      apiGetMock.mock.calls.some(([url]) => url === '/reports/report-1/chat'),
    ).toBe(true);
  });

  it('falls back to the appended server snapshot when exact message matching misses', async () => {
    const initialConversation = createConversation([
      {
        message_id: 'message-1',
        role: 'assistant',
        content: 'Existing context',
        created_at: '2026-04-18T10:00:00Z',
      },
    ]);
    const recoveredConversation = createConversation([
      ...initialConversation.messages,
      {
        message_id: 'user-message-2',
        role: 'user',
        content: 'Server-normalized question',
        created_at: '2026-04-18T10:10:00Z',
      },
      {
        message_id: 'assistant-message-2',
        role: 'assistant',
        content: 'Recovered via appended snapshot',
        created_at: '2026-04-18T10:10:01Z',
      },
    ]);

    apiGetMock
      .mockResolvedValueOnce(okResponse(initialConversation))
      .mockResolvedValueOnce(okResponse(recoveredConversation));
    apiPostMock.mockResolvedValue(
      okResponse<ReportChatSuggestionsResponse>({ suggested_questions: [] }),
    );
    streamReportChatMock.mockImplementation(
      ({ signal }) =>
        new Promise((_, reject) => {
          signal?.addEventListener(
            'abort',
            () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })),
            { once: true },
          );
        }),
    );

    render(
      <ReportChatPanel
        reportId="report-1"
        initialConversation={initialConversation}
      />,
    );

    await waitFor(() => {
      expect(
        apiGetMock.mock.calls.filter(([url]) => url === '/reports/report-1/chat').length,
      ).toBeGreaterThanOrEqual(1);
    });

    const input = document.getElementById('report-chat-message') as HTMLInputElement | null;
    expect(input).toBeTruthy();

    fireEvent.change(input!, { target: { value: 'Will this self-heal?' } });

    const [sendButton] = screen.getAllByRole('button');
    await waitFor(() => {
      expect(sendButton?.hasAttribute('disabled')).toBe(false);
    });

    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(
        apiGetMock.mock.calls.filter(([url]) => url === '/reports/report-1/chat').length,
      ).toBeGreaterThanOrEqual(2);
    }, { timeout: 4000 });

    await waitFor(() => {
      expect(screen.getByText('Recovered via appended snapshot')).toBeTruthy();
    }, { timeout: 4000 });
  });

  it('removes the unsaved user message when stream recovery fails', async () => {
    const initialConversation = createConversation([]);

    apiGetMock.mockResolvedValue(okResponse(initialConversation));
    apiPostMock.mockResolvedValue(
      okResponse<ReportChatSuggestionsResponse>({ suggested_questions: [] }),
    );
    streamReportChatMock.mockRejectedValue(new Error('stream failed'));

    render(
      <ReportChatPanel
        reportId="report-1"
        initialConversation={initialConversation}
      />,
    );

    await waitFor(() => {
      expect(
        apiGetMock.mock.calls.filter(([url]) => url === '/reports/report-1/chat').length,
      ).toBeGreaterThanOrEqual(1);
    });

    const input = document.getElementById('report-chat-message') as HTMLInputElement | null;
    expect(input).toBeTruthy();

    fireEvent.change(input!, { target: { value: 'Will this be removed?' } });

    const [sendButton] = screen.getAllByRole('button');
    await waitFor(() => {
      expect(sendButton?.hasAttribute('disabled')).toBe(false);
    });

    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText('stream failed')).toBeTruthy();
    });
    expect(screen.queryByText('Will this be removed?')).toBeNull();
  });
});
