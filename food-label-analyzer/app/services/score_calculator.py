"""健康分计算规则，根据营养、配料、过敏原和检索结果给出分数。"""


from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.schemas.analysis_data import (
    IngredientItem,
    IngredientRisk,
    NutritionData,
    NutritionItem,
    RAGResults,
)

NRV_THRESHOLDS = {
    "sodium": {"low": 20, "medium": 40, "high": 60, "very_high": 80},
    "sugar": {"low": 10, "medium": 25, "high": 50, "very_high": 100},
    "total_fat": {"low": 20, "medium": 40, "high": 60},
    "saturated_fat": {"low": 10, "medium": 20, "high": 30},
}

REFERENCE_LIMITS = {
    # OCR 只识别到钠含量、没有识别到 NRV% 时，用每日参考值补算占比。
    "sodium_mg": 2000.0,
    # 包装标签通常不写糖的 NRV%，这里用每日 50g 作为扣分参考。
    "sugar_g": 50.0,
}

ADDITIVE_PENALTIES = {
    "preservative": {"danger": 8, "warning": 4, "safe": 0},
    "color": {"danger": 6, "warning": 3, "safe": 0},
    "sweetener": {"danger": 7, "warning": 4, "safe": 0},
    "flavor_enhancer": {"danger": 3, "warning": 1, "safe": 0},
    "other": {"danger": 5, "warning": 2, "safe": 0},
}

ALLERGEN_PENALTIES = {
    0: 0,
    1: 5,
    2: 10,
    3: 15,
    4: 20,
}


@dataclass
class NutritionScore:
    """营养均衡各项分数和总分。"""
    protein_score: float = 100.0
    fat_score: float = 100.0
    carb_score: float = 100.0
    fiber_score: float = 100.0
    total: float = 100.0


@dataclass
class ComponentScores:
    """健康分的各个组成部分。"""
    nutrition: NutritionScore = field(default_factory=NutritionScore)
    sodium: float = 100.0
    sugar: float = 100.0
    additives: float = 100.0
    allergens: float = 100.0


def _parse_nrv(nrv_str: str | None) -> float:
    if not nrv_str:
        return 0.0
    try:
        cleaned = nrv_str.strip().replace("%", "").replace("％", "")
        return float(cleaned)
    except (ValueError, AttributeError):
        return 0.0


def _parse_nutrition_value(value_str: str) -> float:
    if not value_str:
        return 0.0
    try:
        return float(value_str.strip())
    except (ValueError, AttributeError):
        return 0.0


def _estimate_nrv_from_amount(item: NutritionItem, reference_key: str) -> float:
    """把营养含量换算成每日参考值百分比。"""
    value = _parse_nutrition_value(item.value)
    if value <= 0:
        return 0.0
    unit = item.unit.lower()
    if reference_key.endswith("_mg") and unit == "g":
        value *= 1000
    elif reference_key.endswith("_g") and unit == "mg":
        value /= 1000
    reference = REFERENCE_LIMITS[reference_key]
    return value / reference * 100


def _score_limit_nrv(nrv: float) -> float:
    """按每日参考值占比给糖、钠这类限制营养素打分。"""
    if nrv <= 0:
        return 100.0
    if nrv <= 10:
        return 100.0
    if nrv <= 25:
        return 85.0
    if nrv <= 50:
        return 65.0
    if nrv <= 100:
        return 35.0
    return max(10.0, 35.0 - (nrv - 100) * 0.8)


