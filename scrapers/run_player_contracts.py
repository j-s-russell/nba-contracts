import argparse
import csv
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from urllib.parse import quote

from scrapers import constants
from scrapers.fetch import FetchClient, FetchError
from scrapers.parse_player_salaries import parse_salaries_table
from scrapers.parse_spotrac_deals import (
    OG_URL_RE,
    SCHEMA_JOBTITLE_RE,
    SCHEMA_NAME_RE,
    match_player,
    normalize_name,
    parse_player_page,
)

SEASON_LABELS = {f"{y - 1}-{str(y)[-2:]}" for y in range(2016, 2027)}

# Tolerance for flagging deals whose AAV exceeds the max-tier ceiling.
# Deals within this margin of the theoretical cap are not marked "over tier".
OVER_TIER_TOL = 0.005

SPOTRAC_OVERRIDES = {
    "jacksgg01": 85972,   # GG Jackson II -> G.G. Jackson
    "mbahalu01": 6130,    # Luc Mbah a Moute -> Luc Richard Mbah a Moute
    "brownbr01": 27008,   # Bruce Brown -> Bruce Brown Jr.
    "chrisca02": 91777,   # Cam Christie -> Cameron Christie
    "joneshe01": 74142,   # Herbert Jones -> Herb Jones
    "martike04": 70694,   # KJ Martin -> Kenyon Martin Jr.
    "morrima03": 8065,    # Marcus Morris -> Marcus Morris Sr.
    "smithis01": 7116,    # Ish Smith -> Ishmael Smith
    "waltode01": 24263,   # Derrick Walton -> Derrick Walton Jr.
    "willilo02": 2657,    # Lou Williams -> Louis Williams
    "williro04": 26993,   # Robert Williams -> Robert Williams III
}


def load_player_pool() -> list[dict]:
    stats = list(csv.DictReader(open(constants.PLAYER_STATS_CSV, encoding="utf-8")))
    by_id = defaultdict(list)
    for r in stats:
        by_id[r["player_id"]].append(r)
    pool = []
    for pid, rows in by_id.items():
        minutes = sum(
            float(r["minutes_per_game"]) * float(r["games"]) for r in rows
        )
        if minutes < constants.MIN_CAREER_MINUTES:
            continue
        pos = Counter(r["pos"] for r in rows).most_common(1)[0][0]
        teams = {
            constants.canonical_team(r["team"])
            for r in rows
            if r["team"] not in ("2TM", "3TM", "TOT")
        }
        pool.append(
            {
                "player_id": pid,
                "player_name": rows[0]["player_name"],
                "pos": pos,
                "teams": teams,
                "career_minutes": round(minutes),
            }
        )
    pool.sort(key=lambda p: p["player_id"])
    return pool


def write_csv(path, rows, fieldnames):
    constants.PLAYER_CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {path}")


def step_salaries(pool: list[dict], no_cache: bool) -> list[dict]:
    html_by_id = {}
    for pid in (p["player_id"] for p in pool):
        path = constants.PLAYER_STATS_CACHE_DIR / f"bbr_player_{pid}.html"
        if path.exists():
            html_by_id[pid] = path.read_text(encoding="utf-8")
    rows = []
    missing = []
    for p in pool:
        html = html_by_id.get(p["player_id"])
        if html is None:
            missing.append(p["player_id"])
            continue
        for s in parse_salaries_table(html, p["player_id"]):
            if s["season"] in SEASON_LABELS:
                rows.append(
                    {
                        "player_id": p["player_id"],
                        "player_name": p["player_name"],
                        "season": s["season"],
                        "season_start": int(s["season"][:4]),
                        "team": s["team"],
                        "salary": s["salary"],
                    }
                )
    write_csv(
        constants.PLAYER_SALARIES_CSV,
        rows,
        ["player_id", "player_name", "season", "season_start", "team", "salary"],
    )
    if missing:
        print(f"WARNING: {len(missing)} players missing BBR salary table: {missing}")
    return rows


