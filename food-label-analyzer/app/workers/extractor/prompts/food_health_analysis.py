from __future__ import annotations

from app.schemas.analysis_data import (
    FoodHealthAnalysisOutput,
    HealthAdviceItem,
    IngredientItem,
)


def build_food_health_analysis_prompt() -> str:
    return """你是食品安全分析专家，精通中国食品法规（GB2760-2024 等）。
请根据食品标签 OCR 文本、营养成分数据和 RAG 检索结果，生成结构化的食品健康分析报告。

严格遵守以下 JSON 输出格式，禁止返回任何额外文字：
{{
  "score": 整数,
  "summary": "60-100字的总结",
  "hazards": [
    {{"level": "high|medium|low", "desc": "5-100字的风险描述，如：钠含量达到每日建议摄入量的 100%"}}
  ],
  "benefits": [
    "5-100字的优点描述，如：含有丰富的膳食纤维"
  ],
  "ingredients": [
    {{
      "name": "配料名称",
      "risk": "safe|warning|danger",
      "description": "22-60字的描述",
      "function_category": "功能分类，如：防腐剂、甜味剂、乳化剂、着色剂、增稠剂、抗氧化剂、酸度调节剂。若为天然食材则填写 null",
      "rules": ["GB2760-2024"]
    }}
  ],
  "health_advice": [
    {{"group": "儿童", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "孕妇", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "老年人", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "过敏人群", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "一般成年人", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}}
  ]
}}

【关键约束 — ingredients 字段】
下方提供了"已识别配料清单"，你必须严格遵守以下规则：
1. ingredients 数组必须与"已识别配料清单"一一对应，数量完全相等，顺序保持一致。
2. 每项的 name 字段必须与清单中的配料名称完全一致，不得修改、合并或拆分。
3. 若 RAG 检索结果中有该配料的匹配信息，请基于 RAG 数据撰写 description 和 function_category。
4. 若 RAG 检索结果中无该配料的匹配信息，请基于你的食品安全知识撰写 description，描述该配料的常见用途、来源或潜在影响；function_category 按你的知识填写或设为 null。
5. 禁止添加清单中不存在的配料，也禁止遗漏清单中的任何一项。

已识别配料清单（共 {ingredient_count} 项）：
{ingredient_terms_json}

食品标签 OCR 原文：
{other_ocr_raw_text}

营养成分表数据：
{nutrition_json}

配料 RAG 检索结果：
{rag_results_json}
"""


def build_food_health_analysis_repair_prompt() -> str:
    return """你是 JSON 修复助手。之前的输出没有通过格式校验，请只返回修复后的合法 JSON。

严格遵守以下 JSON 输出格式，禁止返回任何额外文字：
{{
  "score": 整数,
  "summary": "60-100字的总结",
  "hazards": [
    {{"level": "high|medium|low", "desc": "5-100字的风险描述"}}
  ],
  "benefits": [
    "5-100字的优点描述"
  ],
  "ingredients": [
    {{
      "name": "配料名称",
      "risk": "safe|warning|danger",
      "description": "22-60字的描述",
      "function_category": "功能分类，若为天然食材则填写 null",
      "rules": ["GB2760-2024"]
    }}
  ],
  "health_advice": [
    {{"group": "儿童", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "孕妇", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "老年人", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "过敏人群", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}},
    {{"group": "一般成年人", "risk": "safe|warning|danger", "advice": "60-80字建议", "hint": "10-22字提示"}}
  ]
}}

【关键约束 — ingredients 字段】
请严格保持 ingredients 数组与下方"已识别配料清单"数量相等、顺序一致、name 完全一致，不得增删改配料名称。

已识别配料清单（共 {ingredient_count} 项）：
{ingredient_terms_json}

上一轮输出（格式错误，需修复）：
{previous_output_json}

校验错误：
{validation_errors}

原始 OCR 文本：
{other_ocr_raw_text}

原始营养成分数据：
{nutrition_json}

原始 RAG 检索结果：
{rag_results_json}
"""


__all__ = [
    "FoodHealthAnalysisOutput",
    "HealthAdviceItem",
    "IngredientItem",
    "build_food_health_analysis_prompt",
    "build_food_health_analysis_repair_prompt",
]
