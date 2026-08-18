import re

from bs4 import BeautifulSoup, Comment

from scrapers import constants
from scrapers.normalize import parse_float, parse_int

ADVANCED_FIELDS = (
    ("wins", "wins", parse_int),
    ("losses", "losses", parse_int),
    ("mov", "mov", parse_float),
    ("sos", "sos", parse_float),
    ("srs", "srs", parse_float),
    ("off_rtg", "ortg", parse_float),
    ("def_rtg", "drtg", parse_float),
    ("net_rtg", "nrtg", parse_float),
    ("pace", "pace", parse_float),
    ("ts_pct", "ts_pct", parse_float),
)

ROUND_LEVELS = (
    ("First Round", 1),
    ("Semifinals", 2),
    ("Conference Finals", 3),
    ("Finals", 4),
)

SERIES_RECORD_RE = re.compile(r"\((\d+)-(\d+)\)")


def _abbr_from_link(link) -> str | None:
    parts = link.get("href", "").split("/")
    return parts[2] if len(parts) >= 3 else None


def _parse_advanced(soup: BeautifulSoup) -> dict[str, dict]:
    table = soup.find("table", id="advanced-team")
    if table is None:
        raise ValueError("No #advanced-team table found")

    teams = {}
    for cell in table.find_all("td", attrs={"data-stat": "team"}):
        link = cell.find("a", href=lambda h: h and h.startswith("/teams/"))
        if link is None:
            continue
        abbr = constants.canonical_team(_abbr_from_link(link))
        row = {"made_playoffs": cell.get_text().strip().endswith("*")}
        for stat, out, parser in ADVANCED_FIELDS:
            c = cell.parent.find("td", attrs={"data-stat": stat})
            row[out] = parser(c.get_text(strip=True)) if c else None
        teams[abbr] = row
    return teams


def _parse_standings(soup: BeautifulSoup) -> dict[str, dict]:
    table_ids = ("confs_standings_E", "confs_standings_W")
    if soup.find("table", id=table_ids[0]) is None:
        table_ids = ("divs_standings_E", "divs_standings_W")
    standings: dict[str, dict] = {}
    by_conf: dict[str, list[tuple[str, float]]] = {"Eastern": [], "Western": []}
    for table_id, conference in zip(table_ids, ("Eastern", "Western")):
        table = soup.find("table", id=table_id)
        if table is None:
            raise ValueError(f"No #{table_id} table found")
        for tr in table.find_all("tr", class_="full_table"):
            name_cell = tr.find("th", attrs={"data-stat": "team_name"})
            if name_cell is None:
                continue
            link = name_cell.find("a", href=lambda h: h and h.startswith("/teams/"))
            if link is None:
                continue
            abbr = constants.canonical_team(_abbr_from_link(link))
            pct_cell = tr.find("td", attrs={"data-stat": "win_loss_pct"})
            pct = parse_float(pct_cell.get_text(strip=True)) if pct_cell else None
            standings[abbr] = {"conference": conference, "conference_seed": None, "win_loss_pct": pct}
            if pct is not None:
                by_conf[conference].append((abbr, pct))
    if not standings:
        raise ValueError("No standings table found")
    for conference, entries in by_conf.items():
        for rank, (abbr, _) in enumerate(sorted(entries, key=lambda t: -t[1]), start=1):
            standings[abbr]["conference_seed"] = rank
    return standings


def _parse_playoffs(soup: BeautifulSoup) -> dict[str, dict]:
    comment_text = None
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if 'id="all_playoffs"' in str(node):
            comment_text = str(node)
            break
    if comment_text is None:
        return {}

    sub = BeautifulSoup(comment_text, "html.parser")
    table = sub.find("table", id="all_playoffs")
    if table is None:
        return {}

    outcomes = {}
    finals_winner = None
    for tr in table.find_all("tr"):
        label_el = tr.find("span", class_="tooltip")
        if label_el is None:
            continue
        label = label_el.get_text(strip=True)
        level = next((lv for name, lv in ROUND_LEVELS if name in label), None)
        if level is None:
            continue
        links = [a for a in tr.find_all("a") if a.get("href", "").startswith("/teams/")]
        if len(links) != 2:
            continue
        match = SERIES_RECORD_RE.search(tr.get_text(" "))
        if match is None:
            continue
        winner = constants.canonical_team(_abbr_from_link(links[0]))
        loser = constants.canonical_team(_abbr_from_link(links[1]))
        winner_games, loser_games = int(match.group(1)), int(match.group(2))
        for abbr, wins, losses in (
            (winner, winner_games, loser_games),
            (loser, loser_games, winner_games),
        ):
            outcome = outcomes.setdefault(
                abbr,
                {"playoff_round_reached": 0, "playoff_wins": 0, "playoff_losses": 0, "champion": 0},
            )
            outcome["playoff_round_reached"] = max(outcome["playoff_round_reached"], level)
            outcome["playoff_wins"] += wins
            outcome["playoff_losses"] += losses
        if level == 4:
            finals_winner = winner

    if finals_winner is not None:
        outcomes[finals_winner]["champion"] = 1
        outcomes[finals_winner]["playoff_round_reached"] = 5
    return outcomes


def parse_team_stats_page(html: str, season: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    advanced = _parse_advanced(soup)
    standings = _parse_standings(soup)
    playoffs = _parse_playoffs(soup)

    rows = []
    for abbr, adv in advanced.items():
        st = standings.get(abbr, {})
        po = playoffs.get(abbr, {})
        rows.append(
            {
                "season": season,
                "team": abbr,
                "conference": st.get("conference"),
                "conference_seed": st.get("conference_seed"),
                "wins": adv.get("wins"),
                "losses": adv.get("losses"),
                "win_loss_pct": st.get("win_loss_pct"),
                "mov": adv.get("mov"),
                "sos": adv.get("sos"),
                "srs": adv.get("srs"),
                "ortg": adv.get("ortg"),
                "drtg": adv.get("drtg"),
                "nrtg": adv.get("nrtg"),
                "pace": adv.get("pace"),
                "ts_pct": adv.get("ts_pct"),
                "made_playoffs": 1 if adv.get("made_playoffs") else 0,
                "playoff_round_reached": po.get("playoff_round_reached", 0),
                "playoff_wins": po.get("playoff_wins", 0),
                "playoff_losses": po.get("playoff_losses", 0),
                "champion": po.get("champion", 0),
            }
        )
    return rows
