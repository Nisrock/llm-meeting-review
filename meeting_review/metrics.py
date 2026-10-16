"""Слой «код»: всё, что можно посчитать без модели.

Доля речи, количество вопросов, самый длинный монолог менеджера, обязательные
и запрещённые формулировки из чек-листа. Эти цифры модель не трогает: чем
больше объём, тем сильнее хочется верить цифрам, поэтому их не должна
выдумывать модель.
"""

from __future__ import annotations

import re
from typing import Any

from .transcribe import role_of

WORD = re.compile(r"\w+", re.U)
QUESTION = re.compile(r"\?")


def _words(text: str) -> int:
    return len(WORD.findall(text))


def count_patterns(text: str, patterns: list[str]) -> list[str]:
    """Возвращает найденные фрагменты по списку регулярок (без учёта регистра)."""
    hits = []
    for p in patterns:
        for m in re.finditer(p, text, re.I):
            hits.append(m.group(0))
    return hits


def compute_metrics(transcript: dict[str, Any], checklist: dict[str, Any] | None = None) -> dict[str, Any]:
    checklist = checklist or {}
    by_role = {"manager": {"words": 0, "questions": 0, "utterances": 0, "seconds": 0.0},
               "client": {"words": 0, "questions": 0, "utterances": 0, "seconds": 0.0}}
    longest_monologue = {"role": None, "seconds": 0.0, "start": 0.0}

    for u in transcript["utterances"]:
        role = role_of(transcript, u)
        bucket = by_role.setdefault(role, {"words": 0, "questions": 0, "utterances": 0, "seconds": 0.0})
        bucket["words"] += _words(u["text"])
        bucket["questions"] += len(QUESTION.findall(u["text"]))
        bucket["utterances"] += 1
        length = max(0.0, float(u["end"]) - float(u["start"]))
        bucket["seconds"] += length
        if role == "manager" and length > longest_monologue["seconds"]:
            longest_monologue = {"role": role, "seconds": round(length, 1), "start": u["start"]}

    total_words = sum(b["words"] for b in by_role.values()) or 1
    talk_share = {role: round(b["words"] / total_words, 2) for role, b in by_role.items()}

    manager_text = "\n".join(u["text"] for u in transcript["utterances"] if role_of(transcript, u) == "manager")

    required = []
    for item in checklist.get("required_phrases", []):
        hits = count_patterns(manager_text, item.get("patterns", []))
        required.append({"id": item["id"], "label": item.get("label", item["id"]), "found": bool(hits), "hits": hits[:5]})

    forbidden = []
    for item in checklist.get("forbidden_phrases", []):
        hits = count_patterns(manager_text, item.get("patterns", []))
        if hits:
            forbidden.append({"id": item["id"], "label": item.get("label", item["id"]), "hits": hits[:5]})

    return {
        "duration_sec": round(float(transcript.get("duration", 0.0)), 1),
        "talk_share": talk_share,
        "questions": {role: b["questions"] for role, b in by_role.items()},
        "words": {role: b["words"] for role, b in by_role.items()},
        "longest_manager_monologue": longest_monologue,
        "required_phrases": required,
        "forbidden_phrases": forbidden,
    }


def metrics_as_text(metrics: dict[str, Any]) -> str:
    """Короткая сводка метрик для промпта и отчёта."""
    share = metrics["talk_share"]
    lines = [
        f"Длительность: {int(metrics['duration_sec'] // 60)} мин.",
        f"Доля речи: менеджер {int(share.get('manager', 0) * 100)} %, клиент {int(share.get('client', 0) * 100)} %.",
        f"Вопросов: менеджер {metrics['questions'].get('manager', 0)}, клиент {metrics['questions'].get('client', 0)}.",
        f"Самый длинный монолог менеджера: {metrics['longest_manager_monologue']['seconds']} с.",
    ]
    req = metrics.get("required_phrases", [])
    if req:
        missing = [r["label"] for r in req if not r["found"]]
        lines.append("Обязательные формулировки не найдены: " + (", ".join(missing) if missing else "все на месте") + ".")
    forb = metrics.get("forbidden_phrases", [])
    if forb:
        lines.append("Запрещённые формулировки: " + "; ".join(f"{f['label']} ({', '.join(f['hits'])})" for f in forb) + ".")
    return "\n".join(lines)