def step_spotrac_ids(pool: list[dict], client: FetchClient, no_cache: bool) -> list[dict]:
    rows = []
    failures = []
    for i, p in enumerate(pool, start=1):
        slug = re.sub(r"[^a-z0-9]+", "-", p["player_name"].lower()).strip("-")
        if p["player_id"] in SPOTRAC_OVERRIDES:
            sid = SPOTRAC_OVERRIDES[p["player_id"]]
            url = constants.SPOTRAC_PLAYER_URL.format(spotrac_id=sid)
            cache_key = f"spotrac_player_{sid}"
            try:
                html = client.fetch(url, cache_key=cache_key)
            except FetchError as exc:
                failures.append((p["player_id"], str(exc)))
                print(f"  WARN override {p['player_id']} {p['player_name']}: {exc}")
                continue
            direct = OG_URL_RE.search(html)
            name_m = SCHEMA_NAME_RE.search(html)
            pos_m = SCHEMA_JOBTITLE_RE.search(html)
            matched_name = name_m.group(1) if name_m else p["player_name"]
            confidence = "high" if normalize_name(matched_name) == normalize_name(p["player_name"]) else "medium"
            match = {
                "spotrac_id": sid,
                "name": matched_name,
                "position": pos_m.group(1) if pos_m else "",
                "confidence": confidence,
            }
        else:
            url = constants.SPOTRAC_SEARCH_URL.format(query=quote(p["player_name"]))
            cache_key = f"spotrac_search_{slug}"
            try:
                html = client.fetch(url, cache_key=cache_key)
            except FetchError as exc:
                failures.append((p["player_id"], str(exc)))
                print(f"  WARN search {p['player_id']} {p['player_name']}: {exc}")
                continue
            match = match_player(html, p["player_name"], p["pos"])
            if match is None:
                failures.append((p["player_id"], "no match"))
                print(f"  WARN no spotrac match: {p['player_id']} {p['player_name']} ({p['pos']})")
                continue
            if OG_URL_RE.search(html):
                player_cache = (
                    constants.PLAYER_CONTRACTS_CACHE_DIR / f"spotrac_player_{match['spotrac_id']}.html"
                )
                if not player_cache.exists():
                    player_cache.parent.mkdir(parents=True, exist_ok=True)
                    player_cache.write_text(html, encoding="utf-8")
        rows.append(
            {
                "player_id": p["player_id"],
                "player_name": p["player_name"],
                "spotrac_id": match["spotrac_id"],
                "matched_name": match["name"],
                "position": match["position"],
                "confidence": match["confidence"],
            }
        )
        if i % 100 == 0:
            print(f"  ... searched {i}/{len(pool)} players")
    write_csv(
        constants.SPOTRAC_IDS_CSV,
        rows,
        ["player_id", "player_name", "spotrac_id", "matched_name", "position", "confidence"],
    )
    low_conf = [r for r in rows if r["confidence"] in ("low", "medium")]
    print(f"\nSpotrac mapping: {len(rows)}/{len(pool)} mapped. "
          f"Low/medium confidence: {len(low_conf)}")
    if failures:
        print(f"  {len(failures)} search failures: {[f[0] for f in failures[:15]]}")
    return rows


def _deal_year(d: dict) -> int | None:
    if d.get("date"):
        m = re.match(r"([A-Za-z]{3}) (\d{1,2}), (\d{4})", d["date"])
        if m:
            return int(m.group(3))
    return d.get("start_year")


def _career_salary_map() -> dict:
    career = {}
    if not constants.PLAYER_SALARIES_CSV.exists():
        return career
    for r in csv.DictReader(open(constants.PLAYER_SALARIES_CSV, encoding="utf-8")):
        try:
            career[r["player_id"]] = career.get(r["player_id"], 0) + float(r["salary"]) / 1e6
        except (ValueError, KeyError):
            continue
    return career


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _date_tuple(date_str: str, fallback_year: int | None = None) -> tuple | None:
    m = re.match(r"([A-Za-z]{3}) (\d{1,2}), (\d{4})", date_str or "")
    if m:
        return (int(m.group(3)), _MONTHS.get(m.group(1).lower(), 0), int(m.group(2)))
    if fallback_year:
        return (int(fallback_year), 7, 1)
    return None


def _service_years_by_player() -> dict:
    by_pid = defaultdict(dict)
    if not constants.PLAYER_STATS_CSV.exists():
        return by_pid
    for r in csv.DictReader(open(constants.PLAYER_STATS_CSV, encoding="utf-8")):
        m = re.match(r"(\d{4})", r["season"] or "")
        if not m:
            continue
        try:
            by_pid[r["player_id"]][int(m.group(1))] = int(r["years_in_league"])
        except (ValueError, KeyError):
            continue
    return by_pid