def score_nutrition(nutrition_data: NutritionData | None) -> NutritionScore:
    result = NutritionScore()

    if not nutrition_data or not nutrition_data.items:
        result.total = 70.0
        return result

    item_map: dict[str, NutritionItem] = {}
    for item in nutrition_data.items:
        name_lower = item.name.lower()
        if "能量" in item.name or "energy" in name_lower or "千焦" in item.name:
            item_map["energy"] = item
        elif "蛋白质" in item.name or "protein" in name_lower:
            item_map["protein"] = item
        elif "脂肪" in item.name or "total fat" in name_lower:
            item_map["fat"] = item
        elif "碳水" in item.name or "carbohydrate" in name_lower:
            item_map["carb"] = item
        elif "钠" in item.name or "sodium" in name_lower:
            item_map["sodium"] = item
        elif "糖" in item.name and "总" in item.name or "total sugar" in name_lower:
            item_map["sugar"] = item
        elif "膳食纤维" in item.name or "fiber" in name_lower:
            item_map["fiber"] = item

    protein_nrv = _parse_nrv(
        item_map.get(
            "protein", NutritionItem(name="", value="", unit="")
        ).daily_reference_percent
    )
    if protein_nrv > 0:
        if protein_nrv >= 20:
            result.protein_score = 90.0
        elif protein_nrv >= 10:
            result.protein_score = 100.0
        else:
            result.protein_score = 60.0 + protein_nrv * 3

    fat_nrv = _parse_nrv(
        item_map.get(
            "fat", NutritionItem(name="", value="", unit="")
        ).daily_reference_percent
    )
    if fat_nrv > 0:
        if fat_nrv <= 20:
            result.fat_score = 100.0
        elif fat_nrv <= 40:
            result.fat_score = 85.0
        elif fat_nrv <= 60:
            result.fat_score = 65.0
        else:
            result.fat_score = max(30.0, 65.0 - (fat_nrv - 60) * 1.5)

    carb_nrv = _parse_nrv(
        item_map.get(
            "carb", NutritionItem(name="", value="", unit="")
        ).daily_reference_percent
    )
    if carb_nrv > 0:
        if 40 <= carb_nrv <= 60:
            result.carb_score = 100.0
        elif 30 <= carb_nrv < 40:
            result.carb_score = 85.0
        elif 60 < carb_nrv <= 70:
            result.carb_score = 85.0
        else:
            result.carb_score = 70.0

    fiber_nrv = _parse_nrv(
        item_map.get(
            "fiber", NutritionItem(name="", value="", unit="")
        ).daily_reference_percent
    )
    if fiber_nrv >= 25:
        result.fiber_score = 100.0
    elif fiber_nrv >= 15:
        result.fiber_score = 90.0
    elif fiber_nrv >= 10:
        result.fiber_score = 80.0
    else:
        result.fiber_score = 70.0

    result.total = (
        result.protein_score * 0.35
        + result.fat_score * 0.25
        + result.carb_score * 0.25
        + result.fiber_score * 0.15
    )

    return result


def score_sodium(nutrition_data: NutritionData | None) -> float:
    if not nutrition_data or not nutrition_data.items:
        return 70.0

    for item in nutrition_data.items:
        if "钠" in item.name.lower() or "sodium" in item.name.lower():
            nrv = _parse_nrv(item.daily_reference_percent)
            if nrv == 0:
                nrv = _estimate_nrv_from_amount(item, "sodium_mg")

            if nrv <= NRV_THRESHOLDS["sodium"]["low"]:
                return 100.0
            elif nrv <= NRV_THRESHOLDS["sodium"]["medium"]:
                return 85.0
            elif nrv <= NRV_THRESHOLDS["sodium"]["high"]:
                return 65.0
            elif nrv <= NRV_THRESHOLDS["sodium"]["very_high"]:
                return 40.0
            else:
                return max(
                    10.0, 40.0 - (nrv - NRV_THRESHOLDS["sodium"]["very_high"]) * 2
                )

    return 80.0


def score_sugar(nutrition_data: NutritionData | None) -> float:
    if not nutrition_data or not nutrition_data.items:
        return 70.0

    for item in nutrition_data.items:
        name_lower = item.name.lower()
        if "糖" in item.name or "sugar" in name_lower:
            nrv = _parse_nrv(item.daily_reference_percent)
            if nrv == 0:
                nrv = _estimate_nrv_from_amount(item, "sugar_g")

            return _score_limit_nrv(nrv)

    return 80.0


