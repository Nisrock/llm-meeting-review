from meeting_review.metrics import compute_metrics, metrics_as_text
from meeting_review.transcribe import assign_roles, from_deepgram, to_text


def test_talk_share_and_questions(transcript, checklist):
    m = compute_metrics(transcript, checklist)
    assert abs(m["talk_share"]["manager"] + m["talk_share"]["client"] - 1.0) < 0.02
    assert m["questions"]["manager"] >= 5
    assert m["longest_manager_monologue"]["seconds"] > 100  # презентация на 180 с
    assert m["duration_sec"] == 1520.0


def test_required_and_forbidden_phrases(transcript, checklist):
    m = compute_metrics(transcript, checklist)
    by_id = {r["id"]: r for r in m["required_phrases"]}
    assert by_id["time_check"]["found"] is True
    assert by_id["next_step_ask"]["found"] is True
    assert m["forbidden_phrases"] == []


def test_forbidden_phrase_detected(transcript, checklist):
    transcript["utterances"][12]["text"] += " Могу сделать скидку прямо сейчас."
    m = compute_metrics(transcript, checklist)
    assert [f["id"] for f in m["forbidden_phrases"]] == ["discount_first"]
    assert "Запрещённые" in metrics_as_text(m)


def test_roles_heuristic_and_override():
    t = {"utterances": [{"speaker": 1, "start": 0, "end": 1, "text": "а"}, {"speaker": 0, "start": 1, "end": 2, "text": "б"}]}
    assert assign_roles(t) == {"0": "client", "1": "manager"}
    assert assign_roles(t, manager_speaker=0) == {"0": "manager", "1": "client"}


def test_from_deepgram_shape():
    payload = {"metadata": {"duration": 61.2}, "results": {"utterances": [
        {"speaker": 0, "start": 0.1, "end": 3.0, "transcript": "Здравствуйте"},
        {"speaker": 1, "start": 3.2, "end": 5.0, "transcript": "  "},
        {"speaker": 1, "start": 5.2, "end": 7.0, "transcript": "Добрый день"},
    ]}}
    t = from_deepgram(payload, source="x.mp3")
    assert t["duration"] == 61.2 and len(t["utterances"]) == 2
    assert t["roles"] == {"0": "manager", "1": "client"}
    assert to_text(t).splitlines()[0] == "[00:00] МЕНЕДЖЕР: Здравствуйте"
