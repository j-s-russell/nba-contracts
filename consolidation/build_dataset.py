#!/usr/bin/env python3
"""Build the consolidated modeling dataset from raw CSVs.

Reads:
  - data/raw/player_contracts/player_deal_features.csv  (base: one row per deal)
  - data/raw/player_stats/player_stats.csv              (player quality)
  - data/raw/player_stats/player_attributes.csv         (physical / draft info)
  - data/raw/team_stats/team_stats.csv                  (signing-team strength)
  - data/raw/cap_space/team_cap_space.csv               (signing-team payroll)

Writes:
  - data/model/features.csv  (one row per deal, leak-safe feature joins)

Leakage guard: only information available at signing is used. A deal signed in
`deal_year` Y joins the PRIOR season, labeled f"{Y-1}-{str(Y)[-2:]}". Career and
rolling 3-season aggregates are computed only from seasons up to that one.

Usage:
    python consolidation/build_dataset.py [--scope {market,all}] [--out PATH]
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW = PROJECT_ROOT / "data" / "raw"

DEALS_CSV = RAW / "player_contracts" / "player_deal_features.csv"
STATS_CSV = RAW / "player_stats" / "player_stats.csv"
ATTRS_CSV = RAW / "player_stats" / "player_attributes.csv"
TEAM_STATS_CSV = RAW / "team_stats" / "team_stats.csv"
TEAM_CAP_CSV = RAW / "cap_space" / "team_cap_space.csv"

MARKET_VIA = {"free_agency", "extension", "offer_sheet", "rfa_match", "sign_and_trade"}

# Non-NBA artifact team codes that must never enter the dataset.
ARTIFACT_TEAMS = {"ARI", "BAL", "BUF", "CAR", "EDM", "NYG", "NYJ", "OTT", "PIT"}

FIELD_TEAM = ["srs", "nrtg", "mov", "wins", "made_playoffs", "champion"]
FIELD_CAP = ["cap_space", "active_payroll", "dead_cap"]

# The deal files store Utah under the historical abbreviation "UTH" (e.g., Spotrac),
# while the team stats / cap-space tables use Basketball-Reference's "UTA". Without
# normalizing, every Utah deal would silently lose its signing-team context.
TEAM_CODE_NORMALIZE = {"UTH": "UTA"}


def season_label(year: int) -> str:
    return f"{year - 1}-{str(year)[-2:]}"


def _f(row: dict, key: str) -> float | None:
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _int(row: dict, key: str) -> int | None:
    v = _f(row, key)
    return int(v) if v is not None else None


def load_stats() -> dict:
    """{player_id: {season_label: row}}"""
    by_pid = defaultdict(dict)
    with open(STATS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_pid[r["player_id"]][r["season"]] = r
    return by_pid


def load_attrs() -> dict:
    out = {}
    with open(ATTRS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["player_id"]] = r
    return out


def load_team_tables():
    """Both keyed by (season_label, team_abbrev)."""
    ts, tc = {}, {}
    for path, store in ((TEAM_STATS_CSV, ts), (TEAM_CAP_CSV, tc)):
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                store[(r["season"], r["team"])] = r
    return ts, tc


def _career_mode_pos(rows: dict, year: int) -> str | None:
    """Most-played position over seasons <= prior; None if never played."""
    counts: dict[str, int] = {}
    for s, row in rows.items():
        sy = int(s[:4]) if len(s) >= 4 else 0
        if sy > year - 1:
            continue
        if (_f(row, "games") or 0) > 0:
            p = row.get("pos")
            if p:
                counts[p] = counts.get(p, 0) + 1
    return max(counts, key=counts.get) if counts else None


def player_quality(pid: str, year: int, stats_by_pid: dict) -> dict:
    prior = season_label(year)
    rows = stats_by_pid.get(pid, {})
    prior_row = rows.get(prior, {})

    out = {}
    out["prior_games"] = _int(prior_row, "games")
    out["has_prior_stats"] = 1 if (out["prior_games"] or 0) > 0 else 0
    out["pos"] = prior_row.get("pos") or _career_mode_pos(rows, year)
    for k, col in (
        ("prior_ppg", "pts_per_game"),
        ("prior_mpg", "minutes_per_game"),
        ("prior_per", "per"),
        ("prior_bpm", "bpm"),
        ("prior_vorp", "vorp"),
        ("prior_ws", "ws"),
        ("prior_ws48", "ws_per_48"),
        ("prior_usg_pct", "usg_pct"),
        ("prior_ts_pct", "ts_pct"),
        ("prior_ast", "ast_per_game"),
        ("prior_trb", "trb_per_game"),
        ("prior_blk", "blk_per_game"),
        ("prior_stl", "stl_per_game"),
        ("prior_tov", "tov_per_game"),
    ):
        out[k] = _f(prior_row, col)

    career_games = 0
    career_seasons = 0
    career_vorp = 0.0
    career_ws = 0.0
    career_pts = 0.0
    career_min = 0.0
    recent_vorp = 0.0
    recent_ws = 0.0
    for s, row in rows.items():
        sy = int(s[:4]) if len(s) >= 4 else 0
        if sy > year - 1:
            continue
        g = _f(row, "games") or 0
        career_games += g
        career_seasons += 1
        career_vorp += _f(row, "vorp") or 0
        career_ws += _f(row, "ws") or 0
        career_pts += (_f(row, "pts_per_game") or 0) * g
        career_min += (_f(row, "minutes_per_game") or 0) * g
        if sy >= year - 3:
            recent_vorp += _f(row, "vorp") or 0
            recent_ws += _f(row, "ws") or 0
    out["career_seasons"] = career_seasons
    out["career_games"] = career_games
    out["career_vorp"] = round(career_vorp, 2)
    out["career_ws"] = round(career_ws, 2)
    out["career_ppg"] = round(career_pts / career_games, 2) if career_games else None
    out["career_mpg"] = round(career_min / career_games, 2) if career_games else None
    out["recent3_vorp"] = round(recent_vorp, 2)
    out["recent3_ws"] = round(recent_ws, 2)
    return out


def team_context(team: str, year: int, team_stats: dict, team_cap: dict) -> dict:
    team = TEAM_CODE_NORMALIZE.get(team, team)
    prior = season_label(year)
    ts_row = team_stats.get((prior, team), {})
    tc_row = team_cap.get((prior, team), {})
    out = {}
    for k in FIELD_TEAM:
        out[f"team_{k}"] = _f(ts_row, k)
    for k in FIELD_CAP:
        v = _f(tc_row, k)
        out[f"team_{k}_m"] = round(v / 1e6, 3) if v is not None else None
    out["team_players_active"] = _int(tc_row, "players_active")
    return out


def cba_regime(year: int) -> str:
    if year <= 2016:
        return "pre_2017"
    if year <= 2022:
        return "cba_2017"
    return "cba_2023"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build consolidated modeling dataset.")
    ap.add_argument("--scope", choices=["market", "all"], default="market",
                    help="market = signed_via in %s & years>=2 (default); all = every deal with a valid target"
                    % ", ".join(sorted(MARKET_VIA)))
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "model" / "features.csv")
    args = ap.parse_args()

    stats_by_pid = load_stats()
    attrs = load_attrs()
    team_stats, team_cap = load_team_tables()

    deals = list(csv.DictReader(open(DEALS_CSV, encoding="utf-8")))
    rows = []
    skipped = {"no_target": 0, "artifact": 0, "non_market": 0}
    for d in deals:
        team = d["team"] or ""
        if team in ARTIFACT_TEAMS:
            skipped["artifact"] += 1
            continue
        if not d["aav_cap_share"]:
            skipped["no_target"] += 1
            continue
        if args.scope == "market" and not (d["market"] == "1"):
            skipped["non_market"] += 1
            continue

        year = _int(d, "deal_year")
        if year is None:
            skipped["no_target"] += 1
            continue
        via = d["signed_via"] or ""
        start_eff = year + 1 if via == "extension" else year
        end_year = _int(d, "end_year")
        n_years = (end_year - start_eff + 1) if end_year is not None else None

        row = {
            "player_id": d["player_id"],
            "player_name": d["player_name"],
            "deal_date": d["deal_date"],
            "deal_year": year,
            "team": team,
            "years": n_years,
            "signed_via": via,
            "deal_type": d["deal_type"] or "",
            "fa_status": d["fa_status"] or "",
            "aav_m": _f(d, "aav_m"),
            "salary_cap_m": _f(d, "salary_cap_m"),
            "aav_cap_share": _f(d, "aav_cap_share"),
            "log_aav_cap_share": _f(d, "log_aav_cap_share"),
        }

        row.update(player_quality(d["player_id"], year, stats_by_pid))

        a = attrs.get(d["player_id"], {})
        born = a.get("born", "")
        row["age_at_signing"] = (year - int(born[:4])) if len(born) >= 4 else None
        row["height_inches"] = _int(a, "height_inches")
        row["weight_lb"] = _int(a, "weight_lb")
        row["years_pro"] = max(0, year - dy) if (dy := _int(a, "debut_year")) else None
        row["draft_year"] = _int(a, "draft_year")

        row.update({
            "incumbent": d["incumbent"] if d["incumbent"] not in ("", None) else None,
            "player_option": _int(d, "player_option"),
            "team_option": _int(d, "team_option"),
            "max_tier_pct": _f(d, "max_tier_pct"),
            "supermax": _int(d, "supermax"),
            "outstanding_options": _int(d, "outstanding_options"),
        })

        row.update(team_context(team, year, team_stats, team_cap))

        prior = d["prior_team"] or ""
        row["prior_team"] = prior
        if prior and prior not in ARTIFACT_TEAMS:
            pc = team_context(prior, year, team_stats, team_cap)
            for k, v in pc.items():
                if k.startswith("team_"):
                    row["prior_" + k[len("team_"):]] = v
            row["prior_team_big_market"] = d["prior_team_big_market"] if d["prior_team_big_market"] not in ("", None) else None
            row["prior_team_market_size"] = d["prior_team_market_size"]
            row["prior_team_metro_pop_m"] = _f(d, "prior_team_metro_pop_m")
        else:
            for k in ("prior_srs", "prior_nrtg", "prior_mov", "prior_wins",
                      "prior_made_playoffs", "prior_champion", "prior_cap_space_m",
                      "prior_active_payroll_m", "prior_dead_cap_m", "prior_players_active",
                      "prior_team_big_market", "prior_team_market_size", "prior_team_metro_pop_m"):
                row[k] = None
        row["team_big_market"] = d["team_big_market"] if d["team_big_market"] not in ("", None) else None
        row["team_market_size"] = d["team_market_size"]
        row["team_metro_pop_m"] = _f(d, "team_metro_pop_m")
        row["team_dma_rank"] = _int(d, "team_dma_rank")
        row["team_tv_homes_m"] = _f(d, "team_tv_homes_m")
        row["cba_regime"] = cba_regime(year)

        rows.append(row)

    fieldnames = [
        "player_id", "player_name", "deal_date", "deal_year", "team", "years",
        "signed_via", "deal_type", "fa_status",
        "aav_m", "salary_cap_m", "aav_cap_share", "log_aav_cap_share",
        "has_prior_stats", "prior_games", "prior_ppg", "prior_mpg", "prior_per",
        "prior_bpm", "prior_vorp", "prior_ws", "prior_ws48", "prior_usg_pct", "prior_ts_pct",
        "prior_ast", "prior_trb", "prior_blk", "prior_stl", "prior_tov",
        "career_seasons", "career_games", "career_ppg", "career_mpg", "career_vorp", "career_ws",
        "recent3_vorp", "recent3_ws",
        "pos",
        "age_at_signing", "height_inches", "weight_lb", "years_pro", "draft_year",
        "incumbent", "player_option", "team_option", "max_tier_pct", "supermax", "outstanding_options",
        "team_srs", "team_nrtg", "team_mov", "team_wins", "team_made_playoffs", "team_champion",
        "team_cap_space_m", "team_active_payroll_m", "team_dead_cap_m", "team_players_active",
        "prior_team",
        "prior_srs", "prior_nrtg", "prior_mov", "prior_wins", "prior_made_playoffs", "prior_champion",
        "prior_cap_space_m", "prior_active_payroll_m", "prior_dead_cap_m", "prior_players_active",
        "prior_team_big_market", "prior_team_market_size", "prior_team_metro_pop_m",
        "team_big_market", "team_market_size", "team_metro_pop_m", "team_dma_rank", "team_tv_homes_m",
        "cba_regime",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.out}")
    print(f"Skipped: {skipped}")
    print(f"  position present: {sum(1 for r in rows if r['pos'])}/{len(rows)}")
    print(f"  prior stats present: {sum(1 for r in rows if r['has_prior_stats'])}/{len(rows)}")
    print(f"  team SRS present: {sum(1 for r in rows if r['team_srs'] is not None)}/{len(rows)}")
    print(f"  prior team present: {sum(1 for r in rows if r['prior_team'])}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
