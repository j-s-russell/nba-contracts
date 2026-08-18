import argparse
import csv
import sys

from scrapers import constants
from scrapers.fetch import FetchClient
from scrapers.parse_team_stats import parse_team_stats_page

REQUIRED_COLUMNS = (
    "conference",
    "conference_seed",
    "wins",
    "losses",
    "win_loss_pct",
    "ortg",
    "drtg",
    "nrtg",
    "pace",
)


def year_range(args) -> list[int]:
    if args.seasons:
        start, end = (int(x) for x in args.seasons.split("-"))
    else:
        start, end = constants.SEASON_START + 1, constants.SEASON_END + 1
    return list(range(start, end + 1))


def validate_season(rows: list[dict], season: str) -> list[str]:
    problems = []
    if len(rows) != 30:
        problems.append(f"{season}: expected 30 teams, got {len(rows)}")

    for row in rows:
        if row["team"] is None or not row["team"]:
            problems.append(f"{season}: missing team abbreviation")
            continue
        for key in REQUIRED_COLUMNS:
            if row[key] is None:
                problems.append(f"{season} {row['team']}: missing {key}")
        if row["made_playoffs"] and row["playoff_round_reached"] == 0:
            problems.append(f"{season} {row['team']}: made playoffs but no series data")
        if not row["made_playoffs"] and row["playoff_round_reached"] > 0:
            problems.append(f"{season} {row['team']}: has series data but not marked playoff team")
        if row["nrtg"] is not None and row["ortg"] is not None and row["drtg"] is not None:
            if abs(row["nrtg"] - (row["ortg"] - row["drtg"])) > 0.1:
                problems.append(
                    f"{season} {row['team']}: nrtg {row['nrtg']} "
                    f"!= ortg {row['ortg']} - drtg {row['drtg']}"
                )
        if (
            row["wins"] is not None
            and row["losses"] is not None
            and row["win_loss_pct"] is not None
        ):
            total = row["wins"] + row["losses"]
            if total and abs(row["win_loss_pct"] - row["wins"] / total) > 0.001:
                problems.append(
                    f"{season} {row['team']}: win_loss_pct {row['win_loss_pct']} "
                    f"inconsistent with W-L record"
                )

    total_wins = sum(row["wins"] or 0 for row in rows)
    total_losses = sum(row["losses"] or 0 for row in rows)
    if total_wins != total_losses:
        problems.append(f"{season}: total wins {total_wins} != total losses {total_losses}")

    made = [row for row in rows if row["made_playoffs"]]
    if len(made) != 16:
        problems.append(f"{season}: expected 16 playoff teams, got {len(made)}")

    for level, count in ((5, 1), (4, 1), (3, 2), (2, 4), (1, 8), (0, 14)):
        actual = sum(1 for row in rows if row["playoff_round_reached"] == level)
        if actual != count:
            problems.append(f"{season}: expected {count} teams at playoff round {level}, got {actual}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape NBA team stats from Basketball-Reference.")
    parser.add_argument(
        "--seasons",
        default=None,
        help="Season end-year range, e.g. '2016-2026' (default: full configured range)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Do not read from or write to the raw HTML cache",
    )
    args = parser.parse_args()

    years = year_range(args)
    client = FetchClient(use_cache=not args.no_cache, cache_dir=constants.BBR_TEAM_CACHE_DIR)

    all_rows = []
    problems = []
    for year in years:
        season = constants.season_label(year)
        print(f"Fetching {season} ({year}) ...")
        html = client.fetch(constants.BBR_LEAGUE_URL.format(year=year), cache_key=f"bbr_league_{year}")
        rows = parse_team_stats_page(html, season)
        problems.extend(validate_season(rows, season))
        all_rows.extend(rows)

    if problems:
        print("\nVALIDATION ISSUES:")
        for p in problems:
            print(f"  - {p}")
    else:
        print(
            "\nValidation passed: 30 teams/season, 16 playoff teams, "
            "round distribution & ratings consistent."
        )

    if not problems:
        constants.BBR_TEAM_STATS_DIR.mkdir(parents=True, exist_ok=True)
        path = constants.TEAM_STATS_CSV
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nWrote {len(all_rows)} team-season rows to {path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
