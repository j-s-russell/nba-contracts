import re
import unicodedata

from scrapers import constants

SEARCH_ITEM_RE = re.compile(
    r'<a href="https://www\.spotrac\.com/redirect/player/(\d+)\?ref=search"[^>]*>(.*?)</a>',
    re.S,
)
NAME_RE = re.compile(r'fs-lg">([^<]+)</span>\s*\(([^)]*)\)')
BADGE_RE = re.compile(r'<span class="badge[^"]*"[^>]*>([^<]+)</span>')
IMG_RE = re.compile(r'images/thumb/([a-z]+)_')
NBA_POSITIONS = {
    "Point Guard", "Shooting Guard", "Small Forward", "Power Forward",
    "Center", "Guard", "Forward", "F-C", "C-F", "G-F", "F-G",
}
NON_NBA_POSITIONS = {
    "Safety", "Cornerback", "Wide Receiver", "Linebacker", "Quarterback",
    "Defensive End", "Defensive Tackle", "Running Back", "Tight End",
    "Offensive Lineman", "Kicker", "Punter", "Long Snapper", "Fullback",
    "Pitcher", "Catcher", "First Baseman", "Second Baseman", "Third Baseman",
    "Shortstop", "Outfielder", "Outfielders", "Designated Hitter",
    "Midfielder", "Defender", "Goalkeeper", "Goal Keeper", "Winger",
    "Utility", "Utility Player", "Relief Pitcher", "Starting Pitcher",
}


def result_sport(r: dict) -> str | None:
    if r["position"] in NBA_POSITIONS:
        return "nba"
    if r["position"] in NON_NBA_POSITIONS:
        return "other"
    if r["sport"] in ("nba", "wnba"):
        return r["sport"]
    if r["sport"] in ("nfl", "mlb", "nhl", "mls", "epl", "nwsl", "ten"):
        return "other"
    return None

TX_PAIR_RE = re.compile(
    r'<strong class="link">([^<]+)</strong>\s*<small class="d-block">(.*?)</small>',
    re.S,
)
DEAL_RE = re.compile(
    r"Signed\s+(?:a\s+)?(?:(\d+)[ -]?year)?[^$]*?\$+([\d.,]+)\s*(million|m|M|k)?"
    r"\s+(?:.{0,300}?)?with ([A-Za-z0-9 .']+?)\s+\(([A-Z]{3})\)",
    re.I,
)
CURRENT_CONTRACT_RE = re.compile(
    r"Signed a (\d+) ?year,? \$([\d,]+) contract with ([A-Za-z0-9 .']+?)"
    r"(?:, including \$([\d,]+) guaranteed,)? and\s+an average annual salary of \$([\d,]+)\.",
    re.I,
)
CONTRACT_YEARS_RE = re.compile(r'<span class="years">(\d{4})-\d{4}')
CONTRACT_BLOCK_RE = re.compile(
    r'<span class="logo"><img[^>]*?src="[^"]*?thumb/(?:nba_)?([a-z]{2,4})(?:_\d+)?\.png".*?'
    r'<span class="years">(\d{4})-\d{4}.*?'
    r'<div class="label">Contract Terms:</div>\s*<div class="value">(\d+) yr\(s\) / \$([\d,]+)</div>',
    re.I | re.S,
)

DEAL_TYPE_KEYWORDS = (
    ("maximum", "maximum"),
    ("rookie scale", "rookie-scale"),
    ("extension", "extension"),
    ("two-way", "two-way"),
    ("veteran minimum", "minimum"),
    ("minimum", "minimum"),
)


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace(".", "")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return s.strip()


def pos_families(bbr_pos: str) -> set[str]:
    p = (bbr_pos or "").upper()
    fam = set()
    if p in ("PG", "SG", "G", "G-F", "F-G"):
        fam.add("Guard")
    if p in ("SF", "PF", "F", "G-F", "F-G", "F-C", "C-F"):
        fam.add("Forward")
    if p in ("C", "C-F", "F-C"):
        fam.add("Center")
    return fam


def parse_search_results(html: str) -> list[dict]:
    results = []
    for m in SEARCH_ITEM_RE.finditer(html):
        spotrac_id = m.group(1)
        body = m.group(2)
        name_match = NAME_RE.search(body)
        badge = BADGE_RE.search(body)
        img = IMG_RE.search(body)
        if not name_match:
            continue
        results.append(
            {
                "spotrac_id": int(spotrac_id),
                "name": name_match.group(1).strip(),
                "team": name_match.group(2).strip(),
                "position": badge.group(1).strip() if badge else "",
                "sport": img.group(1) if img else "",
            }
        )
    return results


