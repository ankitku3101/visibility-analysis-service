import time

import pytest

from app.analysis.preprocess import find_mention, kasparro_cited, quote_in_text, strip_url_list
from app.analysis.service import kasparro_position, normalise_competitors

LIST = "\n\nCitations:\n[1] https://a.com/x\n[2] https://kasparro.com/\n"


def test_strip_url_list():
    assert strip_url_list("Body text." + LIST) == "Body text."
    assert strip_url_list("No list here.") == "No list here."


@pytest.mark.parametrize("text", [
    "Body.\n\nCitations:\n[1] https://a.com\nmore words after the list",  # list not at the end
    "Body.\n\n[1] https://a.com",                                       # no Citations: header
    "Citations: are useful.\n[1] see above",                            # not a URL list
])
def test_strip_url_list_leaves_other_text(text):
    assert strip_url_list(text) == text


def test_strip_url_list_is_fast_on_near_match():
    text = "x\n\nCitations:\n" + "".join(f"[{i}] https://x.com/{i}\n\n" for i in range(5000)) + " tail"
    started = time.perf_counter()
    assert strip_url_list(text) == text
    assert time.perf_counter() - started < 0.5


def test_find_mention_returns_the_sentence():
    text = "Intro line. Kasparro is not widely recognized yet. Profound is bigger."
    assert find_mention(text) == (True, "Kasparro is not widely recognized yet.")
    assert find_mention("Visit kasparro.com for details. Other text.") == (True, "Visit kasparro.com for details.")
    assert find_mention("Nothing about it.") == (False, None)
    found, sentence = find_mention("**Kasparro**\n- audits for brands")
    assert found and sentence in "**Kasparro**\n- audits for brands"


def test_quote_in_text_ignores_markdown_and_typography():
    answer = "**Kasparro** isn’t widely recognized — yet."
    assert quote_in_text("Kasparro isn't widely recognized - yet.", answer)
    assert quote_in_text("kasparro  ISN'T widely", answer)
    assert not quote_in_text("Kasparro is the best tool", answer)
    assert not quote_in_text("", answer) and not quote_in_text(None, answer)
    assert not quote_in_text("yet.", answer)  # too short to count as evidence


def test_kasparro_cited():
    assert kasparro_cited([{"domain": "kasparro.com", "url": "https://kasparro.com/"}])
    assert kasparro_cited([{"domain": None, "url": "https://blog.kasparro.com/post"}])
    assert not kasparro_cited([{"domain": "notkasparro.com", "url": "https://notkasparro.com/"}])
    assert not kasparro_cited([])


def test_normalise_competitors():
    raw = [" Profound ", "Otterly.AI", "otterly ai", "ChatGPT", "SEO", "Kasparro", "", "Peec AI", "New Tool"]
    assert normalise_competitors(raw) == ["Profound", "Otterly", "Peec AI", "New Tool"]


def test_kasparro_position():
    assert kasparro_position(["Profound", "Kasparro (D2C)", "Otterly"]) == 2
    assert kasparro_position(["Profound"]) is None
    assert kasparro_position(None) is None
