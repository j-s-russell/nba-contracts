from bs4 import BeautifulSoup

from scrapers.normalize import parse_float, parse_int

TOTALS_SUM_COLUMNS = (
    "games",
    "games_started",
    "mp",
    "fg",
    "fga",
    "fg3",
    "fg3a",
    "fg2",
    "fg2a",
    "ft",
    "fta",
    "orb",
    "drb",
    "trb",
    "ast",
    "stl",
    "blk",
    "tov",
    "pf",
    "pts",
)

ADVANCED_RATE_COLUMNS = ("per", "usg_pct", "obpm", "dbpm", "bpm")
ADVANCED_SUM_COLUMNS = ("ows", "dws", "ws", "vorp")


def _cell(row, stat, parser=None):
    cell = row.find("td", attrs={"data-stat": stat})
    if cell is None:
        return None
    text = cell.get_text(strip=True)
    return parser(text) if parser else text


def _player_rows(table):
    for tr in table.find_all("tr"):
        if "partial_table" in (tr.get("class") or []):
            continue
        pid_el = tr.find("td", attrs={"data-append-csv": True}) or tr.find(
            "th", attrs={"data-append-csv": True}
        )
        if pid_el is None:
            continue
        name_el = tr.find("a", href=lambda h: h and h.startswith("/players/"))
        if name_el is None:
            continue
        yield pid_el.get("data-append-csv"), name_el.get_text(strip=True), tr


def parse_totals(html: str) -> dict[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="totals_stats")
    if table is None:
        raise ValueError("No #totals_stats table found")

    players = {}
    for pid, name, tr in _player_rows(table):
        games = _cell(tr, "games", parse_int) or 0
        team = _cell(tr, "team_name_abbr")
        entry = players.setdefault(
            pid,
            {
                "name": name,
                "age": _cell(tr, "age", parse_int),
                "pos": _cell(tr, "pos"),
                "team": None,
                "team_games": 0,
                "stats": {},
            },
        )
        if games > entry["team_games"]:
            entry["team_games"] = games
            entry["team"] = team
        for stat in TOTALS_SUM_COLUMNS:
            parser = parse_int if stat in ("games", "games_started") else parse_float
            value = _cell(tr, stat, parser)
            if value is not None:
                entry["stats"][stat] = entry["stats"].get(stat, 0) + value
    return players


def parse_advanced(html: str) -> dict[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="advanced")
    if table is None:
        raise ValueError("No #advanced table found")

    players = {}
    for pid, name, tr in _player_rows(table):
        minutes = _cell(tr, "mp", parse_float) or 0.0
        entry = players.setdefault(pid, {"name": name, "mp": 0.0, "rate": {}, "sum": {}})
        entry["mp"] += minutes
        for stat in ADVANCED_RATE_COLUMNS:
            value = _cell(tr, stat, parse_float)
            if value is not None:
                entry["rate"][stat] = entry["rate"].get(stat, 0.0) + value * minutes
        for stat in ADVANCED_SUM_COLUMNS:
            value = _cell(tr, stat, parse_float)
            if value is not None:
                entry["sum"][stat] = entry["sum"].get(stat, 0.0) + value
    return players


def _ratio(made, attempts):
    if made is None or not attempts:
        return None
    return round(made / attempts, 4)


def build_player_rows(
    season: str, totals: dict[str, dict], advanced: dict[str, dict]
) -> list[dict]:
    rows = []
    for pid, entry in totals.items():
        stats = entry["stats"]
        games = stats.get("games") or 0
        adv = advanced.get(pid, {"mp": 0.0, "rate": {}, "sum": {}})
        adv_mp = adv["mp"]

        def per_game(key, digits=3):
            value = stats.get(key)
            if value is None or not games:
                return None
            return round(value / games, digits)

        fg, fga = stats.get("fg"), stats.get("fga")
        fg3, fg3a = stats.get("fg3"), stats.get("fg3a")
        fg2, fg2a = stats.get("fg2"), stats.get("fg2a")
        ft, fta = stats.get("ft"), stats.get("fta")
        pts, mp = stats.get("pts"), stats.get("mp")
        if fg is not None and fg3 is not None and fga:
            efg = round((fg + 0.5 * fg3) / fga, 4)
        else:
            efg = None
        if pts is not None and fga is not None and fta is not None and (fga + 0.44 * fta):
            ts = round(pts / (2 * (fga + 0.44 * fta)), 4)
        else:
            ts = None
        ws = adv["sum"].get("ws")
        ws_per_48 = round(ws / (adv_mp / 48.0), 3) if ws is not None and adv_mp else None

        row = {
            "season": season,
            "player_id": pid,
            "player_name": entry["name"],
            "pos": entry.get("pos"),
            "age": entry.get("age"),
            "team": entry.get("team"),
            "games": games or None,
            "games_started": stats.get("games_started"),
            "minutes_per_game": per_game("mp"),
            "pts_per_game": per_game("pts"),
            "trb_per_game": per_game("trb"),
            "ast_per_game": per_game("ast"),
            "stl_per_game": per_game("stl"),
            "blk_per_game": per_game("blk"),
            "tov_per_game": per_game("tov"),
            "fg_pct": _ratio(fg, fga),
            "fg3_pct": _ratio(fg3, fg3a),
            "fg2_pct": _ratio(fg2, fg2a),
            "ft_pct": _ratio(ft, fta),
            "efg_pct": efg,
            "per": round(adv["rate"].get("per", 0) / adv_mp, 2) if adv_mp and adv["rate"].get("per") is not None else None,
            "ts_pct": ts,
            "usg_pct": round(adv["rate"].get("usg_pct", 0) / adv_mp, 4) if adv_mp and adv["rate"].get("usg_pct") is not None else None,
            "bpm": round(adv["rate"].get("bpm", 0) / adv_mp, 2) if adv_mp and adv["rate"].get("bpm") is not None else None,
            "obpm": round(adv["rate"].get("obpm", 0) / adv_mp, 2) if adv_mp and adv["rate"].get("obpm") is not None else None,
            "dbpm": round(adv["rate"].get("dbpm", 0) / adv_mp, 2) if adv_mp and adv["rate"].get("dbpm") is not None else None,
            "vorp": adv["sum"].get("vorp"),
            "ws": ws,
            "ws_per_48": ws_per_48,
            "years_in_league": None,
        }
        rows.append(row)
    return rows


def parse_player_stats_pages(
    html_totals: str, html_advanced: str, season: str
) -> list[dict]:
    totals = parse_totals(html_totals)
    advanced = parse_advanced(html_advanced)
    return build_player_rows(season, totals, advanced)
