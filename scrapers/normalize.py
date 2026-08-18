import re

_MONEY_RE = re.compile(r"-?\$?[\d,]+(?:\.\d+)?")
_NEGATIVE_MARKERS = ("-", "−", "(")


def parse_money(text: str) -> int | None:
    if text is None:
        return None
    text = text.strip()
    if not text or text in {"-", "—", "--", "n/a", "N/A", ""}:
        return None
    match = _MONEY_RE.search(text.replace(",", ""))
    if not match:
        return None
    negative = match.group().startswith("-") or any(text.startswith(m) for m in _NEGATIVE_MARKERS)
    raw = match.group().replace(",", "").replace("$", "").lstrip("-−")
    if "." in raw:
        value = int(round(float(raw)))
    else:
        value = int(raw)
    return -value if negative else value


def parse_int(text: str) -> int | None:
    if text is None:
        return None
    text = text.strip()
    if not text or text in {"-", "—", "n/a"}:
        return None
    try:
        return int(text.replace(",", ""))
    except ValueError:
        return None


def parse_float(text: str) -> float | None:
    if text is None:
        return None
    text = text.strip()
    if not text or text in {"-", "—", "n/a"}:
        return None
    text = text.replace(",", "").rstrip("%").strip()
    try:
        return float(text)
    except ValueError:
        return None
