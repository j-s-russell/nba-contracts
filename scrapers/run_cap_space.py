import argparse
import csv
import sys

from scrapers import constants
from scrapers.fetch import FetchClient
from scrapers.parse_spotrac import parse_cap_page
from scrapers.parse_thresholds import parse_thresholds


def season_year_range(args) -> list[int]:
    if args.seasons:
        start, end = (int(x) for x in args.seasons.split("-"))
    else:
        start, end = constants.SEASON_START, constants.SEASON_END
    return list(range(start, end + 1))


def validate_season_rows(rows: list[dict], season: str, thresholds_by_season: dict) -> list[str]:
    problems = []
    if len(rows) != 30:
        problems.append(f"{season}: expected 30 teams, got {len(rows)}")

    salary_cap = thresholds_by_season.get(season, {}).get("salary_cap")
    for row in rows:
        if row["team"] is None or not row["team"]:
            problems.append(f"{season}: missing team name")
        if row["cap_space"] is None or row["total_cap_allocations"] is None:
            problems.append(f"{season} {row['team']}: missing cap figures")
            continue
        if salary_cap:
            expected = salary_cap - row["total_cap_allocations"]
            if abs(expected - row["cap_space"]) > 100_000:
                problems.append(
                    f"{season} {row['team']}: cap_space {row['cap_space']} "
                    f"!= cap {salary_cap} - allocations {row['total_cap_allocations']} "
                    f"(expected {expected})"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape NBA team cap space data.")
    parser.add_argument(
        "--seasons",
        default=None,
        help="Season end-year range, e.g. '2015-2025' (default: full configured range)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Do not read from or write to the raw HTML cache",
    )
    args = parser.parse_args()

    years = season_year_range(args)
    client = FetchClient(use_cache=not args.no_cache)

    thresholds_by_season = {}
    print("Fetching league thresholds from SalarySwish ...")
    thresholds = parse_thresholds(client.fetch(constants.SALARY_SWISH_URL, cache_key="league_thresholds"))
    if not thresholds:
        print("ERROR: no threshold rows parsed")
        return 1
    thresholds_by_season = {t["season"]: t for t in thresholds}
    missing_thresholds = [
        constants.season_label(y + 1) for y in years if constants.season_label(y + 1) not in thresholds_by_season
    ]
    if missing_thresholds:
        print(f"ERROR: missing thresholds for {missing_thresholds}")
        return 1

    all_rows = []
    problems = []
    for year in years:
        season = constants.season_label(year + 1)
        print(f"Fetching {season} ({year}) ...")
        html = client.fetch(constants.SPOTRAC_CAP_URL.format(year=year), cache_key=f"spotrac_cap_{year}")
        rows = parse_cap_page(html, season)
        problems.extend(validate_season_rows(rows, season, thresholds_by_season))
        all_rows.extend(rows)

    if problems:
        print("\nVALIDATION ISSUES:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\nValidation passed: 30 teams/season, no nulls, cap arithmetic consistent.")

    if not problems:
        constants.DATA_DIR.mkdir(parents=True, exist_ok=True)
        team_path = constants.TEAM_CAP_CSV
        with open(team_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)

        threshold_rows = [thresholds_by_season[constants.season_label(y + 1)] for y in years]
        thr_path = constants.THRESHOLDS_CSV
        with open(thr_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(threshold_rows[0].keys()))
            writer.writeheader()
            writer.writerows(threshold_rows)

        print(f"\nWrote {len(all_rows)} team-season rows to {team_path}")
        print(f"Wrote {len(threshold_rows)} season threshold rows to {thr_path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
