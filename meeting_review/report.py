"""Отчёт по встрече: Markdown для человека, JSON для систем, строка CSV для сводки.

Опционально уведомление в Telegram (без сторонних библиотек).
"""

from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cost import sum_costs

STATUS = {"pass": "✅", "fail": "❌", "unclear": "❔"}


def score(review: dict[str, Any]) -> dict[str, int]:
    total = len(review.get("criteria", []))
    passed = sum(1 for c in review["criteria"] if c["status"] == "pass")
    failed = sum(1 for c in review["criteria"] if c["status"] == "fail")
    return {"passed": passed, "failed": failed, "unclear": total - passed - failed, "total": total}


def to_markdown(result: Any, metrics: dict[str, Any], checklist: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    review = result.data
    titles = {c["id"]: c["title"] for c in checklist["criteria"]}
    sc = score(review)
    costs = [result.cost] + [e["cost"] for e in result.escalations]
    total_cost = sum_costs(costs)

    lines = [f"# Разбор встречи · {meta.get('source', '')}".rstrip(" ·"), ""]
    lines.append(f"**Итог:** {sc['passed']} из {sc['total']} критериев выполнено, "
                 f"{sc['failed']} нарушено, {sc['unclear']} без подтверждения. "
                 f"Цель встречи {'достигнута' if review.get('goal_achieved') else 'не достигнута'}.")
    lines.append("")
    lines.append(review.get("summary", ""))
    lines.append("")
    lines.append("## Чек-лист")
    lines.append("")
    lines.append("| Критерий | Статус | Время | Цитата | Комментарий |")
    lines.append("|---|---|---|---|---|")
    for c in review["criteria"]:
        quote = (c.get("quote") or "").replace("|", "¦").replace("\n", " ")
        comment = (c.get("comment") or "").replace("|", "¦").replace("\n", " ")
        if c.get("decided_by"):
            comment += f" (решено моделью {c['decided_by']})"
        lines.append(f"| {titles.get(c['id'], c['id'])} | {STATUS.get(c['status'], c['status'])} | {c.get('time', '')} | {quote} | {comment} |")
    lines.append("")

    if review.get("client_objections"):
        lines.append("## Возражения клиента")
        lines.extend(f"- {o}" for o in review["client_objections"])
        lines.append("")
    if review.get("risks"):
        lines.append("## Риски для сделки")
        lines.extend(f"- {r}" for r in review["risks"])
        lines.append("")
    lines.append("## Следующий шаг")
    lines.append(review.get("next_step") or "не зафиксирован")
    lines.append("")

    lines.append("## Метрики (посчитаны кодом)")
    share = metrics["talk_share"]
    lines.append(f"- Длительность: {int(metrics['duration_sec'] // 60)} мин")
    lines.append(f"- Доля речи: менеджер {int(share.get('manager', 0) * 100)} %, клиент {int(share.get('client', 0) * 100)} %")
    lines.append(f"- Вопросов: менеджер {metrics['questions'].get('manager', 0)}, клиент {metrics['questions'].get('client', 0)}")
    lines.append(f"- Самый длинный монолог менеджера: {metrics['longest_manager_monologue']['seconds']} с")
    for r in metrics.get("required_phrases", []):
        lines.append(f"- {r['label']}: {'есть' if r['found'] else 'нет'}")
    for f in metrics.get("forbidden_phrases", []):
        lines.append(f"- Запрещённое: {f['label']} ({', '.join(f['hits'])})")
    lines.append("")

    lines.append("## Стоимость разбора")
    lines.append(f"- Модель: {result.model}, токены: вход {result.cost['tokens']['input']}, "
                 f"выход {result.cost['tokens']['output']}, из кэша {result.cost['tokens']['cache_read']}")
    for e in result.escalations:
        lines.append(f"- Второе мнение: {e['model']} по критериям {', '.join(e['criteria'])}, {e['cost']['rub']} ₽")
    lines.append(f"- Итого: {total_cost['usd']} $ ≈ {total_cost['rub']} ₽ (курс {result.cost['usd_rub']})")
    if review.get("quotes_downgraded"):
        lines.append(f"- Критериев понижено из-за ненайденных цитат: {review['quotes_downgraded']}")
    lines.append("")
    return "\n".join(lines)


def to_json(result: Any, metrics: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    payload = {
        "meta": {**(meta or {}), "generated_at": datetime.now(timezone.utc).isoformat()},
        "model": result.model,
        "score": score(result.data),
        "review": result.data,
        "metrics": metrics,
        "cost": result.cost,
        "escalations": result.escalations,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def append_csv(path: str | Path, result: Any, metrics: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
    """Одна строка на встречу: сводка для таблицы руководителя."""
    meta = meta or {}
    sc = score(result.data)
    total = sum_costs([result.cost] + [e["cost"] for e in result.escalations])
    row = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": meta.get("source", ""),
        "manager": meta.get("manager", ""),
        "passed": sc["passed"], "failed": sc["failed"], "unclear": sc["unclear"], "total": sc["total"],
        "goal_achieved": int(bool(result.data.get("goal_achieved"))),
        "manager_share": metrics["talk_share"].get("manager", 0),
        "model": result.model,
        "cost_rub": total["rub"],
        "next_step": result.data.get("next_step", ""),
    }
    path = Path(path)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)


def telegram_summary(result: Any, meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    sc = score(result.data)
    fails = [c for c in result.data["criteria"] if c["status"] == "fail"]
    text = [f"Разбор: {meta.get('source', '')}", f"{sc['passed']}/{sc['total']} выполнено, {sc['failed']} нарушено, {sc['unclear']} без подтверждения"]
    if fails:
        text.append("Нарушено: " + ", ".join(c["id"] for c in fails))
    text.append(f"Стоимость: {result.cost['rub']} ₽")
    return "\n".join(text)


def notify_telegram(token: str, chat_id: str, text: str) -> None:
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