def _prior_team_map() -> dict:
    by_pid = defaultdict(dict)
    if not constants.PLAYER_SALARIES_CSV.exists():
        return by_pid
    for r in csv.DictReader(open(constants.PLAYER_SALARIES_CSV, encoding="utf-8")):
        by_pid[r["player_id"]][int(r["season_start"])] = r["team"]
    return by_pid


def _season_salary_map() -> dict:
    by_pid = defaultdict(dict)
    if not constants.PLAYER_SALARIES_CSV.exists():
        return by_pid
    for r in csv.DictReader(open(constants.PLAYER_SALARIES_CSV, encoding="utf-8")):
        try:
            by_pid[r["player_id"]][int(r["season_start"])] = float(r["salary"]) / 1e6
        except (ValueError, KeyError):
            continue
    return by_pid


def _salary_cap_map() -> dict:
    caps = {}
    if not constants.THRESHOLDS_CSV.exists():
        return caps
    for r in csv.DictReader(open(constants.THRESHOLDS_CSV, encoding="utf-8")):
        try:
            caps[int(r["season"][:4])] = int(r["salary_cap"])
        except (ValueError, KeyError):
            continue
    return caps


def _cap_for(caps: dict, year: int) -> float | None:
    """Return the salary cap (in $M) for *year*, or project forward if needed.

    league_thresholds.csv covers seasons through 2025-26 (key 2025).  Extensions
    signed in 2025 with start_year=2026 need a projected cap.  We compound
    MAX_CAP_GROWTH for each missing year beyond the last known cap.
    """
    if year is None:
        return None
    if year in caps:
        return caps[year] / 1e6

    last_known = max(caps) if caps else None
    if last_known is None or year < last_known:
        return None

    cap = caps[last_known]
    for y in range(last_known + 1, year + 1):
        cap = int(cap * (1 + constants.MAX_CAP_GROWTH))
    return cap / 1e6


def _fa_status(deal_date, deal_year, events) -> str:
    target_d = _as_date(_date_tuple(deal_date, deal_year))
    if target_d is None:
        return ""
    best = None
    for ev in events:
        if ev["kind"] not in ("qo", "fa_status"):
            continue
        et = _as_date(_date_tuple(ev["date"]))
        if et is None or et > target_d or (target_d - et).days > 200:
            continue
        if best is None or et > best[0]:
            best = (et, ev["text"])
    if best is None:
        return ""
    t = best[1].lower()
    if "unrestricted" in t or "withdrew" in t:
        return "UFA"
    if "restricted" in t:
        return "RFA"
    return ""


def _as_date(ymd) -> date | None:
    if not ymd:
        return None
    try:
        return date(ymd[0], ymd[1] or 1, ymd[2] or 1)
    except ValueError:
        return None


def _draft_year(events) -> int | None:
    years = []
    for ev in events:
        if ev["kind"] != "draft":
            continue
        ymd = _date_tuple(ev["date"])
        if ymd:
            years.append(ymd[0])
    return min(years) if years else None


def _service_at(yil: dict, draft_year: int | None, year: int | None) -> int | None:
    if year is None:
        return None
    if year in yil:
        return yil[year]
    past = sorted(k for k in yil if k <= year)
    if past:
        return yil[past[-1]] + (year - past[-1])
    if draft_year:
        return year - draft_year + 1
    return None


def _signed_via(deal_type: str, text: str) -> str:
    t = (text or "").lower()
    if "renegotiat" in t:
        return "renegotiation"
    if "rest-of-season" in t or "rest of season" in t:
        return "rest_of_season"
    if "sign-and-trade" in t or "extend-and-trade" in t:
        return "sign_and_trade"
    if "extension" in t or deal_type == "extension":
        return "extension"
    if "offer sheet" in t:
        return "offer_sheet"
    if "qualifying offer" in t:
        return "rfa_match"
    if deal_type == "rookie-scale":
        return "rookie_scale"
    if deal_type == "two-way":
        return "two_way"
    if deal_type == "minimum":
        return "minimum"
    return "free_agency"


