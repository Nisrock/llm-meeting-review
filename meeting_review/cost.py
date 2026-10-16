"""Стоимость каждого разбора из usage ответа API.

Цены за миллион токенов (USD), запись в кэш считается как 1,25 входа,
чтение из кэша по своей ставке. Курс рубля задаётся переменной USD_RUB.
"""

from __future__ import annotations

import os
from typing import Any

PRICES_USD_PER_M = {
    "claude-opus-5-5":   {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "claude-haiku-5-5":  {"input": 0.10, "output": 0.50,  "cache_read": 0.01},
}
CACHE_WRITE_MULTIPLIER = 1.25


def _get(usage: Any, name: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(name) or 0)
    return int(getattr(usage, name, 0) or 0)


def cost_from_usage(model: str, usage: Any, usd_rub: float | None = None) -> dict[str, Any]:
    prices = PRICES_USD_PER_M.get(model)
    if prices is None:
        raise KeyError(f"Нет цен для модели {model}; добавьте в PRICES_USD_PER_M")
    rate = usd_rub if usd_rub is not None else float(os.environ.get("USD_RUB", "90"))

    tokens = {
        "input": _get(usage, "input_tokens"),
        "output": _get(usage, "output_tokens"),
        "cache_read": _get(usage, "cache_read_input_tokens"),
        "cache_write": _get(usage, "cache_creation_input_tokens"),
    }
    usd = (
        tokens["input"] * prices["input"]
        + tokens["output"] * prices["output"]
        + tokens["cache_read"] * prices["cache_read"]
        + tokens["cache_write"] * prices["input"] * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
    return {"model": model, "tokens": tokens, "usd": round(usd, 4), "rub": round(usd * rate, 2), "usd_rub": rate}


def sum_costs(items: list[dict[str, Any]]) -> dict[str, float]:
    return {"usd": round(sum(i["usd"] for i in items), 4), "rub": round(sum(i["rub"] for i in items), 2)}
