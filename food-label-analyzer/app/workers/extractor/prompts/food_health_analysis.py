"""OCR、YOLO、RAG、LLM 等外部能力的封装。"""


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

【营养风险分级口径 — 必须保守、基于证据】
1. 营养风险必须优先依据 nutrition_json 中的 daily_reference_percent、value、unit 判断，不得只因为配料中出现"白砂糖"、"食用油脂制品"就直接判定为高糖或高脂。
2. 对限制性营养素（脂肪、饱和脂肪、反式脂肪、糖、钠）：
   - NRV 或参考占比 <10%：一般不列为主要风险，可表述为"含量较低/适中"。
   - 10%-19%：只能表述为"含量不低/需适量"，hazards.level 最多为 medium，不得写成高风险、严重风险，也不要写"易增加心血管负担"这类强结论。
   - 20%-29%：可表述为"偏高/需要关注"，hazards.level 可为 medium。
   - >=30%：才可作为 high 风险重点提示；>=50% 才可使用"明显偏高/长期过量风险较高"。
3. 若 nutrition_json 没有"糖"或"添加糖"项目，不能直接判定为高糖食品；只能说"配料中含糖，建议控制频率"，除非 OCR 明确给出糖含量或添加糖靠前且产品类别本身高度含糖。
4. "反式脂肪 0g"应视为正面或中性信息，禁止写成反式脂肪风险。
5. 普通食品配料（如小麦粉、全麦粉、白砂糖、植物油、乳粉）不要强行归为食品添加剂；function_category 可填写 null、"原料"、"甜味来源"、"油脂来源"等自然分类。只有防腐剂、甜味剂、乳化剂、着色剂、增稠剂、抗氧化剂、酸度调节剂等才归为添加剂功能类别。
6. 输出 summary、hazards、health_advice 时使用克制表述：没有 >=20% 的限制性营养素时，不要写"高糖高脂"、"心血管负担"、"肥胖风险高"等结论；可写"建议控制食用频率、注意总量搭配"。

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

【营养风险分级口径 — 必须保守、基于证据】
1. 限制性营养素 NRV 或参考占比 10%-19% 只能表述为"含量不低/需适量"，hazards.level 最多为 medium，不得写成高风险，也不要写"易增加心血管负担"。
2. 只有 >=30% 才作为 high 风险重点提示；>=50% 才使用"明显偏高/长期过量风险较高"。
3. 没有糖含量或添加糖数据时，不能直接判定为高糖食品；只能说配料中含糖，建议控制频率。
4. "反式脂肪 0g"不得写成风险。
5. 普通食品原料不要强行归为食品添加剂。

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
