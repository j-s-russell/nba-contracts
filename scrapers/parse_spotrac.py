from bs4 import BeautifulSoup

from scrapers.normalize import parse_float, parse_int, parse_money


def parse_cap_page(html: str, season: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="dataTable")
    if table is None:
        raise ValueError(f"No cap table found for {season}")

    rows = []
    for tr in table.tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 10:
            continue
        rank = parse_int(cells[0].get_text(strip=True))
        if rank is None:
            continue
        team_el = cells[1].find("span", class_="d-none")
        team = team_el.get_text(strip=True) if team_el else cells[1].get_text(strip=True)
        rows.append(
            {
                "season": season,
                "team": team,
                "rank": rank,
                "record": cells[2].get_text(strip=True),
                "players_active": parse_int(cells[3].get_text(strip=True)),
                "avg_age": parse_float(cells[4].get_text(strip=True)),
                "total_cap_allocations": parse_money(cells[5].get_text()),
                "cap_space": parse_money(cells[6].get_text()),
                "active_payroll": parse_money(cells[7].get_text()),
                "active_top3": parse_money(cells[8].get_text()),
                "dead_cap": parse_money(cells[9].get_text()),
            }
        )
    return rows