def step_deal_features(ids: list[dict]) -> list[dict]:
    if not constants.PLAYER_DEALS_CSV.exists():
        print("No player_deals.csv; run deals step first.")
        return []
    deals = list(csv.DictReader(open(constants.PLAYER_DEALS_CSV, encoding="utf-8")))
    by_pid = defaultdict(list)
    for d in deals:
        by_pid[d["player_id"]].append(d)
    service = _service_years_by_player()
    prior_teams = _prior_team_map()
    season_sals = _season_salary_map()
    caps = _salary_cap_map()
    id_by_pid = {r["player_id"]: r["spotrac_id"] for r in ids}
    markets = _team_market_map()

    rows = []
    for pid, player_deals in sorted(by_pid.items()):
        sid = id_by_pid.get(pid)
        events = []
        if sid is not None:
            cached = constants.PLAYER_CONTRACTS_CACHE_DIR / f"spotrac_player_{sid}.html"
            if cached.exists():
                try:
                    events = parse_player_page(
                        cached.read_text(encoding="utf-8"), int(sid)
                    )["events"]
                except Exception:
                    events = []
        yil = service.get(pid, {})
        sals = prior_teams.get(pid, {})
        draft_year = _draft_year(events)
        for d in sorted(player_deals, key=lambda x: _date_tuple(x["deal_date"], _safe_year(x)) or (0, 0, 0)):
            year = _safe_year(d)
            team = d["team"] or ""
            text = d["raw"] or ""
            deal_type = d["deal_type"] or ""
            via = _signed_via(deal_type, text)
            is_fa_deal = via not in ("rookie_scale", "two_way", "extension", "renegotiation")
            fa = _fa_status(d["deal_date"], year, events)
            if not is_fa_deal:
                fa = ""
            if is_fa_deal and not fa and year is not None:
                svc_prior = _service_at(yil, draft_year, year - 1)
                if svc_prior is not None:
                    fa = "" if svc_prior == 0 else ("RFA" if svc_prior <= 4 else "UFA")
            t = text.lower()
            # Blurb-derived flags: Spotrac's transaction text is the only source
            # for these, so they under-count (a max extension whose blurb omits
            # "designated" reads as supermax=0). Treated as noisy, not exact.
            supermax = 1 if ("super max" in t or "supermax" in t or "designated" in t) else 0
            signed_max = 1 if ("maximum" in t or "max extension" in t or "super max" in t or "supermax" in t) else 0
            player_opt = 1 if "player option" in t else 0
            prior = None
            if sals:
                prior = sals.get(year - 1) or sals.get(year)
            if not prior and events:
                evt = _date_tuple(d["deal_date"], year)
                for ev in sorted(events, key=lambda x: _date_tuple(x["date"]) or (0, 0, 0), reverse=True):
                    if ev["kind"] not in ("trade", "sign", "waive"):
                        continue
                    et = _date_tuple(ev["date"])
                    if et is not None and evt is not None and et <= evt:
                        prior = ev["team"]
                        break
            if prior and team:
                incumbent = 1 if prior == team else 0
            else:
                incumbent = ""
            d_t = _date_tuple(d["deal_date"], year)
            out_options = 0
            if d_t is not None:
                for ev in events:
                    if ev["kind"] != "option":
                        continue
                    et = _date_tuple(ev["date"])
                    if et is not None and et > d_t:
                        out_options += 1
            try:
                total_m = float(d["total_value_m"]) if d["total_value_m"] not in ("", None) else None
            except (TypeError, ValueError):
                total_m = None
            try:
                n_years = int(d["years"]) if d["years"] not in ("", None) else None
            except (TypeError, ValueError):
                n_years = None
            # Extension cap-year rule (year+1):
            #
            # NBA seasons span two calendar years (e.g. 2024-25 uses the 2024
            # cap).  An extension signed during a season does not kick in until
            # the *next* season — the current contract still covers the rest of
            # the ongoing season.  So the extension's salary is paid under the
            # next season's cap, not the current one.
            #
            # Example: an extension signed Nov 2024 (during the 2024-25 season)
            # with 1 year remaining kicks in for 2025-26 → cap year = 2025.
            #
            # This is correct for the majority of extensions, which are signed
            # Jul–Dec (offseason / early season) with 1 year remaining.  A
            # small minority signed Jan–Jun would start the same year's season
            # (year+0), but year+1 is the better approximation for the overall
            # distribution of extension signing dates.
            start_year = (year + 1) if via == "extension" else year
            cap_m = _cap_for(caps, start_year)
            aav_m = total_m / n_years if (total_m is not None and n_years) else None
            aav_share = aav_m / cap_m if (aav_m is not None and cap_m) else None
            end_year = (start_year + n_years - 1) if (year is not None and n_years) else None
            completed = 1 if (end_year is not None and end_year < 2026) else (0 if end_year is not None else None)
            market = 1 if (via in ("free_agency", "extension", "offer_sheet", "rfa_match", "sign_and_trade")
                           and n_years is not None and n_years >= 2) else 0

            # Service years COMPLETED before the contract's first season.
            # `years_in_league` counts the season itself, hence the -1.
            svc_at_start = _service_at(yil, draft_year, start_year)
            svc_before_start = None if svc_at_start is None else max(0, svc_at_start - 1)
            tier = constants.max_tier_pct(svc_before_start, supermax=bool(supermax))
            tier_aav = constants.max_tier_aav_pct(tier, n_years)
            over_tier = (1 if (aav_share is not None and tier_aav is not None
                               and aav_share > tier_aav + OVER_TIER_TOL) else 0)

            signing_season_salary = season_sals.get(pid, {}).get(year)
            tm = markets.get(team, {})
            pm = markets.get(prior or "", {})
            rows.append(
                {
                    "player_id": pid,
                    "player_name": d["player_name"],
                    "spotrac_id": sid or "",
                    "deal_date": d["deal_date"],
                    "deal_year": year or "",
                    "team": team,
                    "total_value_m": d["total_value_m"],
                    "deal_type": deal_type,
                    "verified": d["verified"],
                    "fa_status": fa,
                    "max_tier_pct": "" if tier is None else tier,
                    "max_tier_aav_pct": "" if tier_aav is None else round(tier_aav, 6),
                    "aav_over_tier": over_tier,
                    "signed_max": signed_max,
                    "supermax": supermax,
                    "signed_via": via,
                    "prior_team": prior or "",
                    "incumbent": incumbent,
                    "player_option": player_opt,
                    "outstanding_options": out_options,
                    "contract_start_year": start_year if year is not None else "",
                    "salary_cap_m": cap_m,
                    "aav_m": round(aav_m, 3) if aav_m is not None else "",
                    "aav_cap_share": round(aav_share, 6) if aav_share is not None else "",
                    "log_aav_cap_share": round(math.log(aav_share), 6) if aav_share else "",
                    "end_year": end_year,
                    "completed": completed,
                    "years_remaining": "" if end_year is None else (end_year - 2025 if end_year >= 2026 else 0),
                    "market": market,
                    "signing_season_salary_m": signing_season_salary,
                    "team_dma_rank": tm.get("dma_rank", ""),
                    "team_tv_homes_m": tm.get("tv_homes_m", ""),
                    "team_metro_pop_m": tm.get("metro_pop_m", ""),
                    "team_market_size": tm.get("market_size", ""),
                    "team_big_market": tm.get("big_market", ""),
                    "prior_team_dma_rank": pm.get("dma_rank", ""),
                    "prior_team_tv_homes_m": pm.get("tv_homes_m", ""),
                    "prior_team_metro_pop_m": pm.get("metro_pop_m", ""),
                    "prior_team_market_size": pm.get("market_size", ""),
                    "prior_team_big_market": pm.get("big_market", ""),
                }
            )
    write_csv(
        constants.PLAYER_DEAL_FEATURES_CSV,
        rows,
        ["player_id", "player_name", "spotrac_id", "deal_date", "deal_year", "team",
         "total_value_m", "deal_type", "verified", "fa_status", "max_tier_pct",
         "max_tier_aav_pct", "aav_over_tier",
         "signed_max", "supermax", "signed_via", "prior_team", "incumbent",
         "player_option", "team_option", "outstanding_options",
         "contract_start_year", "salary_cap_m", "aav_m", "aav_cap_share", "log_aav_cap_share",
         "end_year", "completed", "years_remaining", "market", "year1_salary",
         "signing_season_salary_m",
         "team_dma_rank", "team_tv_homes_m", "team_metro_pop_m", "team_market_size", "team_big_market",
         "prior_team_dma_rank", "prior_team_tv_homes_m", "prior_team_metro_pop_m",
         "prior_team_market_size", "prior_team_big_market"],
    )
    counter = Counter(r["fa_status"] for r in rows)
    print(f"\nFeatures written: {len(rows)} rows -> {constants.PLAYER_DEAL_FEATURES_CSV}")
    print(f"fa_status: {dict(counter)}")
    via = Counter(r["signed_via"] for r in rows)
    print(f"signed_via: {dict(via.most_common(12))}")
    inc = Counter(r["incumbent"] for r in rows)
    print(f"incumbent: {dict(inc)}")
    tier = Counter(r["max_tier_pct"] for r in rows)
    print(f"max_tier_pct: {dict(tier)}")
    print(f"completed: {dict(Counter(r['completed'] for r in rows))}")
    print(f"market: {dict(Counter(r['market'] for r in rows))}")
    print(f"aav_cap_share present: {sum(1 for r in rows if r['aav_cap_share'] != '')} "
          f"({sum(1 for r in rows if r['log_aav_cap_share'] != '')} with log)")
    return rows


