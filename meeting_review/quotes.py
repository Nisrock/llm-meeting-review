"""Проверка цитат: каждый вывод модели обязан опираться на реплику из транскрипта.

Модель возвращает цитату текстом. Мы ищем её в репликах с нормализацией
(регистр, пунктуация, «ё»), ставим тайминг и говорящего. Если цитата не нашлась,
критерий из «выполнен» становится «неясно»: без доказательства вывода нет.
"""

from __future__ import annotations

import re
from typing import Any

from .transcribe import fmt_time, role_of

TOKEN = re.compile(r"\w+", re.U)


def normalize(text: str) -> str:
    return " ".join(t.lower().replace("ё", "е") for t in TOKEN.findall(text))


def locate(quote: str, transcript: dict[str, Any], min_tokens: int = 4) -> dict[str, Any] | None:
    """Ищет цитату в репликах. Сначала целиком, затем по первым словам."""
    q = normalize(quote)
    if not q:
        return None
    candidates = [q]
    tokens = q.split()
    if len(tokens) > min_tokens:
        candidates.append(" ".join(tokens[:min_tokens + 2]))
        candidates.append(" ".join(tokens[-(min_tokens + 2):]))
    for needle in candidates:
        for u in transcript["utterances"]:
            if needle in normalize(u["text"]):
                return {"start": u["start"], "time": fmt_time(u["start"]), "role": role_of(transcript, u)}
    return None


def verify_quotes(review: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    """Проставляет тайминги и понижает статус критериев без подтверждённой цитаты."""
    out = dict(review)
    criteria = []
    downgraded = 0
    for c in review.get("criteria", []):
        item = dict(c)
        quote = (item.get("quote") or "").strip()
        found = locate(quote, transcript) if quote else None
        item["quote_verified"] = bool(found)
        item["time"] = found["time"] if found else ""
        item["quote_role"] = found["role"] if found else ""
        if item.get("status") == "pass" and not found:
            item["status"] = "unclear"
            item["comment"] = (item.get("comment") or "").strip()
            item["comment"] = (item["comment"] + " " if item["comment"] else "") + "Цитата не найдена в транскрипте, вывод не засчитан."
            downgraded += 1
        criteria.append(item)
    out["criteria"] = criteria
    out["quotes_downgraded"] = downgraded
    return out
