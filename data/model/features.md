# Feature glossary — `data/model/features.csv`

One row per market deal (free agency / extension / offer sheet / RFA match / sign-and-trade, years ≥ 2, valid AAV target). All feature lookups are relative to `deal_year` and use only information known at signing.

## Leakage & timing
- Every time-varying feature is joined from the **prior season** — the season labeled `f"{deal_year - 1}-{str(deal_year)[-2:]}"` (e.g., a deal signed in 2019 uses the 2018-19 season).
- The predicted contract's money starts in `deal_year`'s season at the earliest (`deal_year + 1` for extensions), so it can never appear in the prior-season joins.
- **Team cap columns** (`team_cap_space_m`, `team_active_payroll_m`, `team_dead_cap_m`, and the `prior_*` variants) are prior-season ledgers only. Verified example: Kyrie Irving's July 2019 Brooklyn deal joined Brooklyn's 2018-19 active payroll ($77.8M, pre-signing), not 2019-20 ($94.8M, which includes his salary).
- `team_active_payroll_m` includes the player's own prior salary from an expiring contract when re-signing — legitimate information, but it is naturally correlated with the target.
- Prior-season `team_cap_space_m` is not the room available at signing; teams create space between seasons (renounces, trades, waives). Treat it as a weak proxy, not a leak.
- Career / rolling aggregates (`career_*`, `recent3_*`) include only seasons up to and including the prior season.

## Identifiers
- `player_id` — Basketball-Reference style player key (e.g., `curryst01`).
- `player_name` — Display name.
- `deal_date` — Date the contract was signed.
- `deal_year` — Year of signing; all feature lookups are relative to this.
- `team` — Team the player signed with (canonical abbreviation).

## Contract / outcome
- `years` — Contract length in seasons.
- `signed_via` — How the deal happened (free_agency, extension, offer_sheet, rfa_match, sign_and_trade).
- `deal_type` — Spotrac deal type string.
- `fa_status` — Restricted (RFA) vs unrestricted (UFA) free agency status; blank for extensions.
- `aav_m` — Average annual value in $M (total / years).
- `salary_cap_m` — League salary cap in $M for the signing season.
- `aav_cap_share` — **Target**: AAV as a fraction of the cap.
- `log_aav_cap_share` — Natural log of the target (what we regress on).

## Player quality — prior season (deal year − 1)
- `has_prior_stats` — 1 if the player logged any prior-season games, else 0.
- `pos` — Position at signing (PG / SG / SF / PF / C). Taken from the prior season's
  stats row; if the player had no prior-season games, the career-dominant position (mode
  over played seasons ≤ prior); blank if they never played before signing.
- `prior_games` — Games played in the prior season.
- `prior_ppg` — Points per game, prior season.
- `prior_mpg` — Minutes per game, prior season.
- `prior_per` — Player Efficiency Rating, prior season.
- `prior_bpm` — Box Plus/Minus, prior season.
- `prior_vorp` — Value Over Replacement Player, prior season.
- `prior_ws` — Win Shares, prior season.
- `prior_ws48` — Win Shares per 48 minutes, prior season.
- `prior_usg_pct` — Usage rate %, prior season.
- `prior_ts_pct` — True shooting %, prior season.
- `prior_ast` — Assists per game, prior season.
- `prior_trb` — Total rebounds per game, prior season.
- `prior_blk` — Blocks per game, prior season.
- `prior_stl` — Steals per game, prior season.
- `prior_tov` — Turnovers per game, prior season.

## Player quality — career to date (all seasons ≤ prior)
- `career_seasons` — Number of NBA seasons played before signing.
- `career_games` — Career games played.
- `career_ppg` — Career points per game (games-weighted).
- `career_mpg` — Career minutes per game.
- `career_vorp` — Career cumulative VORP.
- `career_ws` — Career cumulative Win Shares.
- `recent3_vorp` — Sum of VORP over the last 3 seasons.
- `recent3_ws` — Sum of Win Shares over the last 3 seasons.

## Physical / draft
- `age_at_signing` — Player age in years at signing.
- `height_inches` — Height in inches.
- `weight_lb` — Weight in pounds.
- `years_pro` — Years of pro experience (deal year − debut year, floored at 0 for signings before the player's NBA debut).
- `draft_year` — Year drafted; blank if no draft data.

## Contract terms (context features)
- `incumbent` — 1 if the prior team is the signing team, 0 if a new team.
- `player_option` — 1 if the contract includes a player option.
- `team_option` — 1 if the contract includes a team option.
- `max_tier_pct` — Max-salary tier the player is eligible for (0.25 / 0.30 / 0.35).
- `supermax` — 1 if the contract is a designated / supermax deal.
- `outstanding_options` — Count of future options on the deal.

## Signing-team context (prior season)
- `team_srs` — Team Simple Rating System, prior season.
- `team_nrtg` — Team net rating, prior season.
- `team_mov` — Team margin of victory, prior season.
- `team_wins` — Team win total, prior season.
- `team_made_playoffs` — 1 if the team made the playoffs, prior season.
- `team_champion` — 1 if the team won the championship, prior season.
- `team_cap_space_m` — Team cap space in $M, prior season.
- `team_active_payroll_m` — Team active payroll in $M, prior season.
- `team_dead_cap_m` — Team dead cap in $M, prior season.
- `team_players_active` — Number of players on the roster, prior season.

## Prior-team context (prior season)
- `prior_team` — Player's team before signing (canonical abbreviation).
- `prior_srs` — Prior team's Simple Rating System.
- `prior_nrtg` — Prior team's net rating.
- `prior_mov` — Prior team's margin of victory.
- `prior_wins` — Prior team's win total.
- `prior_made_playoffs` — 1 if the prior team made the playoffs.
- `prior_champion` — 1 if the prior team won the championship.
- `prior_cap_space_m` — Prior team's cap space in $M.
- `prior_active_payroll_m` — Prior team's active payroll in $M.
- `prior_dead_cap_m` — Prior team's dead cap in $M.
- `prior_players_active` — Prior team's number of active players.
- `prior_team_big_market` — 1 if the prior team is in a top-10 DMA.
- `prior_team_market_size` — Prior team's market bucket (Large / Medium / Small).
- `prior_team_metro_pop_m` — Prior team's metro population in millions.

## Market (signing team)
- `team_big_market` — 1 if the signing team is in a top-10 DMA.
- `team_market_size` — Signing team's market bucket (Large / Medium / Small).
- `team_metro_pop_m` — Signing team's metro population in millions.
- `team_dma_rank` — Nielsen DMA rank of the signing team's market; blank for Toronto.
- `team_tv_homes_m` — TV households in millions for the signing team's DMA.

## League
- `cba_regime` — Collective-bargaining era (pre_2017 / cba_2017 / cba_2023).
