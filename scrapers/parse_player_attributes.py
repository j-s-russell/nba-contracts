import re

from bs4 import BeautifulSoup

_ORDINAL_RE = re.compile(r"(\d+) (?:st|nd|rd|th) round")
_PICK_RE = re.compile(r"\((\d+) (?:st|nd|rd|th) pick")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_HEIGHT_RE = re.compile(r"(\d+)-(\d+)")
_WEIGHT_RE = re.compile(r"(\d+)lb")
_BOXSCORE_HREF_RE = re.compile(r"/boxscores/(\d{8})")
_DRAFT_HREF_RE = re.compile(r"/draft/NBA_(\d{4})")


def parse_player_attributes(html: str, player_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", id="info") or soup.find("div", id="meta")
    if container is None:
        return {"player_id": player_id}

    name_el = container.find("h1")
    height_inches = None
    weight_lb = None
    for span in container.find_all("span"):
        text = span.get_text(strip=True)
        height_match = _HEIGHT_RE.fullmatch(text)
        if height_match and height_inches is None:
            height_inches = int(height_match.group(1)) * 12 + int(height_match.group(2))
        weight_match = _WEIGHT_RE.fullmatch(text)
        if weight_match and weight_lb is None:
            weight_lb = int(weight_match.group(1))

    born = None
    born_el = container.find("span", attrs={"data-birth": True})
    if born_el is not None:
        born = born_el.get("data-birth")

    college = None
    college_el = container.find("a", href=lambda h: h and h.startswith("/friv/colleges.fcgi"))
    if college_el is not None:
        college = college_el.get_text(strip=True)

    draft_year = draft_round = draft_pick = debut_year = None
    for paragraph in container.find_all("p"):
        strong = paragraph.find("strong")
        label = strong.get_text(strip=True).strip(":").strip() if strong else ""
        if label.startswith("Draft"):
            text = paragraph.get_text(" ", strip=True)
            round_match = _ORDINAL_RE.search(text)
            if round_match:
                draft_round = int(round_match.group(1))
            pick_match = _PICK_RE.search(text)
            if pick_match:
                draft_pick = int(pick_match.group(1))
            draft_link = paragraph.find("a", href=lambda h: h and "/draft/" in h)
            if draft_link:
                href_match = _DRAFT_HREF_RE.search(draft_link.get("href"))
                if href_match:
                    draft_year = int(href_match.group(1))
            if draft_year is None:
                year_match = _YEAR_RE.search(text)
                if year_match:
                    draft_year = int(year_match.group(1))
        elif label.startswith("NBA Debut"):
            text = paragraph.get_text(" ", strip=True)
            year_match = _YEAR_RE.search(text)
            if year_match:
                debut_year = int(year_match.group(1))
            else:
                debut_link = paragraph.find("a", href=lambda h: h and "/boxscores/" in h)
                if debut_link:
                    href_match = _BOXSCORE_HREF_RE.search(debut_link.get("href"))
                    if href_match:
                        debut_year = int(href_match.group(1)[:4])

    return {
        "player_id": player_id,
        "player_name": name_el.get_text(strip=True) if name_el else None,
        "height_inches": height_inches,
        "weight_lb": weight_lb,
        "born": born,
        "college": college,
        "draft_year": draft_year,
        "draft_round": draft_round,
        "draft_pick": draft_pick,
        "debut_year": debut_year,
    }