def _team_market_map() -> dict:
    mkt = {}
    if not constants.TEAM_MARKET_CSV.exists():
        print("No team_market.csv; market columns will be blank.")
        return mkt
    for r in csv.DictReader(open(constants.TEAM_MARKET_CSV, encoding="utf-8")):
        mkt[r["team"]] = {
            "dma_rank": int(r["dma_rank"]) if r["dma_rank"] not in ("", None) else "",
            "tv_homes_m": float(r["tv_homes_m"]) if r["tv_homes_m"] not in ("", None) else "",
            "metro_pop_m": float(r["metro_pop_m"]) if r["metro_pop_m"] not in ("", None) else "",
            "market_size": r["market_size"],
            "big_market": int(r["big_market"]) if r["big_market"] not in ("", None) else "",
        }
    return mkt


def _safe_year(d: dict) -> int | None:
    try:
        return int(d["deal_year"])
    except (KeyError, TypeError, ValueError):
        return None


def step_deals(ids: list[dict], pool_by_id: dict, client: FetchClient) -> list[dict]:
    career_salary = _career_salary_map()
    deals_rows = []
    verified = {"ok": 0, "unverified": 0}
    mismatches = []
    no_page = []
    no_deals = []
    for i, row in enumerate(ids, start=1):
        p = pool_by_id[row["player_id"]]
        sid = row["spotrac_id"]
        url = constants.SPOTRAC_PLAYER_URL.format(spotrac_id=sid)
        cache_key = f"spotrac_player_{sid}"
        cached_path = constants.PLAYER_CONTRACTS_CACHE_DIR / f"{cache_key}.html"
        try:
            if cached_path.exists():
                html = cached_path.read_text(encoding="utf-8")
            else:
                html = client.fetch(url, cache_key=cache_key)
        except FetchError as exc:
            no_page.append(row["player_id"])
            print(f"  WARN page {row['player_id']}: {exc}")
            continue
        try:
            page = parse_player_page(html, sid)
        except Exception as exc:
            no_page.append(row["player_id"])
            print(f"  WARN parse {row['player_id']}: {exc}")
            continue

        deals = [d for d in page["transactions"] if d["total_value_m"] is not None]
        tx_value = sum(d["total_value_m"] for d in deals)
        career = career_salary.get(row["player_id"], 0)
        if career >= 15 and tx_value < 0.35 * career:
            covered = {(d["team"], _deal_year(d)) for d in deals}
            for b in page["contract_blocks"]:
                if b["total_value_m"] < 5:
                    continue
                if (b["team"], b["start_year"]) in covered:
                    continue
                deals.append(b)
        if not deals and page["current_contract"] is not None:
            cc = page["current_contract"]
            if cc["total_value"]:
                deals = [
                {
                    "date": "",
                    "years": cc["years"],
                    "total_value_m": cc["total_value"] / 1e6,
                    "deal_type": cc["deal_type"],
                    "team": constants.TEAM_ABBREV.get(cc["team"], ""),
                    "start_year": cc["start_year"],
                    "text": "current contract",
                }
            ]

        deal_teams = {d["team"] for d in deals if d["team"]}
        overlap = bool(deal_teams & p["teams"])
        n_bbr = normalize_for_compare(p["player_name"])
        n_spr = normalize_for_compare(page["name"])
        name_ok = bool(n_bbr) and (n_bbr == n_spr or n_bbr in n_spr or n_spr in n_bbr)
        is_verified = 1 if (name_ok or overlap) else 0
        if is_verified:
            verified["ok"] += 1
        else:
            verified["unverified"] += 1
            mismatches.append(
                (row["player_id"], p["player_name"], page["name"], row["matched_name"],
                 sorted(deal_teams)[:6], sorted(p["teams"])[:6])
            )

        if not deals:
            no_deals.append(row["player_id"])
        for d in deals:
            deals_rows.append(
                {
                    "player_id": row["player_id"],
                    "player_name": p["player_name"],
                    "spotrac_id": sid,
                    "deal_date": d["date"],
                    "deal_year": _deal_year(d) or "",
                    "team": d["team"],
                    "years": d["years"] if d["years"] is not None else "",
                    "total_value_m": d["total_value_m"],
                    "deal_type": d["deal_type"],
                    "verified": is_verified,
                    "raw": d.get("text") or d.get("raw") or "contract block",
                }
            )
        if i % 100 == 0:
            print(f"  ... fetched {i}/{len(ids)} player pages")
    write_csv(
        constants.PLAYER_DEALS_CSV,
        deals_rows,
        ["player_id", "player_name", "spotrac_id", "deal_date", "deal_year",
         "team", "years", "total_value_m", "deal_type", "verified", "raw"],
    )
    print(f"\nDeals extracted: {len(deals_rows)} from {len(ids)} players.")
    print(f"Verification: {verified}")
    if no_page:
        print(f"  {len(no_page)} player pages failed: {no_page[:10]}")
    if no_deals:
        print(f"  {len(no_deals)} players with no signed-deal transactions: {no_deals[:10]}")
    if mismatches:
        print(f"\nPotential mismatches ({len(mismatches)}):")
        for pid, bname, sname, mname, steams, bteams in mismatches[:15]:
            print(f"  {pid} {bname}: BBR teams {bteams} vs spotrac '{sname}' teams {steams} (matched '{mname}')")
    return deals_rows


