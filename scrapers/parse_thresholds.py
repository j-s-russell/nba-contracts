from bs4 import BeautifulSoup

from scrapers.normalize import parse_float, parse_money

COLUMNS = (
    "season",
    "confirmed",
    "pct_change",
    "cap_floor",
    "salary_cap",
    "luxury_tax",
    "first_apron",
    "second_apron",
    "bae",
    "room_mle",
    "non_tax_mle",
    "tax_mle",
)

MONEY_COLUMNS = COLUMNS[3:]


def parse_thresholds(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="sw_table__default")
    if table is None:
        raise ValueError("No salary cap history table found")

    rows = []
    for tr in table.tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) != len(COLUMNS):
            continue
        row = dict(zip(COLUMNS, cells))
        for col in MONEY_COLUMNS:
            row[col] = parse_money(row[col])
        row["pct_change"] = parse_float(row["pct_change"])
        rows.append(row)
    return rows
