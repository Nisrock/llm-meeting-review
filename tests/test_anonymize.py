from meeting_review.anonymize import anonymize_transcript, mask_names, mask_pii, parse_names


def test_mask_phone_email_card():
    text = "Звоните +7 916 123-45-67 или 89161234567, почта ivan@mebel-test.ru, карта 4276 1234 5678 9012"
    out = mask_pii(text)
    assert "[ТЕЛЕФОН]" in out
    assert "916" not in out
    assert "[EMAIL]" in out and "mebel-test" not in out
    assert "[КАРТА]" in out and "9012" not in out


def test_mask_names_with_cases():
    names = {"Иван": "[КЛИЕНТ]", "Мария": "[МЕНЕДЖЕР]", "Ромашка": "[КОМПАНИЯ]"}
    text = "Иван сказал Марии, что Ивану нравится компания Ромашка и её Ромашки."
    out = mask_names(text, names)
    assert "Иван" not in out and "Мари" not in out and "Ромашк" not in out
    assert out.count("[КЛИЕНТ]") == 2
    assert out.count("[КОМПАНИЯ]") == 2


def test_mask_names_does_not_touch_other_words():
    out = mask_names("Иванов день и диван", {"Иван": "[КЛИЕНТ]"})
    assert "диван" in out


def test_parse_names():
    assert parse_names("Иван=КЛИЕНТ, Мария=[МЕНЕДЖЕР]") == {"Иван": "[КЛИЕНТ]", "Мария": "[МЕНЕДЖЕР]"}
    assert parse_names("") == {}


def test_anonymize_transcript_keeps_structure(transcript):
    clean = anonymize_transcript(transcript, {"Иван": "[КЛИЕНТ]", "Мария": "[МЕНЕДЖЕР]"})
    assert len(clean["utterances"]) == len(transcript["utterances"])
    joined = " ".join(u["text"] for u in clean["utterances"])
    assert "ivan@" not in joined and "+7 916" not in joined and "Иван" not in joined
    assert clean["anonymized"] is True
    assert transcript["utterances"][0]["text"].startswith("Добрый день, Иван")  # исходник не изменён
