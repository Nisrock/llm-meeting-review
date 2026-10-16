"""Слой «модель»: разбор встречи по чек-листу со structured output.

Правила, зашитые в промпт и схему:
- судить только по транскрипту;
- на каждый критерий дословная цитата, иначе статус «unclear» и пустая цитата;
- цифры из слоя кода модель получает как контекст, но не пересчитывает.

Стабильная часть промпта (правила + чек-лист) кэшируется, транскрипт идёт после
точки кэша. Стоимость считается из usage каждого ответа.

Эскалация: если после проверки цитат остались «unclear», можно прогнать разбор
второй, более сильной моделью и взять её вердикты только по спорным критериям.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .cost import cost_from_usage
from .metrics import metrics_as_text
from .quotes import verify_quotes
from .transcribe import to_text

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """Ты проверяющий отдела контроля качества продаж. Тебе дают транскрипт встречи менеджера с клиентом, чек-лист и метрики, посчитанные кодом.

Правила:
1. Судишь только по транскрипту. Не додумывай, что «наверняка было сказано».
2. На каждый критерий приводишь дословную цитату из транскрипта (одну реплику или её часть, без пересказа). Если подтверждающей реплики нет, ставь status "unclear" и оставляй quote пустой строкой. Статус "pass" без цитаты запрещён.
3. "fail" ставь только когда транскрипт прямо показывает, что критерий нарушен (например, цена так и не названа до конца встречи), и тоже приводи цитату, которая это показывает.
4. Метрики из слоя кода не пересчитывай и не оспаривай, используй как контекст.
5. Комментарии короткие, по делу, на русском. Без оценочных прилагательных без фактов.
6. В summary три-четыре предложения: что произошло на встрече и чем закончилась.
7. В risks только то, что может сорвать сделку, с опорой на транскрипт.
"""


def build_schema(checklist: dict[str, Any]) -> dict[str, Any]:
    ids = [c["id"] for c in checklist["criteria"]]
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "goal_achieved": {"type": "boolean"},
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": ids},
                        "status": {"type": "string", "enum": ["pass", "fail", "unclear"]},
                        "quote": {"type": "string"},
                        "comment": {"type": "string"},
                    },
                    "required": ["id", "status", "quote", "comment"],
                    "additionalProperties": False,
                },
            },
            "client_objections": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "next_step": {"type": "string"},
        },
        "required": ["summary", "goal_achieved", "criteria", "client_objections", "risks", "next_step"],
        "additionalProperties": False,
    }


def checklist_text(checklist: dict[str, Any]) -> str:
    lines = []
    if checklist.get("company_context"):
        lines.append("Контекст компании: " + checklist["company_context"])
    if checklist.get("meeting_goal"):
        lines.append("Цель встречи: " + checklist["meeting_goal"])
    lines.append("Чек-лист (id, название, что считается выполнением):")
    for c in checklist["criteria"]:
        lines.append(f"- {c['id']}: {c['title']}. {c.get('description', '')}".rstrip())
    return "\n".join(lines)


def build_messages(transcript: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Один user-ход: метрики, затем транскрипт."""
    body = (
        "Метрики, посчитанные кодом:\n" + metrics_as_text(metrics) +
        "\n\nТранскрипт встречи:\n" + to_text(transcript) +
        "\n\nЗаполни разбор по схеме. Все критерии из чек-листа должны присутствовать ровно по одному разу."
    )
    return [{"role": "user", "content": body}]


@dataclass
class ReviewResult:
    data: dict[str, Any]
    model: str
    cost: dict[str, Any]
    stop_reason: str = "end_turn"
    escalations: list[dict[str, Any]] = field(default_factory=list)


def _extract_json(response: Any) -> dict[str, Any]:
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    return json.loads(text)


def call_model(client: Any, model: str, checklist: dict[str, Any], transcript: dict[str, Any],
               metrics: dict[str, Any], effort: str = "medium", max_tokens: int = 8000) -> tuple[dict[str, Any], Any]:
    """Один вызов API. Возвращает (данные, ответ). Правила и чек-лист в кэшируемом system."""
    response = client.beta.messages.create(
        model=model,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": checklist_text(checklist), "cache_control": {"type": "ephemeral"}},
        ],
        messages=build_messages(transcript, metrics),
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": build_schema(checklist)}},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Модель отказалась разбирать встречу: {getattr(response, 'stop_details', None)}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Ответ обрезан по max_tokens, увеличьте лимит")
    return _extract_json(response), response


def _complete_criteria(data: dict[str, Any], checklist: dict[str, Any]) -> dict[str, Any]:
    """Гарантирует по одному элементу на каждый критерий чек-листа."""
    by_id = {c["id"]: c for c in data.get("criteria", [])}
    data["criteria"] = [
        by_id.get(c["id"], {"id": c["id"], "status": "unclear", "quote": "", "comment": "Модель не вернула критерий."})
        for c in checklist["criteria"]
    ]
    return data


def review_transcript(client: Any, transcript: dict[str, Any], checklist: dict[str, Any], metrics: dict[str, Any],
                      model: str = DEFAULT_MODEL, effort: str = "medium",
                      second_opinion_model: str | None = None) -> ReviewResult:
    """Полный разбор: вызов модели → проверка цитат → при необходимости второе мнение."""
    data, response = call_model(client, model, checklist, transcript, metrics, effort=effort)
    data = verify_quotes(_complete_criteria(data, checklist), transcript)
    result = ReviewResult(data=data, model=model, cost=cost_from_usage(model, response.usage),
                          stop_reason=response.stop_reason)

    unclear = [c["id"] for c in data["criteria"] if c["status"] == "unclear"]
    if second_opinion_model and unclear:
        data2, response2 = call_model(client, second_opinion_model, checklist, transcript, metrics, effort="high")
        data2 = verify_quotes(_complete_criteria(data2, checklist), transcript)
        second = {c["id"]: c for c in data2["criteria"]}
        for c in result.data["criteria"]:
            if c["id"] in unclear and second[c["id"]]["status"] != "unclear":
                c.update(second[c["id"]])
                c["decided_by"] = second_opinion_model
        result.escalations.append({
            "model": second_opinion_model,
            "criteria": unclear,
            "cost": cost_from_usage(second_opinion_model, response2.usage),
        })
    return result
