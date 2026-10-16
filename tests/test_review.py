"""Разбор с подменённым клиентом API: проверяем промпт, схему, проверку цитат и эскалацию."""

import json
from types import SimpleNamespace

from meeting_review.metrics import compute_metrics
from meeting_review.report import append_csv, score, to_json, to_markdown
from meeting_review.review import build_schema, review_transcript


class FakeMessages:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.answers.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=4000, output_tokens=600, cache_read_input_tokens=1000, cache_creation_input_tokens=0),
        )


def fake_client(*answers):
    msgs = FakeMessages(answers)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def answer(checklist, overrides=None):
    overrides = overrides or {}
    criteria = []
    for c in checklist["criteria"]:
        item = {"id": c["id"], "status": "unclear", "quote": "", "comment": ""}
        item.update(overrides.get(c["id"], {}))
        criteria.append(item)
    return {"summary": "Встреча прошла по плану.", "goal_achieved": True, "criteria": criteria,
            "client_objections": ["дорого"], "risks": [], "next_step": "четверг 11:00 с партнёром"}


def test_schema_enumerates_checklist_ids(checklist):
    schema = build_schema(checklist)
    ids = schema["properties"]["criteria"]["items"]["properties"]["id"]["enum"]
    assert ids == [c["id"] for c in checklist["criteria"]]


def test_review_builds_prompt_and_verifies_quotes(transcript, checklist):
    client, msgs = fake_client(answer(checklist, {
        "price": {"status": "pass", "quote": "Стоимость программы четыреста пятьдесят тысяч рублей"},
        "greeting": {"status": "pass", "quote": "такой реплики нет"},
    }))
    metrics = compute_metrics(transcript, checklist)
    result = review_transcript(client, transcript, checklist, metrics, model="claude-opus-5-5")

    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert "[00:00] МЕНЕДЖЕР" in call["messages"][0]["content"]
    assert "Доля речи" in call["messages"][0]["content"]

    by_id = {c["id"]: c for c in result.data["criteria"]}
    assert by_id["price"]["status"] == "pass" and by_id["price"]["time"] == "07:10"
    assert by_id["greeting"]["status"] == "unclear"
    assert result.cost["usd"] > 0 and result.escalations == []


def test_second_opinion_only_for_unclear(transcript, checklist):
    first = answer(checklist, {"price": {"status": "pass", "quote": "Стоимость программы четыреста пятьдесят тысяч"}})
    second = answer(checklist, {
        "price": {"status": "fail", "quote": "Стоимость программы", "comment": "не должно перезаписать"},
        "greeting": {"status": "pass", "quote": "Меня зовут Мария, я из компании Ромашка"},
    })
    client, msgs = fake_client(first, second)
    metrics = compute_metrics(transcript, checklist)
    result = review_transcript(client, transcript, checklist, metrics,
                               model="claude-sonnet-5-5", second_opinion_model="claude-opus-5-5")
    assert len(msgs.calls) == 2 and msgs.calls[1]["model"] == "claude-opus-5-5"
    by_id = {c["id"]: c for c in result.data["criteria"]}
    assert by_id["price"]["status"] == "pass"            # уверенный вердикт первой модели сохранён
    assert by_id["greeting"]["status"] == "pass" and by_id["greeting"]["decided_by"] == "claude-opus-5-5"
    assert result.escalations[0]["model"] == "claude-opus-5-5"
    assert "greeting" in result.escalations[0]["criteria"] and "price" not in result.escalations[0]["criteria"]


def test_report_outputs(tmp_path, transcript, checklist):
    client, _ = fake_client(answer(checklist, {"price": {"status": "pass", "quote": "Стоимость программы четыреста пятьдесят тысяч"}}))
    metrics = compute_metrics(transcript, checklist)
    result = review_transcript(client, transcript, checklist, metrics)
    md = to_markdown(result, metrics, checklist, {"source": "sample.mp3"})
    assert "| Цена названа | ✅ | 07:10 |" in md
    assert "Итого:" in md and "₽" in md
    data = json.loads(to_json(result, metrics, {"source": "sample.mp3"}))
    assert data["score"] == score(result.data) and data["score"]["passed"] == 1
    csv_path = tmp_path / "summary.csv"
    append_csv(csv_path, result, metrics, {"source": "sample.mp3", "manager": "M1"})
    append_csv(csv_path, result, metrics, {"source": "sample2.mp3", "manager": "M1"})
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("date,source,manager,passed") and len(lines) == 3
