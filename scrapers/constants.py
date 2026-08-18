from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw" / "cap_space"
CACHE_DIR = DATA_DIR / "cache"

SEASON_START = 2015
SEASON_END = 2025

SPOTRAC_CAP_URL = "https://www.spotrac.com/nba/cap/_/year/{year}"
SALARY_SWISH_URL = "https://www.salaryswish.com/salary-cap"
BBR_LEAGUE_URL = "https://www.basketball-reference.com/leagues/NBA_{year}.html"
BBR_TOTALS_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_totals.html"
BBR_ADVANCED_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_advanced.html"
BBR_PLAYER_URL = "https://www.basketball-reference.com/players/{letter}/{player_id}.html"

BBR_TEAM_STATS_DIR = PROJECT_ROOT / "data" / "raw" / "team_stats"
BBR_TEAM_CACHE_DIR = BBR_TEAM_STATS_DIR / "cache"
TEAM_STATS_CSV = BBR_TEAM_STATS_DIR / "team_stats.csv"

PLAYER_STATS_DIR = PROJECT_ROOT / "data" / "raw" / "player_stats"
PLAYER_STATS_CACHE_DIR = PLAYER_STATS_DIR / "cache"
PLAYER_STATS_CSV = PLAYER_STATS_DIR / "player_stats.csv"
PLAYER_ATTRIBUTES_CSV = PLAYER_STATS_DIR / "player_attributes.csv"

PLAYER_CONTRACTS_DIR = PROJECT_ROOT / "data" / "raw" / "player_contracts"
PLAYER_CONTRACTS_CACHE_DIR = PLAYER_CONTRACTS_DIR / "cache"
PLAYER_SALARIES_CSV = PLAYER_CONTRACTS_DIR / "player_salaries.csv"
SPOTRAC_IDS_CSV = PLAYER_CONTRACTS_DIR / "spotrac_ids.csv"
PLAYER_DEALS_CSV = PLAYER_CONTRACTS_DIR / "player_deals.csv"
PLAYER_DEAL_FEATURES_CSV = PLAYER_CONTRACTS_DIR / "player_deal_features.csv"

TEAM_MARKET_DIR = PROJECT_ROOT / "data" / "raw" / "team_market"
TEAM_MARKET_CSV = TEAM_MARKET_DIR / "team_market.csv"

SPOTRAC_SEARCH_URL = "https://www.spotrac.com/search?q={query}"
SPOTRAC_PLAYER_URL = "https://www.spotrac.com/nba/player/_/id/{spotrac_id}"

MIN_CAREER_MINUTES = 500

# ---------------------------------------------------------------------------
# CBA salary rules
# ---------------------------------------------------------------------------
# Maximum year-1 salary as a share of the cap, by years of service *completed
# before the contract's first season*. A Designated Veteran ("supermax") player
# gets the 35% tier regardless of band.
MAX_TIER_BANDS = ((6, 0.25), (9, 0.30))
MAX_TIER_TOP = 0.35

# Maximum annual raise inside a max contract (8% with Bird rights). The ceiling
# on a deal's *average* annual value is therefore higher than the year-1 tier:
#   AAV_ceiling = tier * (1 + MAX_ANNUAL_RAISE * (years - 1) / 2)
MAX_ANNUAL_RAISE = 0.08

# The 2023 CBA caps year-over-year cap growth at 10%. Used only to project the
# cap for a season that has not been set yet (an extension signed in the final
# season covered by league_thresholds.csv starts the year after it).
MAX_CAP_GROWTH = 0.10


def max_tier_pct(service_years_before_start: int | None, supermax: bool = False) -> float | None:
    """Year-1 max salary as a share of the cap (0.25 / 0.30 / 0.35)."""
    if supermax:
        return MAX_TIER_TOP
    if service_years_before_start is None:
        return None
    for upper, pct in MAX_TIER_BANDS:
        if service_years_before_start <= upper:
            return pct
    return MAX_TIER_TOP


def max_tier_aav_pct(tier: float | None, years: int | None) -> float | None:
    """Ceiling on a max deal's AAV, as a share of its first season's cap.

    `max_tier_pct` bounds year-1 salary only. Raises push later years above it,
    so a multi-year max deal's AAV is legitimately above the year-1 tier; this
    is the bound the AAV target must be compared against.
    """
    if tier is None or not years:
        return None
    return tier * (1 + MAX_ANNUAL_RAISE * (years - 1) / 2)

BBR_ABBREV_TO_CANONICAL = {
    "BRK": "BKN",
    "CHO": "CHA",
    "PHO": "PHX",
    "WSH": "WAS",
}

TEAM_ABBREV = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

TEAM_LOGO_MAP = {
    "gs": "GSW", "no": "NOP", "ny": "NYK", "sa": "SAS",
    "bkn": "BKN", "phx": "PHX", "wsh": "WAS", "uta": "UTA",
    "atl": "ATL", "bos": "BOS", "cha": "CHA", "chi": "CHI",
    "cle": "CLE", "dal": "DAL", "den": "DEN", "det": "DET",
    "hou": "HOU", "ind": "IND", "lac": "LAC", "lal": "LAL",
    "mem": "MEM", "mia": "MIA", "mil": "MIL", "min": "MIN",
    "okc": "OKC", "orl": "ORL", "phi": "PHI", "por": "POR",
    "sac": "SAC", "tor": "TOR",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0

TEAM_CAP_CSV = DATA_DIR / "team_cap_space.csv"
THRESHOLDS_CSV = DATA_DIR / "league_thresholds.csv"


def season_label(end_year: int) -> str:
    return f"{end_year - 1}-{str(end_year)[-2:]}"


def seasons() -> list[tuple[int, str]]:
    return [(y, season_label(y + 1)) for y in range(SEASON_START, SEASON_END + 1)]


def bbr_seasons() -> list[tuple[int, str]]:
    return [(y, season_label(y)) for y in range(SEASON_START + 1, SEASON_END + 2)]


def canonical_team(abbrev: str) -> str:
    return BBR_ABBREV_TO_CANONICAL.get(abbrev, abbrev)