def normalize_for_compare(name: str) -> str:
    if not name:
        return ""
    import unicodedata

    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace(".", "")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return s.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build NBA player contract data.")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the HTML cache")
    parser.add_argument(
        "--skip-salaries", action="store_true", help="Skip the BBR salary step"
    )
    parser.add_argument(
        "--skip-search", action="store_true", help="Skip Spotrac ID mapping (reuse spotrac_ids.csv)"
    )
    parser.add_argument(
        "--skip-deals", action="store_true", help="Skip Spotrac deal fetching"
    )
    parser.add_argument(
        "--skip-features", action="store_true", help="Skip deal-feature enrichment"
    )
    args = parser.parse_args()

    pool = load_player_pool()
    print(f"Player pool (>= {constants.MIN_CAREER_MINUTES} career min): {len(pool)} players")

    if not args.skip_salaries:
        step_salaries(pool, args.no_cache)
    else:
        print("Skipping salary step.")

    client = FetchClient(
        use_cache=not args.no_cache,
        cache_dir=constants.PLAYER_CONTRACTS_CACHE_DIR,
        delay=15.0,
        max_requests_per_window=None,
    )

    if not args.skip_search:
        ids = step_spotrac_ids(pool, client, args.no_cache)
    else:
        if not constants.SPOTRAC_IDS_CSV.exists():
            print("No spotrac_ids.csv found; run without --skip-search first.")
            return 1
        ids = list(csv.DictReader(open(constants.SPOTRAC_IDS_CSV, encoding="utf-8")))
        print(f"Reusing {len(ids)} mappings from spotrac_ids.csv")

    if not args.skip_deals:
        pool_by_id = {p["player_id"]: p for p in pool}
        step_deals(ids, pool_by_id, client)
    else:
        print("Skipping deal step.")

    if not args.skip_features:
        step_deal_features(ids)
    else:
        print("Skipping feature step.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
