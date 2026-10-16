from pathlib import Path

from meeting_review.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_metrics_command(capsys):
    code = main(["metrics", str(ROOT / "tests/fixtures/sample_transcript.json"), "--checklist", str(ROOT / "checklist.example.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "Доля речи" in out and "все на месте" in out
