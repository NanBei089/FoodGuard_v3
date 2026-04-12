from __future__ import annotations

import re
from typing import Any


def _normalize_ingredient_term(term: str) -> str:
    return re.sub(r"\s+", "", str(term or "").strip().lower())

def _dedupe_ingredient_terms(ingredient_terms: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in ingredient_terms:
        normalized = _normalize_ingredient_term(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(str(term).strip())
    return deduped

def _build_rag_lookup(rag_results_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    retrieval_results = rag_results_json.get("retrieval_results")
    if not isinstance(retrieval_results, list):
        return lookup

    for item in retrieval_results:
        if not isinstance(item, dict):
            continue

        matches = item.get("matches")
        first_match = matches[0] if isinstance(matches, list) and matches else None
        function_category = None
        if isinstance(first_match, dict):
            raw_category = first_match.get("function_category")
            if isinstance(raw_category, str) and raw_category.strip():
                function_category = raw_category.strip()

        payload = {
            "function_category": function_category,
            "retrieved": bool(item.get("retrieved")),
        }
        for raw_key in (item.get("raw_term"), item.get("normalized_term")):
            normalized = _normalize_ingredient_term(str(raw_key or ""))
            if normalized and normalized not in lookup:
                lookup[normalized] = payload
    return lookup

_COMMON_INGREDIENT_INFO: dict[str, tuple[str, str | None]] = {
    "水": ("食品加工中的基础溶剂和调配介质，本身风险较低，主要影响产品形态与口感。", None),
    "饮用水": ("常见食品基底原料，用于溶解和调配其他成分，本身通常不构成额外健康负担。", None),
    "食用盐": ("提供咸味的基础调味料，过量摄入可能增加钠负担和高血压风险，需控制总摄入量。", None),
    "白砂糖": ("精制蔗糖，主要提供甜味和能量，长期过量摄入可能增加肥胖和龋齿风险。", None),
    "蔗糖": ("常用甜味来源，可改善风味和组织状态，但过量摄入会增加糖负担。", None),
    "葡萄糖": ("易吸收的单糖，常用于调味和补充能量，血糖管理人群需关注摄入量。", None),
    "果葡糖浆": ("常见甜味配料，可改善口感与保湿性，过量摄入会提高额外糖摄入风险。", None),
    "食用植物油": ("提供脂肪酸和能量的常见油脂原料，应结合总脂肪和脂肪酸类型综合评估。", None),
    "小麦粉": ("面制品常见基础原料，主要提供碳水化合物，麸质敏感或过敏人群需特别留意。", None),
    "大豆": ("优质植物蛋白来源，也属于常见过敏原之一，对大豆敏感者应避免食用。", None),
    "牛奶": ("提供蛋白质和钙的常见乳原料，但属于常见过敏原，乳糖不耐受者也需注意。", None),
    "乳粉": ("浓缩乳制品原料，可提升乳香和蛋白质含量，乳制品过敏者应谨慎。", None),
    "鸡蛋": ("优质蛋白来源，常用于改善口感和结构，也是常见过敏原之一。", None),
    "麦芽糊精": ("常用于增稠、赋形或改善口感，升糖较快，控糖人群需关注摄入量。", "增稠剂"),
    "香精": ("用于增强或模拟风味的食品用香料制品，建议结合摄入频率和人群敏感性综合判断。", "食用香精"),
    "食用香精": ("用于增强或调整风味的食品添加剂，通常用量不高，但儿童和敏感人群不宜长期高频摄入。", "食用香精"),
}

def _infer_fallback_risk(term: str) -> str:
    lowered = _normalize_ingredient_term(term)
    if any(keyword in lowered for keyword in ("氢化", "反式", "植脂末")):
        return "danger"
    if any(
        keyword in lowered
        for keyword in (
            "糖",
            "盐",
            "钠",
            "油",
            "脂",
            "黄油",
            "奶油",
            "香精",
            "香料",
            "色素",
            "防腐",
            "甜味剂",
            "乳化",
            "增稠",
        )
    ):
        return "warning"
    return "safe"

def _build_fallback_ingredient_item(
    term: str,
    rag_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    function_category = None
    if isinstance(rag_meta, dict):
        raw_category = rag_meta.get("function_category")
        if isinstance(raw_category, str) and raw_category.strip():
            function_category = raw_category.strip()

    normalized = _normalize_ingredient_term(term)
    common_info = _COMMON_INGREDIENT_INFO.get(normalized)
    if common_info is not None:
        description, default_category = common_info
        return {
            "name": term,
            "risk": _infer_fallback_risk(term),
            "description": description,
            "function_category": function_category or default_category,
            "rules": [],
        }

    risk = _infer_fallback_risk(term)
    if risk == "danger":
        description = (
            f"{term}属于需要重点关注的加工配料，可能带来较高代谢或心血管负担，建议控制摄入频率和总量。"
        )
    elif risk == "warning":
        description = (
            f"{term}在食品中多用于调味、改善口感或稳定性，建议结合配料排序和整体营养负担综合判断。"
        )
    else:
        description = (
            f"{term}常见于食品配方中，当前未见明显高风险信号，但仍应结合食用场景和个人体质综合评估。"
        )

    return {
        "name": term,
        "risk": risk,
        "description": description,
        "function_category": function_category,
        "rules": [],
    }

def _ensure_ingredient_coverage(
    llm_output_json: dict[str, Any],
    ingredient_terms: list[str],
    rag_results_json: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(llm_output_json, dict):
        return {}

    expected_terms = _dedupe_ingredient_terms(ingredient_terms)
    if not expected_terms:
        return llm_output_json

    raw_items = llm_output_json.get("ingredients")
    current_items = raw_items if isinstance(raw_items, list) else []
    covered_terms: set[str] = set()
    normalized_items: list[dict[str, Any]] = []

    for item in current_items:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        normalized = _normalize_ingredient_term(raw_name)
        if not normalized or normalized in covered_terms:
            continue
        covered_terms.add(normalized)
        normalized_items.append(item)

    rag_lookup = _build_rag_lookup(rag_results_json)
    for term in expected_terms:
        normalized = _normalize_ingredient_term(term)
        if normalized in covered_terms:
            continue
        normalized_items.append(
            _build_fallback_ingredient_item(term, rag_lookup.get(normalized))
        )
        covered_terms.add(normalized)

    llm_output_json["ingredients"] = normalized_items
    return llm_output_json
