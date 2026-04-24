import type { ReportConversationResponse } from '@/types/report-chat';

export interface PendingRecoveryRequest {
  baselineMessageCount: number;
  content: string;
  startedAt: string;
  userMessageId: string | null;
}

export const PENDING_RECOVERY_INTERVAL_MS = 2000;
const PENDING_RECOVERY_MATCH_WINDOW_MS = 30_000;

export function findRecoveredUserMessageIndex(
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

export function hasRecoveredAssistantReply(
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
