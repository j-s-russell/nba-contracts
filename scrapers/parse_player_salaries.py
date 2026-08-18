import re

from scrapers import constants

TABLE_RE = re.compile(r'<table[^>]*id="all_salaries"[^>]*>(.*?)</table>', re.S)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<t[dh][^>]*>.*?</t[dh]>", re.S)


def parse_salaries_table(html: str, player_id: str) -> list[dict]:
    table = TABLE_RE.search(html)
    if not table:
        return []
    rows = []
    for row in ROW_RE.findall(table.group(1)):
        cells = []
        for cell in CELL_RE.findall(row):
            text = re.sub(r"<[^>]+>", "", cell).strip()
            csk = re.search(r'csk="(\d+)"', cell)
            team_abbrev = re.search(r"/teams/([A-Z]{3})/", cell)
            cells.append(
                {
                    "text": text,
                    "csk": csk.group(1) if csk else None,
                    "team_abbrev": team_abbrev.group(1) if team_abbrev else None,
                }
            )
        if not cells:
            continue
        season = cells[0]["text"]
        team = cells[1]["team_abbrev"] if len(cells) > 1 and cells[1]["team_abbrev"] else ""
        lg = cells[2]["text"] if len(cells) > 2 else ""
        salary_raw = cells[3]["csk"] if len(cells) > 3 else None
        if not re.match(r"^\d{4}-\d{2}$", season) or not salary_raw:
            continue
        rows.append(
            {
                "player_id": player_id,
                "season": season,
                "team": constants.canonical_team(team) if team else "",
                "lg": lg,
                "salary": int(salary_raw),
            }
        )
    return rows
