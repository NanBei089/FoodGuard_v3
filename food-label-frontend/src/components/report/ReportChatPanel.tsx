import { memo, useEffect, useRef, useState } from 'react';
import { Loader2, MessageSquareText, SendHorizontal, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
  initialConversation?: ReportConversationResponse | null;
}

interface PendingRecoveryRequest {
  baselineMessageCount: number;
  content: string;
  startedAt: string;
  userMessageId: string | null;
}

const PENDING_RECOVERY_INTERVAL_MS = 2000;
const PENDING_RECOVERY_MATCH_WINDOW_MS = 30_000;
const STREAM_IDLE_TIMEOUT_MS = 6000;

function nowIsoString() {
  return new Date().toISOString();
}

function buildConversationState(
  reportId: string,
  initialConversation: ReportConversationResponse | null,
) {
  if (initialConversation?.report_id !== reportId) {
    return {
      conversationId: '',
      messages: [] as LocalChatMessage[],
      suggestions: [] as string[],
      hasConversation: false,
    };
  }

  return {
    conversationId: initialConversation.conversation_id,
    messages: [...initialConversation.messages],
    suggestions: [...(initialConversation.suggested_questions || [])],
    hasConversation: true,
  };
}

function findRecoveredUserMessageIndex(
  messages: ReportConversationResponse['messages'],
  pendingRequest: PendingRecoveryRequest,
) {
  if (pendingRequest.userMessageId) {
    const messageIndex = messages.findIndex(
      (item) => item.message_id === pendingRequest.userMessageId,
    );
    if (messageIndex >= 0) {
      return messageIndex;
    }
  }

  const requestStartedAtMs = Date.parse(pendingRequest.startedAt);

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const item = messages[index];
    if (item.role !== 'user' || item.content !== pendingRequest.content) {
      continue;
    }

    const messageCreatedAtMs = Date.parse(item.created_at);
    if (
      Number.isNaN(requestStartedAtMs) ||
      Number.isNaN(messageCreatedAtMs) ||
      messageCreatedAtMs >= requestStartedAtMs - PENDING_RECOVERY_MATCH_WINDOW_MS
    ) {
      return index;
    }
  }

  return -1;
}

function hasRecoveredAssistantReply(
  messages: ReportConversationResponse['messages'],
  pendingRequest: PendingRecoveryRequest,
) {
  const userMessageIndex = findRecoveredUserMessageIndex(messages, pendingRequest);
  if (
    userMessageIndex >= 0 &&
    messages.slice(userMessageIndex + 1).some((item) => item.role === 'assistant')
  ) {
    return true;
  }

  const newMessages = messages.slice(pendingRequest.baselineMessageCount);
  return (
    newMessages.some((item) => item.role === 'user') &&
    newMessages.some((item) => item.role === 'assistant')
  );
}

