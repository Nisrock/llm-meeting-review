"""Командная строка.

    meeting-review transcribe meeting.mp3 --out out/meeting.json
    meeting-review metrics out/meeting.json --checklist checklist.json
    meeting-review review out/meeting.json --checklist checklist.json --out out/meeting.md
    meeting-review run meeting.mp3 --checklist checklist.json --out out/meeting.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .anonymize import anonymize_transcript, parse_names
from .metrics import compute_metrics, metrics_as_text
from .report import append_csv, notify_telegram, telegram_summary, to_json, to_markdown
from .review import DEFAULT_MODEL, review_transcript
from .transcribe import assign_roles, transcribe


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def add_review_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--checklist", required=True, help="JSON с критериями и формулировками")
    p.add_argument("--out", required=True, help="Путь к Markdown-отчёту; рядом ляжет .json")
    p.add_argument("--model", default=os.environ.get("REVIEW_MODEL", DEFAULT_MODEL))
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--second-opinion-model", default=os.environ.get("SECOND_OPINION_MODEL"),
                   help="Модель для спорных критериев, например claude-opus-5-5 поверх claude-sonnet-5-5")
    p.add_argument("--names", default="", help="Имена для обезличивания: «Иван=КЛИЕНТ,Мария=МЕНЕДЖЕР,Ромашка=КОМПАНИЯ»")
    p.add_argument("--manager", default="", help="Имя менеджера для сводной таблицы (в модель не уходит)")
    p.add_argument("--manager-speaker", type=int, default=None, help="Номер спикера менеджера, если эвристика ошиблась")
    p.add_argument("--csv", default="", help="Сводная таблица, по строке на встречу")
    p.add_argument("--telegram", action="store_true", help="Отправить сводку в Telegram (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")


def do_review(transcript: dict, args: argparse.Namespace) -> int:
    import anthropic

    checklist = load_json(args.checklist)
    if args.manager_speaker is not None:
        transcript["roles"] = assign_roles(transcript, manager_speaker=args.manager_speaker)
    clean = anonymize_transcript(transcript, parse_names(args.names))
    metrics = compute_metrics(clean, checklist)

    client = anthropic.Anthropic()
    result = review_transcript(client, clean, checklist, metrics, model=args.model,
                               effort=args.effort, second_opinion_model=args.second_opinion_model)

    meta = {"source": transcript.get("source", ""), "manager": args.manager}
    save(args.out, to_markdown(result, metrics, checklist, meta))
    save(str(Path(args.out).with_suffix(".json")), to_json(result, metrics, meta))
    if args.csv:
        append_csv(args.csv, result, metrics, meta)
    if args.telegram:
        notify_telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"], telegram_summary(result, meta))

    sc = result.data
    passed = sum(1 for c in sc["criteria"] if c["status"] == "pass")
    print(f"{args.out}: {passed}/{len(sc['criteria'])} выполнено, {result.cost['rub']} ₽, модель {result.model}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meeting-review", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("transcribe", help="аудио или ссылка → транскрипт JSON")
    p.add_argument("source")
    p.add_argument("--out", required=True)

    p = sub.add_parser("metrics", help="метрики слоя кода без обращения к модели")
    p.add_argument("transcript")
    p.add_argument("--checklist", default="")

    p = sub.add_parser("review", help="разбор готового транскрипта")
    p.add_argument("transcript")
    add_review_args(p)

    p = sub.add_parser("run", help="транскрибация и разбор одной командой")
    p.add_argument("source")
    add_review_args(p)
    p.add_argument("--transcript-out", default="", help="Куда сохранить транскрипт (по умолчанию рядом с отчётом)")

    args = parser.parse_args(argv)

    if args.cmd == "transcribe":
        transcript = transcribe(args.source)
        save(args.out, json.dumps(transcript, ensure_ascii=False, indent=2))
        print(f"{args.out}: {len(transcript['utterances'])} реплик, {int(transcript['duration'] // 60)} мин")
        return 0

    if args.cmd == "metrics":
        transcript = load_json(args.transcript)
        checklist = load_json(args.checklist) if args.checklist else {}
        print(metrics_as_text(compute_metrics(transcript, checklist)))
        return 0

    if args.cmd == "review":
        return do_review(load_json(args.transcript), args)

    if args.cmd == "run":
        transcript = transcribe(args.source)
        tpath = args.transcript_out or str(Path(args.out).with_suffix(".transcript.json"))
        save(tpath, json.dumps(transcript, ensure_ascii=False, indent=2))
        return do_review(transcript, args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
