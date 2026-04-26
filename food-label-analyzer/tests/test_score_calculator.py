from __future__ import annotations

from app.schemas.analysis_data import IngredientItem, NutritionData
from app.services.score_calculator import calculate_health_score


def _nutrition(items: list[dict[str, str | None]]) -> NutritionData:
    return NutritionData.model_validate({"items": items, "parse_method": "ocr_text"})


def _ingredient(name: str = "芒果浓缩汁", risk: str = "safe") -> IngredientItem:
    return IngredientItem.model_validate(
        {
            "name": name,
            "risk": risk,
            "description": "常见食品配料，按正常食用量一般风险较低。",
            "function_category": None,
            "rules": [],
        }
    )


def test_high_sugar_amount_without_nrv_is_penalized() -> None:
    score, component = calculate_health_score(
        _nutrition(
            [
                {
                    "name": "蛋白质",
                    "value": "2.1",
                    "unit": "g",
                    "daily_reference_percent": "4%",
                },
                {
                    "name": "脂肪",
                    "value": "0",
                    "unit": "g",
                    "daily_reference_percent": "0%",
                },
                {
                    "name": "糖",
                    "value": "56.7",
                    "unit": "g",
                    "daily_reference_percent": None,
                },
                {
                    "name": "膳食纤维",
                    "value": "8.6",
                    "unit": "g",
                    "daily_reference_percent": "34%",
                },
                {
                    "name": "钠",
                    "value": "0",
                    "unit": "mg",
                    "daily_reference_percent": "0%",
                },
            ]
        ),
        [_ingredient()],
    )

    assert component.sugar <= 30
    assert score < 80


def test_zero_sodium_is_not_treated_as_missing_nrv() -> None:
    _, component = calculate_health_score(
        _nutrition(
            [
                {
                    "name": "钠",
                    "value": "0",
                    "unit": "mg",
                    "daily_reference_percent": "0%",
                },
            ]
        ),
        [_ingredient()],
    )

    assert component.sodium == 100.0


def test_nutrition_benefits_do_not_mask_severe_sugar_load() -> None:
    score, component = calculate_health_score(
        _nutrition(
            [
                {
                    "name": "蛋白质",
                    "value": "12",
                    "unit": "g",
                    "daily_reference_percent": "20%",
                },
                {
                    "name": "脂肪",
                    "value": "0",
                    "unit": "g",
                    "daily_reference_percent": "0%",
                },
                {
                    "name": "糖",
                    "value": "60",
                    "unit": "g",
                    "daily_reference_percent": None,
                },
                {
                    "name": "膳食纤维",
                    "value": "9",
                    "unit": "g",
                    "daily_reference_percent": "36%",
                },
                {
                    "name": "钠",
                    "value": "0",
                    "unit": "mg",
                    "daily_reference_percent": "0%",
                },
            ]
        ),
        [_ingredient()],
    )

    assert component.nutrition.total >= 85
    assert component.sugar <= 25
    assert score < 80