def _classify_additive(name: str) -> str:
    name_lower = name.lower()
    if any(k in name_lower for k in ["防腐", "preserv", "山梨", "苯甲", "亚硫酸"]):
        return "preservative"
    elif any(
        k in name_lower for k in ["色素", "color", "着色", "胭脂", "柠檬黄", "日落"]
    ):
        return "color"
    elif any(
        k in name_lower for k in ["甜味", "sweetener", "糖精", "阿斯巴", "三氯", "赤藓"]
    ):
        return "sweetener"
    elif any(k in name_lower for k in ["味精", "增味", "谷氨酸", "肌苷", "呈味核苷"]):
        return "flavor_enhancer"
    return "other"


def score_additives(ingredients: list[IngredientItem]) -> float:
    penalty = 0.0
    additive_count = 0

    for ing in ingredients:
        risk = ing.risk
        category = _classify_additive(ing.name)
        p = ADDITIVE_PENALTIES[category][risk]
        if p > 0:
            additive_count += 1
            penalty += p

    if additive_count == 0:
        return 100.0

    penalty = min(penalty, 35.0)
    return max(65.0, 100.0 - penalty)


def score_allergens(ingredients: list[IngredientItem]) -> float:
    allergen_keywords = [
        "麸质",
        "小麦",
        "面筋",
        "gluten",
        "乳",
        "牛奶",
        "乳制品",
        "奶酪",
        "黄油",
        "奶粉",
        "大豆",
        "soy",
        "鸡蛋",
        "蛋",
        "花生",
        "peanut",
        "坚果",
        "杏仁",
        "核桃",
        "腰果",
        "pecan",
        "芝麻",
        "sesame",
        "甲壳",
        "虾",
        "蟹",
        "贝类",
        "鱼",
        "fish",
    ]

    allergen_count = 0
    for ing in ingredients:
        name_lower = ing.name.lower()
        for allergen in allergen_keywords:
            if allergen.lower() in name_lower:
                allergen_count += 1
                break

    penalty = ALLERGEN_PENALTIES.get(min(allergen_count, 4), 20)
    return max(60.0, 100.0 - penalty)


def calculate_health_score(
    nutrition_data: NutritionData | None,
    ingredients: list[IngredientItem],
    rag_results: RAGResults | None = None,
) -> tuple[int, ComponentScores]:
    """根据规则计算健康分。"""
    nutrition_score = score_nutrition(nutrition_data)
    sodium_score = score_sodium(nutrition_data)
    sugar_score = score_sugar(nutrition_data)
    additive_score = score_additives(ingredients)
    allergen_score = score_allergens(ingredients)

    component = ComponentScores(
        nutrition=nutrition_score,
        sodium=sodium_score,
        sugar=sugar_score,
        additives=additive_score,
        allergens=allergen_score,
    )

    final_score = (
        nutrition_score.total * 0.25
        + sodium_score * 0.25
        + additive_score * 0.20
        + allergen_score * 0.15
        + sugar_score * 0.15
    )

    # 糖或钠明显超标时限制总分，避免其它维度把高风险食品拉成高分。
    if sugar_score <= 30:
        final_score = min(final_score, 79.0)
    if sodium_score <= 40:
        final_score = min(final_score, 75.0)

    final_score = max(0.0, min(100.0, final_score))

    return int(round(final_score)), component


def format_score_breakdown(component: ComponentScores) -> str:
    """把数据整理成展示或输出需要的格式。"""
    lines = [
        "【评分明细】",
        f"  营养均衡: {component.nutrition.total:.1f}/100",
        f"    - 蛋白质: {component.nutrition.protein_score:.1f}",
        f"    - 脂肪: {component.nutrition.fat_score:.1f}",
        f"    - 碳水: {component.nutrition.carb_score:.1f}",
        f"    - 纤维: {component.nutrition.fiber_score:.1f}",
        f"  钠含量: {component.sodium:.1f}/100",
        f"  糖分: {component.sugar:.1f}/100",
        f"  添加剂: {component.additives:.1f}/100",
        f"  过敏原: {component.allergens:.1f}/100",
    ]
    return "\n".join(lines)
