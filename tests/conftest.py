import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def transcript():
    return json.loads((FIXTURES / "sample_transcript.json").read_text(encoding="utf-8"))


@pytest.fixture
def checklist():
    return json.loads((ROOT / "checklist.example.json").read_text(encoding="utf-8"))
