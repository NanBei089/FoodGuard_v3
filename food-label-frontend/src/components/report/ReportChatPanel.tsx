import { useEffect, useRef, useState } from 'react';
import { Loader2, MessageSquareText, SendHorizontal, Sparkles } from 'lucide-react';
import { apiGet, apiPost } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { getErrorMessage } from '@/lib/api-errors';
import { streamReportChat } from '@/lib/report-chat';
import type {
  ReportChatSuggestionsResponse,
  ReportConversationMessage,
  ReportConversationResponse,
} from '@/types/report-chat';

interface LocalChatMessage extends ReportConversationMessage {
  pending?: boolean;
}

interface ReportChatPanelProps {
  reportId: string;
}

function nowIsoString() {
  return new Date().toISOString();
}

export function ReportChatPanel({ reportId }: ReportChatPanelProps) {
  const [conversationId, setConversationId] = useState('');
  const [messages, setMessages] = useState<LocalChatMessage[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const activeStreamRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  const canSend = input.trim().length > 0 && !sending;

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      activeStreamRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadConversation = async () => {
      setLoading(true);
      setError('');

      try {
        const res = await apiGet<ReportConversationResponse>(`/reports/${reportId}/chat`);
        if (cancelled) {
          return;
        }
        if (res.code !== 0 || !res.data) {
          setError(res.message || '加载问答会话失败');
          return;
        }

        setConversationId(res.data.conversation_id);
        setMessages(res.data.messages);
        setSuggestions(res.data.suggested_questions || []);

        if ((res.data.suggested_questions || []).length === 0) {
          setSuggestionsLoading(true);
          const suggestionsRes = await apiPost<ReportChatSuggestionsResponse>(
            `/reports/${reportId}/chat/suggestions`,
          );
          if (!cancelled && suggestionsRes.code === 0 && suggestionsRes.data) {
            setSuggestions(suggestionsRes.data.suggested_questions || []);
          }
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(getErrorMessage(err, '加载问答会话失败'));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setSuggestionsLoading(false);
        }
      }
    };

    loadConversation();

    return () => {
      cancelled = true;
      if (activeStreamRef.current) {
        activeStreamRef.current.abort();
        activeStreamRef.current = null;
      }
    };
  }, [reportId]);

  useEffect(() => {
    const container = messageListRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [messages]);

  const handleSend = async (preset?: string) => {
    const nextMessage = (preset ?? input).trim();
    if (!nextMessage || sending) {
      return;
    }

    setError('');
    setInput('');
    const tempBase = `${Date.now()}`;
    const tempUserId = `temp-user-${tempBase}`;
    const tempAssistantId = `temp-assistant-${tempBase}`;

    setMessages((current) => [
      ...current,
      {
        message_id: tempUserId,
        role: 'user',
        content: nextMessage,
        created_at: nowIsoString(),
      },
      {
        message_id: tempAssistantId,
        role: 'assistant',
        content: '',
        created_at: nowIsoString(),
        pending: true,
      },
    ]);
    setSending(true);

    activeStreamRef.current?.abort();
    const controller = new AbortController();
    activeStreamRef.current = controller;
    const isActiveController = () =>
      mountedRef.current &&
      activeStreamRef.current === controller &&
      !controller.signal.aborted;

    try {
      await streamReportChat({
        reportId,
        message: nextMessage,
        signal: controller.signal,
        onMeta: (payload) => {
          if (!isActiveController()) {
            return;
          }
          if (payload.conversation_id) {
            setConversationId(payload.conversation_id);
          }
          if (payload.user_message_id) {
            setMessages((current) =>
              current.map((item) =>
                item.message_id === tempUserId
                  ? { ...item, message_id: payload.user_message_id }
                  : item,
              ),
            );
          }
        },
        onDelta: (chunk) => {
          if (!chunk || !isActiveController()) {
            return;
          }
          setMessages((current) =>
            current.map((item) =>
              item.message_id === tempAssistantId
                ? { ...item, content: `${item.content}${chunk}` }
                : item,
            ),
          );
        },
        onDone: (payload) => {
          if (!isActiveController()) {
            return;
          }
          setMessages((current) =>
            current.map((item) =>
              item.message_id === tempAssistantId
                ? {
                    message_id: payload.message_id,
                    role: payload.role,
                    content: payload.content,
                    created_at: payload.created_at,
                  }
                : item,
            ),
          );
        },
      });
    } catch (err: unknown) {
      if (isActiveController() && (err as { name?: string }).name !== 'AbortError') {
        setMessages((current) => current.filter((item) => item.message_id !== tempAssistantId));
        setError(getErrorMessage(err, '问答生成失败，请稍后重试'));
      }
    } finally {
      const isLatestController = activeStreamRef.current === controller;
      if (isLatestController) {
        activeStreamRef.current = null;
      }
      if (mountedRef.current && (isLatestController || activeStreamRef.current === null)) {
        setSending(false);
      }
    }
  };

  return (
    <aside className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm xl:sticky xl:top-24">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
            <Sparkles className="h-3.5 w-3.5" />
            报告专属 AI 助手
          </div>
          <h3 className="text-lg font-bold text-slate-900">围绕当前报告继续深度讨论</h3>
          <p className="mt-1 text-sm leading-6 text-slate-500">
            我会结合这份报告、你的健康档案和历史对话持续回答。
          </p>
        </div>
        {conversationId && (
          <div className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-500">
            已绑定
          </div>
        )}
      </div>

      <div className="mb-5">
        <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
          快捷提问
        </div>
        {suggestionsLoading ? (
          <div className="grid gap-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="h-9 animate-pulse rounded-xl bg-slate-100"
              />
            ))}
          </div>
        ) : suggestions.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {suggestions.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => void handleSend(item)}
                disabled={sending}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-medium text-slate-600 transition hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {item}
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-sm text-slate-400">
            暂无快捷提问，直接输入你想了解的问题即可。
          </div>
        )}
      </div>

      <div
        ref={messageListRef}
        className="mb-4 flex max-h-[28rem] min-h-[20rem] flex-col gap-3 overflow-y-auto rounded-2xl bg-slate-50 p-3"
      >
        {loading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className={`h-20 animate-pulse rounded-2xl ${
                index % 2 === 0 ? 'mr-10 bg-white' : 'ml-10 bg-emerald-100/50'
              }`}
            />
          ))
        ) : messages.length > 0 ? (
          messages.map((item) => {
            const isAssistant = item.role === 'assistant';
            return (
              <div
                key={item.message_id}
                className={`flex ${isAssistant ? 'justify-start' : 'justify-end'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm ${
                    isAssistant
                      ? 'bg-white text-slate-700'
                      : 'bg-slate-900 text-white'
                  }`}
                >
                  <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] opacity-70">
                    {isAssistant ? (
                      <>
                        <MessageSquareText className="h-3.5 w-3.5" />
                        助手
                      </>
                    ) : (
                      '你'
                    )}
                    {item.pending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  </div>
                  <div>{item.content || (item.pending ? '正在生成回答...' : '')}</div>
                </div>
              </div>
            );
          })
        ) : (
          <div className="flex h-full flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white px-6 text-center">
            <MessageSquareText className="mb-3 h-10 w-10 text-slate-300" />
            <div className="text-sm font-medium text-slate-700">还没有开始讨论这份报告</div>
            <div className="mt-1 text-xs leading-5 text-slate-400">
              你可以直接提问，或点击上方快捷问题开始。
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-3 rounded-2xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="继续追问这份报告..."
          maxLength={500}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void handleSend();
            }
          }}
        />
        <Button
          type="button"
          onClick={() => void handleSend()}
          disabled={!canSend}
          isLoading={sending}
          className="shrink-0 px-4"
        >
          {!sending && <SendHorizontal className="h-4 w-4" />}
        </Button>
      </div>
    </aside>
  );
}
