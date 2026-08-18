import argparse
import csv
import re
import sys
from collections import Counter

from scrapers import constants
from scrapers.fetch import FetchClient, FetchError
from scrapers.parse_player_attributes import parse_player_attributes
from scrapers.parse_player_stats import parse_player_stats_pages

PCT_COLUMNS = ("fg_pct", "fg3_pct", "fg2_pct", "ft_pct")
RATE_COLUMNS = ("efg_pct", "ts_pct")
PLAYER_ID_RE = re.compile(r"^[a-z]{4,}\d{2}$")


def year_range(args) -> list[int]:
    if args.seasons:
        start, end = (int(x) for x in args.seasons.split("-"))
    else:
        start, end = constants.SEASON_START + 1, constants.SEASON_END + 1
    return list(range(start, end + 1))


def validate_stats_season(rows: list[dict], season: str) -> list[str]:
    problems = []
    ids = [r["player_id"] for r in rows]
    if len(ids) != len(set(ids)):
        duplicates = sorted({pid for pid, count in Counter(ids).items() if count > 1})
        problems.append(f"{season}: duplicate player_ids {duplicates[:5]}")
    if not (300 <= len(rows) <= 800):
        problems.append(f"{season}: unusual player count {len(rows)}")
    for row in rows:
        if not row["player_id"] or not PLAYER_ID_RE.match(row["player_id"]):
            problems.append(f"{season}: malformed player_id {row['player_id']!r}")
            continue
        for key, bounds in (
            (("fg_pct", "fg3_pct", "fg2_pct", "ft_pct"), (0, 1)),
            (("efg_pct", "ts_pct"), (0, 1.5)),
        ):
            for stat in key:
                value = row[stat]
                if value is not None and not (bounds[0] <= value <= bounds[1]):
                    problems.append(f"{season} {row['player_id']}: {stat} out of range {value}")
        if row["games"] and row["pts_per_game"] is None:
            problems.append(
                f"{season} {row['player_id']}: missing per-game stats with {row['games']} games"
            )
    return problems


def merge_years_in_league(stats_rows: list[dict], attributes_by_id: dict) -> None:
    for row in stats_rows:
        attrs = attributes_by_id.get(row["player_id"])
        if attrs and attrs.get("debut_year"):
            season_start = int(row["season"][:4])
            row["years_in_league"] = max(1, season_start - int(attrs["debut_year"]) + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape NBA player stats from Basketball-Reference.")
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
    parser.add_argument(
        "--skip-attributes",
        action="store_true",
        help="Skip fetching player attribute pages (years_in_league left blank)",
    )
    parser.add_argument(
        "--attributes-from-csv",
        action="store_true",
        help="Load attributes from the existing CSV only; never fetch (new players get no years_in_league)",
    )
    parser.add_argument(
        "--players-limit",
        type=int,
        default=None,
        help="Only fetch attributes for the first N players (testing)",
    )
    args = parser.parse_args()

    years = year_range(args)
    client = FetchClient(use_cache=not args.no_cache, cache_dir=constants.PLAYER_STATS_CACHE_DIR)
    player_client = FetchClient(
        use_cache=not args.no_cache,
        cache_dir=constants.PLAYER_STATS_CACHE_DIR,
        max_requests_per_window=17,
        window_seconds=110,
    )

    all_rows = []
    problems = []
    for year in years:
        season = constants.season_label(year)
        print(f"Fetching {season} ({year}) ...")
        html_totals = client.fetch(
            constants.BBR_TOTALS_URL.format(year=year), cache_key=f"bbr_totals_{year}"
        )
        html_advanced = client.fetch(
            constants.BBR_ADVANCED_URL.format(year=year), cache_key=f"bbr_advanced_{year}"
        )
        rows = parse_player_stats_pages(html_totals, html_advanced, season)
        problems.extend(validate_stats_season(rows, season))
        all_rows.extend(rows)

    if problems:
        print("\nSTATS VALIDATION ISSUES:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"\nStats parsed: {len(all_rows)} player-season rows across {len(years)} seasons.")

    player_ids = sorted({row["player_id"] for row in all_rows})
    print(f"Distinct players: {len(player_ids)}")

    attributes_by_id = {}
    fetch_failures = []
    if not args.skip_attributes:
        # Seed from an existing attributes CSV so years_in_league survives and
        # already-known players are not re-fetched.
        if constants.PLAYER_ATTRIBUTES_CSV.exists():
            with open(constants.PLAYER_ATTRIBUTES_CSV, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    attributes_by_id[r["player_id"]] = r
            print(f"Seeded {len(attributes_by_id)} players from {constants.PLAYER_ATTRIBUTES_CSV.name}")
        if not args.attributes_from_csv:
            selected = sorted(set(player_ids) - set(attributes_by_id))
            if args.players_limit is not None:
                selected = selected[: args.players_limit]
            print(f"\nFetching attribute pages for {len(selected)} players ...")
            for i, pid in enumerate(selected, start=1):
                url = constants.BBR_PLAYER_URL.format(letter=pid[0], player_id=pid)
                try:
                    html = player_client.fetch(url, cache_key=f"bbr_player_{pid}")
                    attributes_by_id[pid] = parse_player_attributes(html, pid)
                except FetchError as exc:
                    fetch_failures.append(pid)
                    print(f"  WARN: failed to fetch {pid}: {exc}")
                if i % 50 == 0:
                    print(f"  ... {i}/{len(selected)} players")
        if fetch_failures:
            print(f"\nWARNING: {len(fetch_failures)} player pages failed: {fetch_failures[:10]}")

        if not fetch_failures:
            missing_attrs = sorted(set(player_ids) - set(attributes_by_id))
            no_height = [pid for pid, a in attributes_by_id.items() if a.get("height_inches") is None]
            no_weight = [pid for pid, a in attributes_by_id.items() if a.get("weight_lb") is None]
            no_debut = [pid for pid, a in attributes_by_id.items() if a.get("debut_year") is None]
            print(
                f"\nAttributes coverage: missing={len(missing_attrs)}, "
                f"no height={len(no_height)}, no weight={len(no_weight)}, "
                f"no debut year={len(no_debut)}"
            )
    else:
        print("Skipping attribute fetch (--skip-attributes).")

    merge_years_in_league(all_rows, attributes_by_id)

    constants.PLAYER_STATS_DIR.mkdir(parents=True, exist_ok=True)
    with open(constants.PLAYER_STATS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    if attributes_by_id:
        with open(constants.PLAYER_ATTRIBUTES_CSV, "w", newline="", encoding="utf-8") as f:
            attrs = list(attributes_by_id.values())
            writer = csv.DictWriter(f, fieldnames=list(attrs[0].keys()))
            writer.writeheader()
            writer.writerows(attrs)
        print(f"Wrote {len(attrs)} attribute rows to {constants.PLAYER_ATTRIBUTES_CSV}")

    print(f"Wrote {len(all_rows)} player-season rows to {constants.PLAYER_STATS_CSV}")

    if fetch_failures:
        print("Run incomplete: some player pages failed. Re-run to resume via cache.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
