"""Обезличивание транскрипта перед отправкой модели.

Два слоя:
- шаблоны: телефоны, почта, номера карт, ссылки, паспортные серии;
- известные имена: имя клиента, менеджера, название компании заменяются
  плейсхолдерами с учётом русских падежей (по основе слова).

Модели уходит текст без персональных данных, в отчёте плейсхолдеры остаются.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.I)),
    ("[ССЫЛКА]", re.compile(r"https?://\S+|www\.\S+", re.I)),
    ("[КАРТА]", re.compile(r"\b(?:\d[ -]?){16}\b")),
    ("[ТЕЛЕФОН]", re.compile(r"(?<!\d)(?:\+7|8|7)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")),
    ("[ПАСПОРТ]", re.compile(r"\b\d{4}\s?\d{6}\b")),
]


def mask_pii(text: str) -> str:
    for placeholder, pattern in PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


def _name_pattern(name: str) -> re.Pattern[str]:
    """Регулярка на имя с русскими окончаниями: «Иван» ловит «Ивана», «Ивану»."""
    name = name.strip()
    stem = name[:-1] if len(name) >= 4 else name
    return re.compile(rf"(?<!\w){re.escape(stem)}\w{{0,3}}(?!\w)", re.I)


def mask_names(text: str, names: dict[str, str]) -> str:
    """names: {«Иван»: «[КЛИЕНТ]», «Ромашка»: «[КОМПАНИЯ]»}. Длинные имена первыми."""
    for name, placeholder in sorted(names.items(), key=lambda kv: -len(kv[0])):
        if not name.strip():
            continue
        text = _name_pattern(name).sub(placeholder, text)
    return text


def anonymize_transcript(transcript: dict[str, Any], names: dict[str, str] | None = None) -> dict[str, Any]:
    """Возвращает копию транскрипта с обезличенными репликами."""
    names = names or {}
    out = dict(transcript)
    out["utterances"] = [
        {**u, "text": mask_names(mask_pii(u["text"]), names)} for u in transcript["utterances"]
    ]
    out["anonymized"] = True
    return out


def parse_names(spec: str | Iterable[str] | None) -> dict[str, str]:
    """«Иван=[КЛИЕНТ],Мария=[МЕНЕДЖЕР]» → словарь. Плейсхолдер без скобок обернём сами."""
    if not spec:
        return {}
    items = spec.split(",") if isinstance(spec, str) else list(spec)
    names: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        name, placeholder = item.split("=", 1)
        placeholder = placeholder.strip()
        if not placeholder.startswith("["):
            placeholder = f"[{placeholder}]"
        names[name.strip()] = placeholder
    return names
