import { getApiBaseUrl, refreshAuthTokens, triggerForceLogout } from '@/api/client';

interface StreamMetaPayload {
  conversation_id: string;
  user_message_id: string;
}

interface StreamDonePayload {
  message_id: string;
  role: 'assistant';
  content: string;
  created_at: string;
}

interface StreamErrorPayload {
  message?: string;
}

interface StreamReportChatOptions {
  reportId: string;
  message: string;
  signal?: AbortSignal;
  idleTimeoutMs?: number;
  onMeta?: (payload: StreamMetaPayload) => void;
  onDelta?: (chunk: string) => void;
  onDone?: (payload: StreamDonePayload) => void;
}

export interface StreamReportChatResult {
  doneEventReceived: boolean;
  receivedDelta: boolean;
}

const DEFAULT_STREAM_IDLE_TIMEOUT_MS = 6000;

function parseSseEventBlock(block: string): { event: string; data: string } | null {
  const lines = block.split('\n');
  let event = '';
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (!event || dataLines.length === 0) {
    return null;
  }

  return {
    event,
    data: dataLines.join('\n'),
  };
}

async function openChatStream(
  reportId: string,
  message: string,
  token: string,
  signal?: AbortSignal,
) {
  return fetch(`${getApiBaseUrl()}/reports/${reportId}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
    signal,
  });
}

async function ensureStreamResponse(
  reportId: string,
  message: string,
  signal?: AbortSignal,
): Promise<Response> {
  const accessToken = localStorage.getItem('access_token');
  if (!accessToken) {
    triggerForceLogout();
    throw new Error('登录状态已失效，请重新登录');
  }

  let response = await openChatStream(reportId, message, accessToken, signal);
  if (response.status !== 401) {
    return response;
  }

  const refreshedToken = await refreshAuthTokens();
  if (!refreshedToken) {
    throw new Error('登录状态已失效，请重新登录');
  }

  response = await openChatStream(reportId, message, refreshedToken, signal);
  if (response.status === 401) {
    triggerForceLogout();
    throw new Error('登录状态已失效，请重新登录');
  }

  return response;
}

function normalizeSseBuffer(buffer: string) {
  return buffer.replace(/\r\n/g, '\n');
}

function createAbortError() {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('The operation was aborted.', 'AbortError');
  }

  return Object.assign(new Error('The operation was aborted.'), {
    name: 'AbortError',
  });
}

async function readStreamChunkWithGuards(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  signal: AbortSignal | undefined,
  idleTimeoutMs: number,
) {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let abortHandler: (() => void) | null = null;

  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_, reject) => {
        if (!signal) {
          return;
        }

        if (signal.aborted) {
          reject(createAbortError());
          return;
        }

        abortHandler = () => reject(createAbortError());
        signal.addEventListener('abort', abortHandler, { once: true });
      }),
      new Promise<never>((_, reject) => {
        if (idleTimeoutMs <= 0) {
          return;
        }

        timeoutId = setTimeout(() => {
          reject(new Error('问答流长时间未返回新内容，请稍后重试'));
        }, idleTimeoutMs);
      }),
    ]);
  } finally {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
    if (signal && abortHandler) {
      signal.removeEventListener('abort', abortHandler);
    }
  }
}

export async function streamReportChat({
  reportId,
  message,
  signal,
  idleTimeoutMs = DEFAULT_STREAM_IDLE_TIMEOUT_MS,
  onMeta,
  onDelta,
  onDone,
}: StreamReportChatOptions): Promise<StreamReportChatResult> {
  const response = await ensureStreamResponse(reportId, message, signal);

  if (!response.ok) {
    let payload: { message?: string } | null = null;
    try {
      payload = (await response.json()) as { message?: string } | null;
    } catch {
      payload = null;
    }
    throw new Error(payload?.message || '问答请求失败');
  }

  if (!response.body) {
    throw new Error('问答流响应为空');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let doneEventReceived = false;
  let receivedDelta = false;

  const consumeEventBlock = (block: string) => {
    const normalizedBlock = block.trim();
    if (!normalizedBlock) {
      return;
    }

    const eventBlock = parseSseEventBlock(normalizedBlock);
    if (!eventBlock) {
      return;
    }

    const parsed = JSON.parse(eventBlock.data) as
      | StreamMetaPayload
      | StreamDonePayload
      | StreamErrorPayload
      | { text?: string };

    if (eventBlock.event === 'meta') {
      onMeta?.(parsed as StreamMetaPayload);
      return;
    }

    if (eventBlock.event === 'delta') {
      const chunk = (parsed as { text?: string }).text || '';
      if (chunk) {
        receivedDelta = true;
      }
      onDelta?.(chunk);
      return;
    }

    if (eventBlock.event === 'done') {
      doneEventReceived = true;
      onDone?.(parsed as StreamDonePayload);
      return;
    }

    if (eventBlock.event === 'error') {
      throw new Error((parsed as StreamErrorPayload).message || '问答生成失败');
    }
  };

  while (true) {
    const { done, value } = await readStreamChunkWithGuards(
      reader,
      signal,
      idleTimeoutMs,
    );
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = normalizeSseBuffer(buffer);

    let separatorIndex = buffer.indexOf('\n\n');
    while (separatorIndex >= 0) {
      const block = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      consumeEventBlock(block);
      separatorIndex = buffer.indexOf('\n\n');
    }

    if (done) {
      break;
    }
  }

  const trailingBlock = buffer.trim();
  if (trailingBlock) {
    consumeEventBlock(trailingBlock);
  }

  if (!doneEventReceived) {
    throw new Error(
      receivedDelta ? '回答中断，未保存，请重试' : '问答流已结束，但未收到完成事件',
    );
  }

  return {
    doneEventReceived,
    receivedDelta,
  };
}
