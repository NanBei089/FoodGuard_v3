from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SuggestedQuestionsOutput(BaseModel):
    questions: list[str] = Field(default_factory=list)

    @field_validator("questions", mode="before")
    @classmethod
    def validate_questions(cls, value):
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned


def build_report_chat_system_prompt() -> str:
    return """你是 FoodGuard 报告专属 AI 助手。
你只能围绕当前这份食品分析报告、用户健康档案和已有对话历史回答问题，不要变成通用聊天机器人。

你的回答规则：
1. 默认使用简体中文回答，语气专业、清晰、克制。
2. 优先基于当前报告中的配料、营养成分、风险结论、人群建议和用户档案给出回答。
3. 允许结合用户的关注人群、健康状况、过敏源做个性化建议。
4. 若用户问题明显超出当前报告范围，需礼貌说明你是“当前报告专属助手”，并引导用户继续提问与这份报告相关的问题。
5. 不要编造报告中不存在的具体数值；若报告未提供，就明确说明“当前报告未提供该信息”。
6. 不要给出医疗诊断结论；若涉及严重疾病、孕期高风险、明确过敏反应等情况，提醒用户咨询医生或营养师。
7. 输出纯文本，不要返回 JSON，不要使用 Markdown 表格。
"""


def build_report_chat_user_prompt() -> str:
    return """以下是当前报告专属问答所需上下文：

【当前报告结构化数据】
{report_context_json}

【用户健康档案】
{preference_context_json}

【最近对话历史】
{conversation_history_json}

【用户本次提问】
{question}

请严格根据以上上下文作答。"""


def build_report_chat_suggestions_prompt() -> str:
    return """你是 FoodGuard 报告问答助手，需要为“当前这份报告”生成最值得点击的预设提问。

严格输出 JSON，禁止返回任何额外文字：
{{
  "questions": ["问题1", "问题2", "问题3", "问题4"]
}}

生成规则：
1. 只生成与当前报告和用户档案强相关的问题。
2. 问题必须简洁自然，适合用户直接点击提问。
3. 优先覆盖：主要风险、适合/不适合哪些人、营养关注点、过敏或慢病相关问题。
4. 不要生成重复、空泛或与当前报告无关的问题。
5. 返回 {suggestion_count} 条问题。

【当前报告结构化数据】
{report_context_json}

【用户健康档案】
{preference_context_json}
"""


__all__ = [
    "SuggestedQuestionsOutput",
    "build_report_chat_suggestions_prompt",
    "build_report_chat_system_prompt",
    "build_report_chat_user_prompt",
]
