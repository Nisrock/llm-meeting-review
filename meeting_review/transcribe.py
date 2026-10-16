"""Транскрибация через Deepgram с разметкой говорящих.

На выходе единый формат транскрипта, который понимают остальные модули:

    {
      "source": "meeting.mp3",
      "duration": 2710.4,
      "utterances": [
        {"speaker": 0, "start": 1.2, "end": 5.4, "text": "Добрый день..."},
        ...
      ],
      "roles": {"0": "manager", "1": "client"}
    }

Роли назначаются эвристикой: менеджер открывает встречу, поэтому говорящий
первой реплики считается менеджером. Эвристику можно переопределить параметром.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEFAULT_PARAMS = {
    "model": "nova-3",
    "language": "ru",
    "diarize": "true",
    "utterances": "true",
    "punctuate": "true",
    "smart_format": "true",
}


def transcribe(source: str, api_key: str | None = None, timeout: int = 600) -> dict[str, Any]:
    """Отправляет файл или ссылку в Deepgram и возвращает транскрипт в нашем формате."""
    key = api_key or os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("Нужен DEEPGRAM_API_KEY")
    headers = {"Authorization": f"Token {key}"}

    if source.startswith("http://") or source.startswith("https://"):
        resp = requests.post(
            DEEPGRAM_URL, params=DEFAULT_PARAMS, headers=headers,
            json={"url": source}, timeout=timeout,
        )
    else:
        path = Path(source)
        headers["Content-Type"] = "application/octet-stream"
        with path.open("rb") as fh:
            resp = requests.post(
                DEEPGRAM_URL, params=DEFAULT_PARAMS, headers=headers,
                data=fh, timeout=timeout,
            )
    resp.raise_for_status()
    return from_deepgram(resp.json(), source=source)


def from_deepgram(payload: dict[str, Any], source: str = "") -> dict[str, Any]:
    """Переводит ответ Deepgram в формат транскрипта."""
    results = payload.get("results", {})
    utterances = []
    for u in results.get("utterances", []):
        text = (u.get("transcript") or "").strip()
        if not text:
            continue
        utterances.append({
            "speaker": int(u.get("speaker", 0)),
            "start": round(float(u.get("start", 0.0)), 2),
            "end": round(float(u.get("end", 0.0)), 2),
            "text": text,
        })
    duration = float(payload.get("metadata", {}).get("duration", 0.0))
    if not duration and utterances:
        duration = utterances[-1]["end"]
    transcript = {"source": source, "duration": round(duration, 2), "utterances": utterances}
    transcript["roles"] = assign_roles(transcript)
    return transcript


def assign_roles(transcript: dict[str, Any], manager_speaker: int | None = None) -> dict[str, str]:
    """Назначает роли говорящим: один менеджер, остальные клиенты.

    По умолчанию менеджер тот, кто говорит первым. Если спикеров больше двух,
    все, кроме менеджера, считаются стороной клиента.
    """
    speakers = sorted({u["speaker"] for u in transcript["utterances"]})
    if not speakers:
        return {}
    if manager_speaker is None:
        manager_speaker = transcript["utterances"][0]["speaker"]
    return {str(s): ("manager" if s == manager_speaker else "client") for s in speakers}


def role_of(transcript: dict[str, Any], utterance: dict[str, Any]) -> str:
    return transcript.get("roles", {}).get(str(utterance["speaker"]), "client")


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def to_text(transcript: dict[str, Any]) -> str:
    """Транскрипт одной строкой на реплику: [мм:сс] РОЛЬ: текст."""
    labels = {"manager": "МЕНЕДЖЕР", "client": "КЛИЕНТ"}
    lines = []
    for u in transcript["utterances"]:
        role = labels.get(role_of(transcript, u), "КЛИЕНТ")
        lines.append(f"[{fmt_time(u['start'])}] {role}: {u['text']}")
    return "\n".join(lines)
