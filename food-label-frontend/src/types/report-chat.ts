export interface ReportConversationMessage {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface ReportConversationResponse {
  conversation_id: string;
  report_id: string;
  suggested_questions: string[];
  messages: ReportConversationMessage[];
}

export interface ReportChatSuggestionsResponse {
  suggested_questions: string[];
}

export interface ReportChatAskRequest {
  message: string;
}
