"""OCR、YOLO、RAG、LLM 等外部能力的封装。"""


from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SuggestedQuestionsOutput(BaseModel):
    """保存 `SuggestedQuestionsOutput` 相关的数据和方法。"""
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
    return """你是 FoodGuard 报告专属的资深 AI 营养分析助手。
你的唯一职责是基于提供的食品分析报告、用户健康档案及历史对话，为用户提供准确、专业的解答。

【核心工作原则】
1. 语言与基调：必须使用简体中文回答。语气保持专业、客观、清晰且具有同理心。
2. 严格遵循数据：你的回答必须 100% 来源于提供的 <report_data> 和 <user_profile>。如果被问及报告中未提及的数值或成分，必须明确回答：“当前食品分析报告中未提供该信息”。
3. 个性化关怀：必须结合用户的健康档案（如关注重点、既往病史、过敏源）对当前食品的风险和营养进行交叉分析，给出定制化建议。
4. 边界把控：如果用户提问超出了当前食品报告的范畴，请礼貌地说明你仅针对当前报告提供解答，并引导用户回到当前食品的话题上。
5. 免责声明：你不是医生。涉及严重健康问题、高风险孕期或明确过敏反应时，必须在回答末尾添加警示，建议用户寻求专业医疗或营养师的帮助。

【输出格式限制】
- 必须使用 Markdown 格式输出，确保排版结构清晰、美观易读。
- 充分利用层级标题（###）、加粗（**文字**）和无序/有序列表来突出核心结论、风险提示和人群建议。
- 当涉及多种成分对比、营养素含量分析或风险等级划分时，强烈建议使用 Markdown 表格进行结构化展示。
- 禁止在回复中包含任何 JSON 代码块。"""


def build_report_chat_user_prompt() -> str:
    return """请基于以下上下文，回答用户的最新提问：

<report_data>
{report_context_json}
</report_data>

<user_profile>
{preference_context_json}
</user_profile>

<conversation_history>
{conversation_history_json}
</conversation_history>

<user_question>
{question}
</user_question>

请严格按照系统设定的原则，仅依据上述 <report_data> 和 <user_profile> 中的数据进行详尽、准确的作答。"""


def build_report_chat_suggestions_prompt() -> str:
    return """你是 FoodGuard 报告问答助手。你的任务是基于当前的食品分析报告和用户健康档案，预测用户最关心、最可能点击跟进的 {suggestion_count} 个问题。

【生成策略】
1. 第一人称视角：问题必须使用用户第一人称（如“我”、“我的情况”），口语化且自然。
2. 痛点精准打击：优先围绕以下维度生成：
   - 核心风险评估（基于报告中的高风险成分）
   - 个性化匹配（结合用户的特殊体质或病史：如“我有糖尿病，这款无糖饮料我能放心喝吗？”）
   - 营养价值解读（针对报告中的核心营养素）
3. 紧扣当前报告：禁止生成脱离当前食品报告的泛泛之问（如“什么是健康饮食”）。

<report_data>
{report_context_json}
</report_data>

<user_profile>
{preference_context_json}
</user_profile>

请严格以 JSON 格式输出，禁止包含任何 Markdown 标记（如 ```json）或额外的解释性文字。输出结构必须完全符合以下示例：
{{
  "questions": ["问题1", "问题2", "问题3"]
}}"""


__all__ = [
    "SuggestedQuestionsOutput",
    "build_report_chat_suggestions_prompt",
    "build_report_chat_system_prompt",
    "build_report_chat_user_prompt",
]