def match_search_results(results: list[dict], bbr_name: str, bbr_pos: str) -> dict | None:
    target = normalize_name(bbr_name)
    target_fams = pos_families(bbr_pos)
    target_tokens = target.split()
    target_first = target_tokens[0] if target_tokens else ""

    exact = []
    fuzzy = []
    for r in results:
        cand = normalize_name(r["name"])
        sport = result_sport(r)
        if not cand:
            continue
        if cand == target:
            if sport != "other":
                exact.append((r, 200))
            else:
                exact.append((r, 100))
        elif cand in target or target in cand:
            fuzzy.append((r, 50, cand))
        elif cand.split()[-1:] == target_tokens[-1:]:
            fuzzy.append((r, 20, cand))

    if exact:
        best = max(exact, key=lambda x: x[1])
        r, score = best
        r["confidence"] = "high" if score >= 200 else "medium"
        return {**r, "confidence": r["confidence"]}

    scored = []
    for r, base, cand in fuzzy:
        score = base
        cand_tokens = cand.split()
        if target_first and cand_tokens:
            cf = cand_tokens[0]
            if len(target_first) >= 2 and (
                cf.startswith(target_first) or target_first.startswith(cf)
            ):
                score += 25
        if target_fams:
            rfam = {w for w in ("Guard", "Forward", "Center") if w in r["position"]}
            if rfam & target_fams:
                score += 10
        if result_sport(r) == "nba":
            score += 5
        scored.append((r, score))
    if not scored:
        return None
    best = max(scored, key=lambda x: x[1])
    r, score = best
    confidence = "medium" if score >= 50 else "low"
    return {**r, "confidence": confidence}


def parse_deal_type(text: str) -> str:
    lowered = text.lower()
    for keyword, label in DEAL_TYPE_KEYWORDS:
        if keyword in lowered:
            return label
    return "standard"


def _parse_amount(value: str) -> float:
    s = value.replace(",", "")
    if s.startswith("."):
        s = s[1:]
    return float(s)


def _parse_deal_value(num: str, unit: str | None) -> float | None:
    try:
        if "," in num:
            return float(num.replace(",", "")) / 1e6
        if unit and unit.lower() == "k":
            return float(num) / 1000.0
        return float(num)
    except ValueError:
        return None


def parse_transactions(html: str, spotrac_id: int) -> list[dict]:
    deals = []
    seen = set()
    for date_match, text_match in TX_PAIR_RE.findall(html):
        date = date_match.strip()
        text = re.sub(r"<[^>]+>", "", text_match).strip()
        text = re.sub(r"\s+", " ", text)
        if not text.lower().startswith("signed"):
            continue
        key = (date, text)
        if key in seen:
            continue
        seen.add(key)
        deal = {"spotrac_id": spotrac_id, "date": date, "text": text}
        m = DEAL_RE.search(text)
        if m:
            deal["years"] = int(m.group(1)) if m.group(1) else None
            deal["total_value_m"] = _parse_deal_value(m.group(2), m.group(3))
            deal["deal_type"] = parse_deal_type(text)
            deal["team"] = constants.canonical_team(m.group(5))
        else:
            deal["years"] = None
            deal["total_value_m"] = None
            deal["deal_type"] = parse_deal_type(text)
            deal["team"] = ""
        deals.append(deal)
    return deals


EVENT_TX_RE = re.compile(
    r'<span class="logo"><img[^>]*?src="[^"]*?thumb/(?:nba_)?([a-z]{2,4})(?:_\d+)?\.png"',
    re.I,
)
EVENT_KIND_RULES = (
    ("qualifying offer", "qo"),
    ("restricted free agent", "fa_status"),
    ("unrestricted free agent", "fa_status"),
    ("offer sheet", "offer_sheet"),
    ("sign-and-trade", "sign_and_trade"),
    ("buyout", "buyout"),
    ("waived", "waive"),
    ("trade exception", "trade_exception"),
    ("traded to", "trade"),
    ("trade to", "trade"),
    ("signed", "sign"),
    ("drafted", "draft"),
    ("exercised", "option"),
    ("declined", "option"),
    ("declined to", "option"),
    ("renegotiated", "renegotiation"),
    ("waiver", "waive"),
    ("suspended", "suspend"),
    ("fined", "fine"),
    ("rest-of-season", "sign"),
    ("rest of season", "sign"),
    ("two-way", "sign"),
    ("extension", "sign"),
    ("option", "option"),
)


