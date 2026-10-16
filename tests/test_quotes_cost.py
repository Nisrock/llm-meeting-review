import pytest

from meeting_review.cost import cost_from_usage, sum_costs
from meeting_review.quotes import locate, normalize, verify_quotes


def test_locate_exact_and_fuzzy(transcript):
    hit = locate("Сколько это стоит?", transcript)
    assert hit and hit["time"] == "07:00" and hit["role"] == "client"
    # цитата с другой пунктуацией и ё/е
    hit = locate("стоимость программы четыреста пятьдесят тысяч рублей за три месяца, можно разбить на три платежа", transcript)
    assert hit and hit["role"] == "manager"
    assert locate("мы дарим вам скидку", transcript) is None
    assert normalize("Ёлка, ёж!") == "елка еж"


def test_verify_quotes_downgrades_pass_without_quote(transcript):
    review = {"criteria": [
        {"id": "price", "status": "pass", "quote": "Стоимость программы четыреста пятьдесят тысяч", "comment": ""},
        {"id": "summary", "status": "pass", "quote": "", "comment": ""},
        {"id": "pain", "status": "pass", "quote": "этой фразы в транскрипте нет вообще", "comment": "ок"},
        {"id": "goal", "status": "fail", "quote": "", "comment": "цель не названа"},
    ]}
    out = verify_quotes(review, transcript)
    by_id = {c["id"]: c for c in out["criteria"]}
    assert by_id["price"]["status"] == "pass" and by_id["price"]["time"] == "07:10"
    assert by_id["summary"]["status"] == "unclear"
    assert by_id["pain"]["status"] == "unclear" and "не найдена" in by_id["pain"]["comment"]
    assert by_id["goal"]["status"] == "fail"  # fail без цитаты не трогаем
    assert out["quotes_downgraded"] == 2


def test_cost_from_usage_dict_and_cache():
    usage = {"input_tokens": 10_000, "output_tokens": 1_000, "cache_read_input_tokens": 5_000, "cache_creation_input_tokens": 2_000}
    c = cost_from_usage("claude-opus-5-5", usage, usd_rub=100)
    # 10k*4 + 1k*20 + 5k*0.2 + 2k*4*1.25 = 40000+20000+1000+10000 = 71000 / 1e6 = 0.071 $
    assert c["usd"] == pytest.approx(0.071)
    assert c["rub"] == pytest.approx(7.1)
    assert sum_costs([c, c])["rub"] == pytest.approx(14.2)


def test_cost_unknown_model():
    with pytest.raises(KeyError):
        cost_from_usage("gpt-x", {"input_tokens": 1})