function ChatMessageContent({
  content,
  isAssistant,
  pending = false,
}: {
  content: string;
  isAssistant: boolean;
  pending?: boolean;
}) {
  if (!content) {
    return <div>{pending ? '正在生成回答...' : ''}</div>;
  }

  if (!isAssistant) {
    return <div className="whitespace-pre-wrap break-words">{content}</div>;
  }

  return (
    <div className="break-words text-sm leading-6 text-slate-700">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-2 mt-4 text-base font-semibold text-slate-900 first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-4 text-base font-semibold text-slate-900 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 mt-3 text-sm font-semibold text-slate-900 first:mt-0">{children}</h3>
          ),
          p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
          ul: ({ children }) => <ul className="mb-3 ml-5 list-disc space-y-1 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-3 ml-5 list-decimal space-y-1 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="mb-3 border-l-4 border-emerald-200 bg-emerald-50/60 px-3 py-2 text-slate-700 last:mb-0">
              {children}
            </blockquote>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-700 underline underline-offset-2"
            >
              {children}
            </a>
          ),
          code: ({ children, className }) => {
            if (className) {
              return (
                <code className="block overflow-x-auto rounded-xl bg-slate-900/95 px-3 py-2 text-xs text-slate-100">
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[0.85em] text-slate-800">
                {children}
              </code>
            );
          },
          pre: ({ children }) => <pre className="mb-3 last:mb-0">{children}</pre>,
          table: ({ children }) => (
            <div className="mb-3 overflow-x-auto rounded-xl border border-slate-200 last:mb-0">
              <table className="min-w-full border-collapse text-left text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-slate-100 text-slate-700">{children}</thead>,
          th: ({ children }) => (
            <th className="border-b border-slate-200 px-3 py-2 font-semibold">{children}</th>
          ),
          td: ({ children }) => <td className="border-b border-slate-100 px-3 py-2 align-top">{children}</td>,
          hr: () => <hr className="my-3 border-slate-200" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const ReportChatPanel = memo(function ReportChatPanel({
  reportId,
  initialConversation = null,
}: ReportChatPanelProps) {
  const [conversationId, setConversationId] = useState(
    () => buildConversationState(reportId, initialConversation).conversationId,
  );
  const [messages, setMessages] = useState<LocalChatMessage[]>(
    () => buildConversationState(reportId, initialConversation).messages,
  );
  const [suggestions, setSuggestions] = useState<string[]>(
    () => buildConversationState(reportId, initialConversation).suggestions,
  );
  const [loading, setLoading] = useState(
    () => !buildConversationState(reportId, initialConversation).hasConversation,
  );
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const activeStreamRef = useRef<AbortController | null>(null);
  const recoveryTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recoveryInFlightRef = useRef(false);
  const pendingRequestRef = useRef<PendingRecoveryRequest | null>(null);
  const mountedRef = useRef(true);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  const canSend = input.trim().length > 0 && !sending;

  const clearPendingRecovery = () => {
    if (recoveryTimerRef.current !== null) {
      clearInterval(recoveryTimerRef.current);
      recoveryTimerRef.current = null;
    }
    recoveryInFlightRef.current = false;
  };

  const applyConversationSnapshot = (conversation: ReportConversationResponse) => {
    setConversationId(conversation.conversation_id);
    setMessages([...conversation.messages]);
    setSuggestions([...(conversation.suggested_questions || [])]);
    setLoading(false);
  };

  const tryRecoverPendingConversation = async (controller: AbortController): Promise<boolean> => {
    const pendingRequest = pendingRequestRef.current;
    if (!pendingRequest || recoveryInFlightRef.current) {
      return false;
    }

    recoveryInFlightRef.current = true;
    try {
      const res = await apiGet<ReportConversationResponse | null>(`/reports/${reportId}/chat`);
      if (!mountedRef.current || res.code !== 0 || !res.data) {
        return false;
      }

      const hasAssistantReply = hasRecoveredAssistantReply(
        res.data.messages,
        pendingRequest,
      );
      if (!hasAssistantReply) {
        return false;
      }

      clearPendingRecovery();
      pendingRequestRef.current = null;
      applyConversationSnapshot(res.data);
      setError('');
      setSending(false);

      if (!controller.signal.aborted) {
        controller.abort();
      }
      return true;
    } catch {
      return false;
    } finally {
      recoveryInFlightRef.current = false;
    }
  };

  const startPendingRecovery = (controller: AbortController) => {
    clearPendingRecovery();
    recoveryTimerRef.current = setInterval(() => {
      void tryRecoverPendingConversation(controller);
    }, PENDING_RECOVERY_INTERVAL_MS);
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeStreamRef.current?.abort();
      clearPendingRecovery();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    activeStreamRef.current?.abort();
    activeStreamRef.current = null;
    clearPendingRecovery();
    pendingRequestRef.current = null;
    setSending(false);

    const initialState = buildConversationState(reportId, initialConversation);
    setConversationId(initialState.conversationId);
    setMessages(initialState.messages);
    setSuggestions(initialState.suggestions);
    setError('');
    setSuggestionsLoading(false);

    const loadSuggestions = async () => {
      setSuggestionsLoading(true);
      try {
        const suggestionsRes = await apiPost<ReportChatSuggestionsResponse>(
          `/reports/${reportId}/chat/suggestions`,
        );
        if (!cancelled && suggestionsRes.code === 0 && suggestionsRes.data) {
          setSuggestions(suggestionsRes.data.suggested_questions || []);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError((current) => current || getErrorMessage(err, '加载快捷提问失败'));
        }
      } finally {
        if (!cancelled) {
          setSuggestionsLoading(false);
        }
      }
    };

    const loadConversation = async (preserveExistingState: boolean) => {
      if (!preserveExistingState) {
        setLoading(true);
        setError('');
        setConversationId('');
        setMessages([]);
        setSuggestions([]);
        setSuggestionsLoading(false);
      } else {
        setLoading(false);
      }

      try {
        const res = await apiGet<ReportConversationResponse | null>(`/reports/${reportId}/chat`);
        if (cancelled) {
          return;
        }
        if (res.code !== 0) {
          if (!preserveExistingState) {
            setError(res.message || '加载问答会话失败');
          }
          return;
        }

        if (!res.data) {
          if (!preserveExistingState) {
            setConversationId('');
            setMessages([]);
            setSuggestions([]);
          }
          if (initialState.suggestions.length === 0 || !preserveExistingState) {
            await loadSuggestions();
          }
          return;
        }

        applyConversationSnapshot(res.data);

        if ((res.data.suggested_questions || []).length === 0) {
          await loadSuggestions();
        }
      } catch (err: unknown) {
        if (!cancelled && !preserveExistingState) {
          setError(getErrorMessage(err, '加载问答会话失败'));
        }
      } finally {
        if (!cancelled && !preserveExistingState) {
          setLoading(false);
        }
      }
    };

    if (initialState.hasConversation) {
      setLoading(false);
      if (initialState.suggestions.length === 0) {
        void loadSuggestions();
      }
      void loadConversation(true);
    } else {
      void loadConversation(false);
    }

    return () => {
      cancelled = true;
      clearPendingRecovery();
      if (activeStreamRef.current) {
        activeStreamRef.current.abort();
        activeStreamRef.current = null;
      }
    };
  }, [reportId, initialConversation]);

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
    const requestStartedAt = nowIsoString();
    const tempBase = `${Date.now()}`;
    const tempUserId = `temp-user-${tempBase}`;
    const tempAssistantId = `temp-assistant-${tempBase}`;
    pendingRequestRef.current = {
      baselineMessageCount: messages.length,
      content: nextMessage,
      startedAt: requestStartedAt,
      userMessageId: null,
    };
    clearPendingRecovery();

    setMessages((current) => [
      ...current,
      {
        message_id: tempUserId,
        role: 'user',
        content: nextMessage,
        created_at: requestStartedAt,
      },
      {
        message_id: tempAssistantId,
        role: 'assistant',
        content: '',
        created_at: requestStartedAt,
        pending: true,
      },
    ]);
    setSending(true);

    activeStreamRef.current?.abort();
    const controller = new AbortController();
    activeStreamRef.current = controller;
    startPendingRecovery(controller);
    const isActiveController = () =>
      mountedRef.current &&
      activeStreamRef.current === controller &&
      !controller.signal.aborted;

    try {
      await streamReportChat({
        reportId,
        message: nextMessage,
        signal: controller.signal,
        idleTimeoutMs: STREAM_IDLE_TIMEOUT_MS,
        onMeta: (payload) => {
          if (!isActiveController()) {
            return;
          }
          if (payload.conversation_id) {
            setConversationId(payload.conversation_id);
          }
          if (payload.user_message_id) {
            if (pendingRequestRef.current) {
              pendingRequestRef.current = {
                ...pendingRequestRef.current,
                userMessageId: payload.user_message_id,
              };
            }
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
          clearPendingRecovery();
          pendingRequestRef.current = null;
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
        const recovered = await tryRecoverPendingConversation(controller);
        if (!recovered) {
          clearPendingRecovery();
          pendingRequestRef.current = null;
          setMessages((current) => current.filter((item) => item.message_id !== tempAssistantId));
          setError(getErrorMessage(err, '回答中断，未保存，请重试'));
        }
      }
    } finally {
      clearPendingRecovery();
      pendingRequestRef.current = null;
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
            我会结合这份报告、你的健康偏好和历史对话持续回答。
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
              <div key={index} className="h-9 animate-pulse rounded-xl bg-slate-100" />
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
                    isAssistant ? 'bg-white text-slate-700' : 'bg-slate-900 text-white'
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
                  <ChatMessageContent
                    content={item.content}
                    isAssistant={isAssistant}
                    pending={item.pending}
                  />
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
          id="report-chat-message"
          name="report-chat-message"
          aria-label="继续追问这份报告"
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
});