def _event_kind(text: str) -> str:
    lowered = text.lower()
    for keyword, kind in EVENT_KIND_RULES:
        if keyword in lowered:
            return kind
    return "other"


def parse_transaction_events(html: str, spotrac_id: int) -> list[dict]:
    events = []
    seen = set()
    for date_match, text_match in TX_PAIR_RE.findall(html):
        date = date_match.strip()
        text = re.sub(r"<[^>]+>", "", text_match).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        key = (date, text)
        if key in seen:
            continue
        seen.add(key)
        kind = _event_kind(text)
        if kind in ("suspend", "fine"):
            continue
        logo = EVENT_TX_RE.search(text_match)
        team = ""
        if logo:
            team = constants.TEAM_LOGO_MAP.get(logo.group(1), "")
        if not team:
            m = re.search(r"\bwith ([A-Za-z0-9 .']+?)\s+\(([A-Z]{3})\)", text)
            if m:
                team = constants.canonical_team(m.group(2))
        events.append(
            {
                "spotrac_id": spotrac_id,
                "date": date,
                "text": text,
                "kind": kind,
                "team": team,
            }
        )
    return events


def parse_current_contract(html: str) -> dict | None:
    m = CURRENT_CONTRACT_RE.search(html)
    if not m:
        return None
    ym = CONTRACT_YEARS_RE.search(html)
    return {
        "years": int(m.group(1)),
        "total_value": int(m.group(2).replace(",", "")),
        "team": m.group(3).strip().removeprefix("the ").removeprefix("The "),
        "guaranteed": int(m.group(4).replace(",", "")) if m.group(4) else None,
        "aav": int(m.group(5).replace(",", "")),
        "start_year": int(ym.group(1)) if ym else None,
        "deal_type": parse_deal_type(m.group(0)),
    }


SCHEMA_NAME_RE = re.compile(r'"@type"\s*:\s*"Person"\s*,\s*"name"\s*:\s*"([^"]+)"')
SCHEMA_JOBTITLE_RE = re.compile(r'"jobTitle"\s*:\s*"([^"]+)"')
OG_URL_RE = re.compile(r'property="og:url" content="https://www\.spotrac\.com/nba/player/_/id/(\d+)')



def match_player(html: str, bbr_name: str, bbr_pos: str) -> dict | None:
    direct = OG_URL_RE.search(html)
    if direct:
        name_m = SCHEMA_NAME_RE.search(html)
        pos_m = SCHEMA_JOBTITLE_RE.search(html)
        matched = {
            "spotrac_id": int(direct.group(1)),
            "name": name_m.group(1) if name_m else bbr_name,
            "team": "",
            "position": pos_m.group(1) if pos_m else "",
            "sport": "nba",
        }
        if normalize_name(matched["name"]) == normalize_name(bbr_name):
            matched["confidence"] = "high"
            return matched
        matched["confidence"] = "medium"
        return matched
    return match_search_results(parse_search_results(html), bbr_name, bbr_pos)


def parse_contract_blocks(html: str, spotrac_id: int) -> list[dict]:
    deals = []
    for team, start_year, years, total in CONTRACT_BLOCK_RE.findall(html):
        total = int(total.replace(",", ""))
        if total <= 0:
            continue
        deals.append(
            {
                "spotrac_id": spotrac_id,
                "date": "",
                "start_year": int(start_year),
                "years": int(years),
                "total_value_m": total / 1e6,
                "team": constants.TEAM_LOGO_MAP.get(team.lower(), team.upper()),
                "deal_type": "standard",
            }
        )
    return deals


def parse_player_page(html: str, spotrac_id: int) -> dict:
    name_match = SCHEMA_NAME_RE.search(html)
    return {
        "spotrac_id": spotrac_id,
        "name": name_match.group(1) if name_match else None,
        "current_contract": parse_current_contract(html),
        "contract_blocks": parse_contract_blocks(html, spotrac_id),
        "transactions": parse_transactions(html, spotrac_id),
        "events": parse_transaction_events(html, spotrac_id),
    }
