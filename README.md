# nba-contracts

Predict NBA contract value (average annual value as a share of the signing-season
salary cap) from prior-season production, physicals, deal terms, and team/market
context. The project runs a leakage-controlled pipeline: baselines, a regularized
linear model with a documented two-layer feature selection, tree ensembles
tuned by walk-forward CV, ceiling-aware models (Tobit / Heckman), and quantile-
regression prediction intervals. `REPORT.ipynb` is the final summary; it also
answers two context questions — whether market size drives pay and whether
players take below-market deals to join contending teams — using coefficient
paths across the linear, ceiling-aware, and tree models.

## Directory layout

    consolidation/       build_dataset.py - assembles data/model/features.csv
    scrapers/            spotrac/BRef scrapers and normalizers (raw source data)
    data/
      raw/               scraped source data
      model/             modeled features and all pipeline artifacts
    notebooks/
      EDA.ipynb          exploratory analysis
      PREP.ipynb         encoding, position dummies, chronological split
      MODEL_01_baseline.ipynb
      MODEL_02_linear.ipynb
      MODEL_03_ensemble.ipynb
      MODEL_04_advanced.ipynb
      REPORT.ipynb       final report: comparison, error analysis, conclusions
      metrics.py         shared rmse/mae/r2/evaluate used by all notebooks
    requirements.txt

## Pipeline

1. `consolidation/build_dataset.py` writes `data/model/features.csv` (1,214
   candidate rows; position and prior-season box-score stats included where
   available, documented in `data/model/features.md`).
2. `PREP.ipynb` builds `prep.csv` (1,180 modeled deals, 2015-2025), encodes
   categoricals, and splits chronologically: train = years <= 2021 (n=783),
   val = 2022-23 (n=216, headline), test = 2024-25 (n=181, hold-out, never
   tuned on).
3. `MODEL_01..04` fit and register models into `data/model/results.csv`.
4. `REPORT.ipynb` reads the saved artifacts and renders the final report.

Leakage controls: player stats are prior-season, team context is signing season
only, hyperparameters are selected by expanding-window walk-forward CV inside the
train window, and val/test never influence any fit.

## Models

- Baselines: global median; segment medians by experience and prior minutes.
- Linear: ElasticNet on standardized features. Controls always stay in; the 39
  candidate stats are screened by two deterministic layers (redundancy,
  weak target correlation) with the outcome recorded in
  `data/model/linear_features.json`. The chosen interpretable model uses 35
  controls + 24 chosen stats. Position enters as a structural control.
- Ensembles: Random Forest and Gradient Boosting, default and walk-forward-tuned,
  on the canonical set.
- Ceiling-aware: Tobit MLE and two-stage Heckman for the right-censored max-tier
  ceiling (diagnostics in `data/model/ceiling_metrics.json`).
- Intervals: quantile regression (tau in {0.10, 0.50, 0.90}) versus a naive
  gb-residual interval (metrics in `data/model/interval_metrics.json`).

## Key results (val)

- Best model: `rf_tuned` log-RMSE 0.410, R2 0.845 (test 0.396, R2 0.861).
- Chosen interpretable model: `linear_interpretable` log-RMSE 0.440; the
  interpretability cost versus the all-stats ceiling (0.421) is about 0.019.
- Position x stat interactions add nothing (delta ~0); raw box-score stats are
  noise beyond the position-normalized composites (PER/BPM/VORP/WS).
- Market size does not drive pay once player/team quality is controlled (ElasticNet
  shrinks all market features to 0; OLS/Tobit/Heckman coefficients are individually
  non-zero but unstable due to multicollinearity; flat tree partial dependence).
- The contender discount is real but modest: `team_nrtg` coefficient ~ -0.07
  (chosen ElasticNet) and -0.13 to -0.14 (OLS/Tobit/Heckman); bigger for stars
  (interaction ~ -0.03), identical for re-signings vs movers, and ~0.4% of cap
  per contender deal (details in `data/model/contender_metrics.json`).
- Quantile [q10, q90] intervals reach 82.9% coverage on val, 75.1% on test.

## Reproducibility

Python 3.12 recommended. Create a virtual environment and install dependencies:

    python -m venv .venv
    .venv/bin/pip install -r requirements.txt

Run the notebooks in order from the `notebooks/` directory so that
`import metrics` resolves:

    ../.venv/bin/jupyter nbconvert --to notebook --execute --inplace <NB>.ipynb

Order: PREP, MODEL_01_baseline, MODEL_02_linear, MODEL_03_ensemble,
MODEL_04_advanced, REPORT. `consolidation/build_dataset.py` should be run first
if the raw scrapes change.

## Artifacts (data/model/)

    features.csv            modeled features, one row per candidate deal
    prep.csv                encoded, split-ready modeling frame
    prep_columns.json       column manifest for prep.csv
    linear_features.json    chosen canonical set + every drop and its reason
    results.csv             long-format metrics, one row per model x split
    predictions_*.csv       per-model predictions for every row
    interval_metrics.json   interval coverage / width / pinball
    ceiling_metrics.json    Tobit, Heckman, market + team-quality coefficients,
                            quantile crossings
    contender_metrics.json  Q2 coefficient paths + per-deal discount tables
    features.md             feature-by-feature documentation and timing rules

## Limitations

The max-tier ceiling is thin (34 cap-bound deals within a 5% band), the Heckman
correction has no clean exclusion restriction and is diagnostic only, the test
set is small, and agent/leverage factors are not modeled.
