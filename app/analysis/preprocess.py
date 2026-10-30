"""Pure text helpers used before and after the LLM step. No I/O."""
import re
from urllib.parse import urlparse

URL_LINE = re.compile(r"\[\d+\]\s+\S+")
MENTION = re.compile(r"\bkasparro", re.IGNORECASE)
SENTENCE_END = re.compile(r"[.!?](?=\s|$)|\n")

# Characters the LLM often rewrites when it copies a sentence. All quote marks become one character:
# inside JSON output the model often swaps "double" quotes for 'single' ones (seen in eval case c02).
PLAIN = str.maketrans({"‘": "'", "’": "'", "“": "'", "”": "'", '"': "'",
                       "–": "-", "—": "-", " ": " ", "*": None, "`": None})


def strip_url_list(text: str) -> str:
    """Remove the trailing 'Citations:' + '[n] https://...' block.

    Line by line from the end instead of one regex: a nested regex here backtracks
    exponentially on text that almost matches (tested: > 20 s for 10 entries)."""
    lines = text.split("\n")
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    first_url = end
    while first_url and URL_LINE.fullmatch(lines[first_url - 1].strip()):
        first_url -= 1
    header = first_url - 1
    if first_url == end or header < 0 or lines[header].strip() != "Citations:":
        return text
    return "\n".join(lines[:header]).rstrip()


def find_mention(text: str) -> tuple[bool, str | None]:
    """Is Kasparro named? If so, return the sentence around the first mention (a substring of `text`)."""
    sentence = sentence_with(text, MENTION)
    return sentence is not None, sentence


def sentence_with(text: str, pattern: re.Pattern) -> str | None:
    """The sentence around the first match of `pattern` (a substring of `text`), or None."""
    match = pattern.search(text)
    if not match:
        return None
    start = 0
    for m in SENTENCE_END.finditer(text, 0, match.start()):
        start = m.end()
    after = SENTENCE_END.search(text, match.end())
    end = after.end() if after and after.group() != "\n" else (after.start() if after else len(text))
    return text[start:end].strip()


LINK = re.compile(r"\[([^\]\n]*)\]\([^)\s]*\)")
BARE_URL = re.compile(r"https?://\S+")
DOMAIN_LIKE = re.compile(r"(www\.)?[\w-]+(\.[\w-]+)*\.(com|org|net|io|ai|co|in|app|dev)\S*", re.IGNORECASE)


def prose_only(text: str) -> str:
    """The answer without URLs and without link labels that are just domains ('[genezio.com](...)').
    A real link label such as '[Profound](...)' is kept."""
    text = LINK.sub(lambda m: "" if DOMAIN_LIKE.fullmatch(m.group(1).strip()) else m.group(1), text)
    return BARE_URL.sub("", text)


def named_in_prose(name: str, prose: str) -> bool:
    """Is a competitor really named in the prose (not only cited as a source)?
    Matches the full name, or its first word when that word is distinctive (4+ characters)."""
    n, p = normalise(name), normalise(prose)
    if not n:
        return False
    if n in p:
        return True
    first = n.split()[0]
    return len(first) >= 4 and re.search(rf"\b{re.escape(first)}", p) is not None


def normalise(text: str) -> str:
    return " ".join(text.translate(PLAIN).lower().split())


def quote_in_text(quote: str | None, text: str) -> bool:
    """Is the quote really in the text? Ignores whitespace, case, markdown * and `, curly quotes and dashes."""
    if not quote or not quote.strip():
        return False
    q = normalise(quote)
    return len(q) >= 8 and q in normalise(text)


def kasparro_cited(citations: list[dict]) -> bool:
    for c in citations:
        host = (c.get("domain") or urlparse(c.get("url") or "").hostname or "").lower()
        if host == "kasparro.com" or host.endswith(".kasparro.com"):
            return True
    return False
