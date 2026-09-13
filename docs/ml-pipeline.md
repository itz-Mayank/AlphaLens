# ML Pipeline

## Status

Phase 5 built research-data ingestion, validation, feature engineering, target design, temporal
dataset construction, naive baselines, XGBoost, LSTM, GRU, evaluation (classification, regression,
financial), and a lightweight model registry. Phase 6 added: a serving layer
(`ml.inference.serving`) that turns raw price history into a live forecast using the exact training
feature pipeline; SHAP explainability (`ml.explainability`) for the XGBoost models; a portfolio
backtest engine (`ml.backtest`); and the backend wiring that exposes all of this over HTTP
(`GET /stocks/{ticker}/forecast`, `GET /stocks/{ticker}/forecast/explanation`,
`POST /research/backtest` — see [api.md](api.md)). Phase 7 added financial sentiment
(`ml.nlp.sentiment`, FinBERT) and the backend's news/entity-mapping/sentiment-aggregation pipeline
(`GET /stocks/{ticker}/news`, `/sentiment`, `/sentiment/history`). `ml/` remains standalone — no
FastAPI dependency, and `backend/` imports from `ml.inference`/`ml.explainability`/`ml.backtest`/
`ml.nlp` only, never `ml.pipelines`/`ml.training` (ADR-001) — verified by a repository-wide `grep`
audit, not just by convention. Phase 8 added a grounded LLM research agent on top of this pipeline
(`app/agent/`) — see "Research agent (Phase 8)" below; it is a `backend/` concern, not a new `ml/`
capability, and this document's own contract is otherwise unchanged.

This document is the ML data contract and methodology reference. It should be enough for a senior
ML engineer to understand exactly what the pipeline does and why, without reading every source
file.

## The three data environments — never blurred

| Environment  | Enum value                    | Used for                                        | Example                                |
|--------------|--------------------------------|--------------------------------------------------|-----------------------------------------|
| Demo         | `DataEnvironment.DEMO`         | Backend UI demo mode (Phase 3/4)                 | `DemoMarketDataProvider` (synthetic)    |
| Research     | `DataEnvironment.RESEARCH`     | Model training/evaluation (Phase 5)              | `SampleSP500ResearchProvider` (real)    |
| Production   | `DataEnvironment.PRODUCTION`   | Not yet built — a future live/paid vendor feed   | —                                       |

`ml.data.contracts.DatasetProvenance.environment` is stamped on every dataset a pipeline touches.
**The rule this enforces:** a model trained on `DEMO` data must never have its results reported as
if they described real market behavior, and a model trained on `RESEARCH` data must never be
represented as production-grade — it is real historical data, but a small, fixed, non-split-adjusted
sample (see "Known limitations"). No code path in `ml/` silently defaults to demo data for training;
`ml.pipelines.train_pipeline.run_experiment` defaults to `SampleSP500ResearchProvider` and requires
an explicit `provider=` override to use anything else (as the test suite's synthetic-data provider
does, itself stamped `DEMO` for honesty about what it is — see
`tests/integration/test_train_pipeline_integration.py`).

## Research dataset

- **Source:** `plotly/datasets:all_stocks_5yr.csv` (MIT license), a static historical OHLCV
  snapshot. Extracted once into `ml/ml/data/sample_data/research_sample_sp500.csv`; full
  extraction methodology, license text, and known caveats are in
  `ml/ml/data/sample_data/PROVENANCE.md`.
- **Coverage:** 11 tickers (AAPL, MSFT, AMZN, GOOGL, JNJ, JPM, FB, NVDA, DIS, KO, PG),
  2013-02-08 to 2018-02-07, 1,259 trading days each, 13,850 rows total.
- **Why not scrape a live source:** Stooq requires solving a JavaScript proof-of-work challenge to
  script (not attempted — that is exactly the "unreliable scraping" this project's rules forbid);
  Yahoo Finance returned HTTP 429 (rate-limited) on every attempt; FRED has index-level data only,
  not per-ticker OHLCV. A permissively-licensed, real, statically-hosted CSV was the compliant
  option available without a paid vendor key.
- **Why this is not "production data":** it is a fixed snapshot (not a live feed), not
  split/dividend-adjusted, and covers only 11 large, liquid, still-listed names (survivorship
  bias — no delisted/failed companies are represented). See "Known limitations."

## Data validation (`ml/ml/data/validation.py`)

Runs before any feature is computed. Checks: required columns present, duplicate `(ticker, ts)`
rows, chronological ordering, `low <= open,close <= high`, positive prices, non-negative volume,
missing values, missing trading days, suspicious single-day jumps (>50%, informational), and
insufficient history (< `min_history_days`, informational). `is_clean` is `False` if any
*non-informational* check fails — `run_experiment` raises rather than training on data that fails
validation. `validate()` never repairs anything; `clean()` is the one, narrow, explicit
transformation allowed (drop exact `(ticker, ts)` duplicates, re-sort) — never a silent numeric
"fix" of a suspicious value.

## The formal data contract: `X_t` and `Y_t`

- **`X_t`** — the feature vector computed from OHLCV rows *up to and including* trading day `t`.
  Every feature in `ml/features/*.py` is a trailing (never centered) rolling/EWM calculation over
  `close`/`high`/`low`/`volume`/`ts` — verified directly by
  `tests/unit/test_features.py::test_no_lookahead_*`, which builds features on the full series and
  on a series truncated after `t`, and asserts the two are byte-identical up to `t`. No feature is
  ever computed with `center=True`, and no shift used anywhere in `ml/features/` is negative
  (`tests/unit/test_targets.py::test_targets_module_only_uses_negative_shift_for_the_future_target`
  asserts this by inspecting the source of every feature module — the *only* negative shift
  permitted anywhere in the package is inside `ml.targets.targets.future_return`).
- **`Y_t`** — the outcome after `t`: `future_return_t = close_{t+h} / close_t - 1`, where
  `h = horizon_days` (5 by default). A prediction "made using `X_t`" is a decision at the close of
  day `t`; the position it implies is only ever entered starting the next trading day (see
  "Financial evaluation methodology").
- **Guarantee:** no feature may read a value with a timestamp after `t`, and `Y_t` may only be
  computed from timestamps strictly after `t`. Verified structurally (source-inspection test above)
  and empirically (truncation test above), not just by code review.
- **Per-ticker isolation:** every feature and target is computed *within* one ticker's rows only —
  a rolling window, an EWM state, or a `shift()` never crosses a ticker boundary. Verified by
  `tests/unit/test_features.py::test_rolling_features_do_not_cross_ticker_boundaries` and
  `test_targets.py::test_future_return_does_not_cross_ticker_boundaries`.
- **Missing data:** warm-up rows (before a feature's window is full) and end-of-series rows (no
  known future close for `Y_t`) are `NaN`, dropped by dataset builders (`ml/datasets/`) — never
  imputed, zero-filled, or otherwise fabricated.
- **Versioning:** `FEATURE_SET_VERSION = "fs_v1"` (`ml.features.pipeline`) and
  `RESEARCH_DATASET_VERSION = "research_sample_sp500_v1"` (`ml.data.contracts`) are recorded on
  every registered model (`ModelRecord.feature_version` / `.dataset_version`) — a model's exact
  training data and feature definitions are always reconstructable from its registry entry.

## Feature set (`fs_v1`, 27 features, `ml.features.pipeline.FEATURE_COLUMNS`)

| Category   | Features                                                                                   |
|------------|----------------------------------------------------------------------------------------------|
| Price      | `return_1d`, `log_return_1d`, `return_5d`, `return_10d`, `momentum_10d`                     |
| Trend      | `sma_10`, `sma_20`, `sma_50`, `price_to_sma_20`, `ema_12`, `ema_26`, `price_to_ema_12`       |
| Momentum   | `rsi_14`, `macd_line`, `macd_signal`, `macd_histogram`, `roc_10`                             |
| Volatility | `volatility_10d`, `volatility_20d`, `atr_14`, `bollinger_percent_b`                          |
| Volume     | `volume_change_1d`, `rolling_volume_mean_20`, `relative_volume_20`                           |
| Calendar   | `day_of_week`, `month`, `trading_day_position_in_month`                                     |

`relative_volume_20` deliberately excludes the current day's own volume from its 20-day baseline
(`shift(1)` before the rolling mean) — otherwise a high-volume day would inflate its own baseline
and understate its own relative volume.

## Target design

- **Regression target:** `future_return` — the `horizon_days`-ahead simple return, *not* the exact
  future price. Predicting a price directly would (a) make the target's scale depend on which
  ticker/era it's from, preventing a shared model across tickers, and (b) implicitly reward a model
  for tracking the current price rather than forecasting its change — a well-known pathology
  ("predict yesterday's price" gets a deceptively good-looking price-space error).
- **Classification target:** `future_class` — Bearish / Neutral / Bullish, from
  `ml.targets.targets.classify_return`, using thresholds derived by
  `derive_classification_thresholds(train_returns, num_std=0.5)`: `mean ± 0.5·std` of the
  **training split's own** `future_return` distribution. Never derived from validation or test —
  that would leak the evaluation data's own distribution into the label definition itself.
  `ml.config.TargetConfig`'s `bearish_threshold=-0.02`/`bullish_threshold=0.02` are a documented
  fixed fallback (roughly a 5-day return's 1-standard-deviation move for a typical large-cap
  equity), not a threshold tuned against any specific run's test metrics.
- **Horizon:** 5 trading days (`DEFAULT_HORIZON_DAYS`), configurable via `TargetConfig.horizon_days`.
  Chosen as a horizon long enough to be feasible from daily OHLCV features (a 1-day-ahead target is
  dominated by noise) and short enough to keep the walk-forward evaluation window meaningful.

## Temporal dataset construction

- **Tabular** (`ml.datasets.tabular`) — one row per `(ticker, day)`, features already summarizing
  trailing history; used by the baselines and XGBoost.
- **Sequence** (`ml.datasets.sequences`) — one sample per `(ticker, day)` is the trailing
  `sequence_length` (60, `SequenceConfig`) days of feature rows, shape `(samples, 60, 27)`; used by
  LSTM/GRU. Built strictly per ticker (`build_sequences` loops `groupby("ticker")` and windows
  within each group) so a window never mixes two tickers' rows.
- **`next_day_return`** (`ml.datasets.tabular.add_next_day_return`) — computed once, on the full
  (pre-split) series, so a row at a split boundary still gets its true realized next-day return
  rather than an artifact of being that split's last row. This is the value the financial
  evaluation replays as "what actually happened next," and is a *different quantity* from
  `future_return` (the `horizon_days`-ahead *forecast target*) — conflating the two would make a
  financial metric describe a trade nobody could actually place.

## Chronological split — dates used in this run

| Split       | Start        | End          |
|-------------|--------------|--------------|
| Train       | 2013-02-08   | 2016-06-30   |
| Validation  | 2016-07-01   | 2017-06-30   |
| Test        | 2017-07-01   | 2018-02-07   |

`ml.datasets.temporal_split.chronological_split` applies these three date ranges identically across
every ticker — never shuffled, never a per-ticker window. `train_test_split(..., shuffle=True)` (or
anything equivalent) is never imported anywhere in this package for the primary evaluation path.
`SequenceScaler` (feature standardization for LSTM/GRU) is fit **only** on the training sequences;
validation/test are transformed with the training-fit parameters, never refit. This is verified two
ways, not just asserted: `tests/unit/test_sequences.py::TestSequenceScalerLeakage` proves fitting on
train-only differs numerically from fitting on train+validation combined (a real leakage check, not
an API-call check), and `test_transform_before_fit_raises`/
`test_validation_data_transformed_with_train_parameters_not_its_own` cover the failure modes
directly.

## Model comparison

| Model                     | Location                          | Purpose                                            |
|----------------------------|------------------------------------|-----------------------------------------------------|
| `NaiveZeroReturnModel`      | `ml.models.baseline.naive`        | Always predicts 0 return — the floor any model must beat |
| `PreviousReturnBaseline`    | `ml.models.baseline.naive`        | Persistence/random-walk: tomorrow looks like today |
| `MajorityClassBaseline`     | `ml.models.baseline.naive`        | Always predicts the training set's most frequent class |
| `XGBoostReturnModel` / `XGBoostDirectionModel` | `ml.models.xgboost.model` | Shallow gradient-boosted trees, the benchmark deep models must beat |
| `LSTMReturnModel`           | `ml.models.lstm.model`            | Sequential model over the 60-day feature window    |
| `GRUReturnModel`            | `ml.models.gru.model`             | Same task, different recurrent cell                |

**Why a naive baseline first:** an XGBoost/LSTM/GRU result is only meaningful relative to these
numbers — if a "sophisticated" model can't beat always-predicting-zero on MAE/RMSE, it has learned
nothing useful, no matter how good its raw metric looks in isolation.

**Why XGBoost before deep learning:** gradient-boosted trees on tabular financial features are a
strong, fast, well-understood baseline in this domain; a deep model is only worth its added
complexity if it demonstrably beats XGBoost, not by default. Hyperparameters
(`XGBoostHyperparameters`: `n_estimators=200` ceiling, `max_depth=4`, `learning_rate=0.05`,
`subsample`/`colsample_bytree=0.8`) are deliberately conservative, hand-picked defaults — no
hyperparameter search was run. Early stopping (`early_stopping_rounds=20`) is against the
**validation** split only, never against test.

**LSTM vs GRU — architecture (identical on purpose):** both wrap the same
`ml.models._recurrent._RecurrentNet`/`RecurrentReturnModel`, differing only in `cell_type`. Shared
hyperparameters (`RecurrentHyperparameters`): `hidden_size=32`, `num_layers=1`, `dropout=0.2`,
`learning_rate=1e-3` (Adam), `max_epochs=30` ceiling with early stopping
(`early_stopping_patience=5`, against validation loss, best-state restored — not just
"stopped early", the weights are actually rolled back), `batch_size=64`. Loss: MSE against
`future_return`. Deliberately small — the goal is a fair, reproducible LSTM-vs-GRU comparison, not
chasing a benchmark number; a larger network would also be harder to justify against 11 tickers'
worth of training data without material overfitting risk.

**The comparison does not assume an answer.** The results below are from one real run against the
research dataset (see "Real experiment results") — read them as what this dataset and this
pipeline produced, not as a general claim about LSTM vs GRU vs XGBoost.

## Financial evaluation methodology

See `ml.evaluation.financial` module docstring for the full strategy definition (entry/exit rule,
position sizing, transaction costs, benchmark, rebalance frequency) — summarized:

- **Entry:** go long the next trading day if the forecast is positive; otherwise stay flat. Sign
  only, no confidence-weighted sizing.
- **Exit / rebalance:** daily, from the latest forecast — not a fixed `horizon_days`-long hold
  (holding literally `h` days on every day's signal would double-count overlapping returns).
- **Position sizing:** binary (fully long or fully flat). No leverage, no shorting.
- **Costs:** `cost_bps=10` (0.10%), charged only when the position actually changes.
- **Benchmark:** buy-and-hold over the identical window.

**Per-ticker, never a naive cross-ticker concatenation.** An earlier version of this pipeline fed
one ticker's rows immediately followed by the next ticker's rows into a single call to
`evaluate_strategy` — which let a "trade" span a ticker boundary (a position that was really "long
AAPL" silently continuing as "long AMZN" the next row) and compounded unrelated instruments' daily
returns into one artificial equity curve. `ml.evaluation.financial.evaluate_strategy_per_ticker`
fixes this: it runs the identical single-asset strategy independently per ticker, keeps every
ticker's equity curve, trade list, and cost accounting fully separate, and only averages the
*summary statistics* afterward. `tests/unit/test_evaluation_financial.py::TestEvaluateStrategyPerTicker`
verifies the isolation directly (a large loss in one ticker must not appear in another's number).

**This is still not a portfolio backtest.** No cross-ticker capital allocation, rebalancing between
names, or correlation is modeled — each ticker is evaluated as if it were the only position in the
account. A real multi-asset backtest (position sizing across names, portfolio-level risk, realistic
fills) is explicitly out of scope for Phase 5 (see "Known limitations" and "Recommended Phase 6").

## Model registry (`ml.registry.registry`)

A JSON-file-backed registry (`registry.json`), deliberately not MLflow — nothing about this
project's scale or team size justifies that operational overhead yet (introducing it "for
appearance" is explicitly against project rules). Each `ModelRecord` captures: model name/type,
version (`new_version_string`, e.g. `xgboost_return-<timestamp>-<random>`), `dataset_version`,
`feature_version`, hyperparameters (the full `ExperimentConfig`), train/validation/test period
date ranges, metrics, artifact path, creation timestamp, git commit (`get_git_commit()` — `None`,
never fabricated, if the repo/commit can't be resolved), and status
(`TRAINING`/`VALIDATED`/`STAGING`/`PRODUCTION`/`ARCHIVED`/`FAILED`). `best_by_metric` supports
picking a champion model by any nested metric path.

## Reproducibility

`ml.config.set_global_seed(seed)` seeds `random`, `numpy`, and `torch` (CUDA too, if present) in one
place, called once at the start of `run_experiment`. The entire training configuration — seed,
tickers, feature/target/split/sequence settings — lives in one `ExperimentConfig` dataclass
(`ml.config`), serialized verbatim to `configuration.json` and into the registry, so a run is
reconstructable from its output alone rather than from scattered constants.

## Structured experiment output

`ml.pipelines.train_pipeline.run_experiment(config, output_dir, provider=...)` writes, under
`output_dir`: `configuration.json`, `provenance.json` (source/environment/tickers/date
range/retrieval time/dataset version), `metrics.json` (every model's regression/classification/
financial metrics), `split_bounds.json`, and `models/<model_name>/` (serialized artifacts — XGBoost
native JSON, LSTM/GRU torch state dict + scaler + config JSON). It never runs inside an HTTP
request and is never imported by `backend/` (ADR-001) — it is invoked directly
(`ml/scripts/run_real_experiment.py`) or, in a later phase, from a Celery task that only creates a
job row and enqueues, following the same shape `market_data.ingest` already established (Phase 3).

## Inference interface (`ml.inference`)

`ml.inference.inference.predict_return(model, features, ...)` / `predict_direction(model,
features, ...)` return a `PredictionResult`: ticker, `as_of` date, model name/version, feature-set
version, prediction timestamp, expected return, predicted class, and class probabilities.
Probabilities are populated **only** if the model actually exposes `predict_proba` (XGBoost's
direction model does; the naive baselines don't) — never a fabricated uniform/fake distribution for
a model that can't produce one. These are the low-level building blocks; `ml.inference.serving`
(added in Phase 6) is the orchestration layer described next.

## Inference serving (`ml.inference.serving`) — Phase 6

The layer between "raw price history" and a served prediction. Still standalone `ml/` code — no
FastAPI import; `backend/app/services/forecast_service.py` and `backtest_service.py` are the only
things that call into it (ADR-001), and neither ever calls `.fit()`.

- **`load_forecast_models(registry_path)`** — loads the best-by-metric `xgboost_return` and
  `xgboost_direction` models from the registry (never an arbitrary filesystem path — the registry
  is the only valid model source). Raises `ModelUnavailableError` if the registry doesn't exist yet
  (a real, expected state before any training run), no evaluated model of either type exists, or
  the two models disagree on feature/dataset version (which would mean combining them into one
  forecast is not methodologically sound).
- **`build_latest_feature_row(ohlcv, min_history_rows=60)`** — runs the exact same
  `ml.features.pipeline.build_features` training uses, on whatever history is supplied, and returns
  the last fully-warmed-up row. Raises `InsufficientHistoryError` for too few rows or a
  still-`NaN` latest row (e.g. a caller accidentally passing a different ticker's short history
  appended at the end — covered directly by a test). Raises `DataValidationFailedError` if the
  history fails `ml.data.validation.validate`.
- **`generate_forecast(ohlcv, models, ticker=...)`** — combines both models into one
  `ForecastResult`. Raises `UnsupportedTickerError` if the ticker isn't in the trained model's
  universe (`ExperimentConfig.tickers`) — this project does not serve a prediction for a ticker the
  model was never validated on, rather than silently extrapolating out-of-distribution.
- **`generate_historical_predictions(ohlcv, models)`** — the batch form: one row per fully-warmed-up
  `(ticker, day)`, used by `ml.backtest` (a backtest needs a prediction on every historical day, not
  just the latest). Same feature pipeline, same models — verified to agree exactly with
  `generate_forecast` on an overlapping day, and to be truncation-invariant (appending future rows
  never changes an earlier day's prediction).

**Data-environment disclosure, not a data-environment gate.** The backend feeds whatever
`price_bars` a deployment actually has — in Demo Mode (the default), `DemoMarketDataProvider`'s
synthetic random walk (ADR-007), not the real historical data the model was trained on
(`RESEARCH_DATASET_VERSION`). Feeding demo data through a model trained on real data produces a
technically-valid-shaped prediction with **no real predictive meaning** — this is not blocked
(blocking it would make the served-forecast feature undemoable in the one environment this project
ships with data in), but every response carries `data_source` so it is never hidden (ADR-007's
established labeling precedent, extended here) — see `docs/decisions.md` for the full reasoning.

## SHAP explainability (`ml.explainability.shap_explainer`) — Phase 6

Prioritizes XGBoost because it is the strongest-performing model from Phase 5, and
`shap.TreeExplainer` is exact and fast for tree ensembles — no sampling/approximation needed,
unlike a model-agnostic explainer.

**SHAP explains the contribution of features to a model's prediction; it does not establish
causality.** A large positive SHAP value moved *this model's output* in the positive direction
relative to the model's average prediction — a statement about the model's learned behavior on
this input, not a claim about what actually drives the security's future return. Every function
returns "contribution", never "cause" or "reason", and the backend echoes this as a
`methodology_note` on every explanation response.

- `explain_return_prediction(model, feature_row, feature_columns, top_n=5)` — top-N features by
  `abs(contribution)` behind the return model's prediction.
- `explain_direction_prediction(model, feature_row, feature_columns, predicted_class_index=...,
  top_n=5)` — top-N features behind the direction model's prediction, explained relative to the
  **predicted class specifically** (not a three-way breakdown across all classes at once) — the
  actual question a "why did the model predict Bullish" UI asks.

Verified beyond "SHAP executes without error": feature values match the input row exactly (not
fabricated), `direction` matches the sign of `contribution`, results are ranked by magnitude,
repeated calls are deterministic, and the full-feature-set contribution total plus the base value
reconstructs the model's own prediction (SHAP's additive property, checked numerically against an
independently-constructed `shap.TreeExplainer`, not just trusted).

Computed only on explicit request (`GET /forecast/explanation`), never as a side effect of an
ordinary forecast request — SHAP is materially more expensive than a plain `predict()` call.

## Portfolio backtest methodology (`ml.backtest`) — Phase 6

Phase 5 identified a limitation: financial evaluation was per-ticker
(`ml.evaluation.financial.evaluate_strategy_per_ticker`, ADR-018), not portfolio-level — each
ticker was scored as if it were the account's only position. `ml.backtest` is the portfolio-level
engine, built on top of `ml.inference.serving.generate_historical_predictions` (real historical
predictions from the already-trained, already-evaluated models — never retrained, never
retroactively tuned).

**Strategy definition** (`ml.backtest.engine`'s module docstring has the full write-up):

- **Signal** (`ml.backtest.signals`): Bullish prediction → long; Neutral/Bearish → flat. Shorting is
  never assumed — `SignalRule.allow_short` is an explicit, off-by-default opt-in at the signal
  layer, and the portfolio engine itself only ever takes long-or-flat positions regardless (v1
  scope), so enabling it upstream still can't produce a short position in this backtest.
- **Execution timing — no look-ahead:** a signal decided using information available at the close
  of day `t` is applied to the return realized from the close of `t` to the close of `t+1` — never
  to the return ending at `t` itself (the same close the signal was computed from). The one
  deliberate backward-looking `.shift(-1)` in `ml.backtest.engine` exists purely to SCORE an
  already-decided position (mirrors `ml.datasets.tabular.add_next_day_return`'s identical,
  already-tested pattern), never to make one.
- **Position sizing:** equal weight across every ticker with a long signal on a given day (dynamic
  — more simultaneously-long names means a smaller weight each), the remainder in un-modeled cash.
  No leverage. `max_position_weight` optionally caps a single name.
- **Transaction costs & slippage:** `commission_bps` + `slippage_bps` (both configurable, non-zero
  defaults — 5 bps each), charged against one-way turnover on the day of the rebalance.
- **Benchmark:** equal-weight, daily-rebalanced buy-and-hold across every ticker with a valid price
  that day — no signal, no transaction costs (mirrors Phase 5's per-ticker benchmark treatment).
- **Rebalance frequency:** daily.

**Still not a full brokerage simulation** — no fractional-share rounding, no market-impact-scaling
slippage, no intraday fills, no borrow costs. See "Known limitations."

**Portfolio metrics** (`ml.backtest.metrics.PortfolioMetrics`): cumulative return, CAGR, annualized
volatility, Sharpe ratio, Sortino ratio, max drawdown, win rate, mean turnover, total transaction
costs, rebalance-day count, benchmark cumulative return. Computed from the returns series directly
(a compounded product), not from `equity_curve.iloc[-1] / equity_curve.iloc[0]` — an earlier draft
did exactly that and silently reported a real, nonzero single-day return as 0% whenever there was
only one usable trading day (both index positions were the same value); a regression test now
pins this. Edge cases handled explicitly, never as a silent `NaN`: zero-variance returns →
`sharpe_ratio`/`sortino_ratio` are `None`; no down days → `sortino_ratio` is `None`; empty input →
raises `ValueError` rather than a report full of zeroes that would look like a real flat result.

**Leakage/timing tests** (`ml.backtest`'s test suite) prove, not just assert: a signal is never
scored against the same close it was generated from; truncating future rows never changes an
earlier day's equity or weights; mutating only a future bar's price never changes an earlier day's
recorded return; one ticker's return calculation never uses another ticker's price (a perfectly
flat ticker spliced in alongside a moving one contributes exactly zero, checked numerically).

## Walk-forward evaluation (`ml.backtest.walk_forward`) — Phase 6

The framework, plus one deterministic, actually-executed example — not a claim of a complete
multi-window, multi-model study.

```
Train window -> Validation -> Test window -> Advance window -> Retrain -> Next test window
```

- `generate_rolling_windows(start_date, end_date, train_days, validation_days, test_days,
  step_days)` — pure, deterministic window generation, no data access, no training.
- `run_xgboost_return_walk_forward(provider, tickers, windows, ...)` — retrains a **fresh**
  `XGBoostReturnModel` from scratch for every window (never reusing a previous window's fitted
  model), scores it on that window's own held-out test period. Restricted to the XGBoost return
  model specifically because it is fast enough to retrain per-window within this phase's scope.

Run for real (`tests/integration/test_walk_forward_integration.py`) against the actual 5-year
sample dataset with 2 rolling windows (train 1000 days / validation 180 / test 180, step 250):
produced different MAE per window (not the same number copy-pasted), each window's test period
strictly later than the previous one — genuine retraining, not a re-scored single split. LSTM, GRU,
and the direction model are **not** walked forward — see "Known limitations."

## Financial sentiment (`ml.nlp.sentiment`) — Phase 7

FinBERT (`ProsusAI/finbert`, pinned to commit `4556d13015211d73dccd3fdd39d39232506f3e43` — every
`NewsSentiment` row records this exact value as `model_version`, not "latest"), a
transformer model fine-tuned for financial-text sentiment: positive/neutral/negative
probabilities from one forward pass. Still standalone `ml/` code — no FastAPI import;
`backend/app/services/news_sentiment_service.py` is the only thing that calls into it (ADR-001),
and it never trains anything, only loads the pinned checkpoint and runs inference.

**Sentiment is an informational signal, not a guaranteed trading signal.** No code in this
project — here or in `ml.backtest`/`ml.evaluation` — computes or implies that FinBERT's output
predicts a security's future return; this phase does not run or claim any such experiment. Every
sentiment-bearing API response (`GET /stocks/{ticker}/sentiment`) carries this exact caveat as a
`disclaimer` field, not just in this doc.

- **`analyze_sentiment(text)`** / **`analyze_batch(texts)`** — the public interface, returning a
  `SentimentResult` (positive/neutral/negative probabilities, `predicted_label`, `model_name`,
  `model_version`). `get_sentiment_analyzer()` is a process-wide singleton (`lru_cache`) — the
  ~440MB checkpoint is loaded from disk once per process, never once per article (see
  "Performance" below).
- **Label order is read from the model's own config, never hardcoded** —
  `ProsusAI/finbert`'s checkpoint happens to order its output as
  `{0: positive, 1: negative, 2: neutral}`, not alphabetical; `FinBertSentimentAnalyzer` builds its
  `id2label` mapping from `model.config.id2label` every time, so this would still be correct even
  if a future model swap used a different internal order.
- **Determinism:** the model runs in `eval()` mode (no dropout, no sampling) — the same text
  produces the same result on repeated calls
  (`tests/unit/test_nlp_sentiment.py::test_deterministic_across_repeated_calls`). Batched vs.
  one-at-a-time inference agree on the predicted label and probabilities to within ~1e-4 (padding
  changes attention's floating-point rounding at the ~1e-6 level — a well-known, benign effect of
  batching, not a bug; see that test file's `test_batch_matches_individual_calls`).
- **Input contract:** raises `ValueError` on empty/whitespace-only text and `TypeError` on a
  non-string, rather than fabricating a result — never silently pads or skips within `analyze_batch`.
  Text longer than 512 tokens is truncated by the tokenizer (FinBERT's own input limit), not an
  error. The text actually analyzed is `title + ". " + summary` when a summary exists
  (`app/services/news_processing.py::sentiment_input_text`), never a scraped full article body
  (ADR-025).

**Performance:** `run_news_ingestion` calls `analyze_batch` in chunks of `SENTIMENT_BATCH_SIZE`
(16) articles per forward pass, never one FinBERT call per article, and only over
`NewsRepository.get_articles_missing_sentiment(model_version=...)` — an article already scored by
the current model version is never re-processed (idempotent; see "Article/sentiment idempotency").
The singleton analyzer means a given worker process pays the model-load cost exactly once,
regardless of how many ingestion jobs it later processes.

## News & sentiment pipeline (Phase 7)

The full flow, end to end (see docs/architecture.md for the diagram):

```
NewsProvider.fetch_articles(tickers, since, until, limit)
        │
        ▼
normalize (whitespace only, preserve financial terms) → filter language → deduplicate
        │
        ▼
NewsRepository.upsert_articles()   -- idempotent on (source, external_id)
        │
        ├─ entity_extraction_service.extract_entities()  -- per article, against securities table
        │       → NewsRepository.add_entity_matches()    -- idempotent on (article_id, security_id)
        │
        └─ ml.nlp.sentiment.analyze_batch()  -- only articles missing this model_version's score
                → NewsRepository.upsert_sentiment()  -- idempotent on (article_id, model_version)
```

**News provider abstraction** (`app/providers/base.py::NewsProvider`, mirrors `MarketDataProvider`
— ADR-002): `fetch_articles(*, tickers, since, until, limit)` is a pure function of its inputs
(explicit `since`/`until`, never internal wall-clock reads), so re-fetching the same window is
meaningfully idempotent, not coincidentally so. `DemoNewsProvider` (`app/providers/news/demo.py`)
is the only implementation today — deterministic, templated, clearly-synthetic headlines over the
same 10-ticker demo universe `DemoMarketDataProvider` uses (ADR-028). **Demo News is never
presented as real news**: every stored article carries `data_source="demo"`, every demo article
URL uses the `.invalid` TLD (fails obviously if clicked), and the frontend shows an explicit "Demo
News" banner whenever any returned article is demo-sourced. A real provider (a licensed news API)
plugs in behind the same ABC without touching any downstream code — not built in this phase (no
paid vendor key), same reasoning as Phase 3's `MarketDataProvider`.

**Article provenance:** every `NewsArticle` row records `source` + `external_id` (dedup identity),
`published_at` + `retrieved_at` (two distinct timestamps — when the article says it was published
vs. when this system actually fetched it), `data_source` (demo/external), and `content_status`
(what's actually stored — see ADR-025: summary/title only, never a full scraped body, for
licensing reasons).

**Entity/ticker mapping** — see ADR-026 for the full methodology (ticker-symbol cashtag/parenthetical
matching + case-sensitive company-name matching against the `securities` table, never a generic
NER model at this project's scale). `MIN_CONFIDENCE = 0.70`; an article that doesn't clear it stays
unmapped rather than getting an invented ticker.

**Temporal aggregation — no leakage:** `app/services/news_sentiment_aggregation.py::compute_window_stats`/
`compute_sentiment_summary` take explicit `since`/`until`/`as_of` bounds and query
`published_at <= until` (and `>= since`) directly in SQL — there is no code path that aggregates
"all articles" and filters in Python after the fact, which would be an easy place to accidentally
include a too-recent row. `tests/integration/test_news_sentiment_aggregation.py::TestTemporalLeakage`
proves this directly: an article published after `as_of`/`until` is excluded from both the
distribution/count *and* the momentum calculation (recent-half vs. older-half of the window), and
moving `as_of` forward can only ever add articles to the count, never remove one that was
previously included.

**Article/sentiment idempotency:** three independent unique constraints make re-running the same
ingestion job a no-op where nothing changed — `(source, external_id)` for articles,
`(article_id, security_id)` for entity matches, `(article_id, model_version)` for sentiment.
`tests/integration/test_news_sentiment_service.py::test_run_news_ingestion_is_idempotent` runs the
full pipeline twice over the same window and asserts zero new rows the second time.

**Async processing:** `run_news_ingestion` (fetch → normalize → store → extract → analyze) is a
plain function with no Celery/FastAPI imports, called directly by tests and wrapped thinly by
`app/workers/tasks/news.py` (`news.ingest` Celery task) — identical shape to Phase 3's
`market_data.ingest`. FinBERT inference is the one CPU-heavy step, which is exactly why this never
runs inside `POST /news/ingest`'s request handler — that route only creates a `jobs` row and
returns `202` immediately (ADR-001).

## Real experiment results

Produced by `ml/scripts/run_real_experiment.py` against `SampleSP500ResearchProvider` (11 tickers,
the split dates above). Full output: `ml/experiments/sp500_sample_v1/metrics.json` (gitignored —
model artifacts and experiment output are never committed).

Classification thresholds derived from the training split: bearish < **-1.29%**, bullish >
**+2.14%** (5-day return).

| Model                     | MAE     | RMSE    | R²      |
|----------------------------|---------|---------|---------|
| Naive (always 0)            | 0.0209  | 0.0290  | -0.044  |
| Previous-return baseline    | 0.0224  | 0.0312  | -0.206  |
| XGBoost (return)            | 0.0203  | 0.0285  | -0.005  |
| LSTM (return)                | 0.0258  | 0.0354  | -0.359  |
| GRU (return)                 | 0.0277  | 0.0379  | -0.564  |

| Model                     | Accuracy | F1 (macro) | ROC-AUC (OvR) |
|----------------------------|----------|------------|----------------|
| Majority-class baseline     | 0.571    | 0.242      | — (constant predictor) |
| XGBoost (direction)         | 0.539    | 0.290      | 0.571          |

**Reading these honestly:** every model's R² on this test window is negative or barely above zero
— none of them explains meaningful variance in the 5-day-ahead return beyond a flat mean predictor,
and XGBoost's classifier barely edges out a majority-class baseline on F1. This is an unsurprising
result for daily-OHLCV-only features over 11 names and roughly a 7-month test window, and it is
reported as-is rather than selectively.

Per-ticker financial evaluation (mean across the 11 tickers, `cost_bps=10`, test window
2017-07-01–2018-02-07): XGBoost's return model shows the highest mean Sharpe (≈1.75) and cumulative
return (≈22%) of the group, with only 13 total trades across all 11 tickers (it stayed flat most of
the window) and a materially lower mean max-drawdown (≈-8%) than the persistence baseline (≈-8%,
comparable) — LSTM/GRU landed in between the persistence baseline and XGBoost. See "Known
limitations" for exactly what this evaluation does and does not model before drawing any conclusion
from it.

**None of this should be read as evidence of a profitable, production-ready, or investment-grade
strategy.** It is one run, on one small (11-ticker, 5-year) real-but-limited historical sample, with
a simplified single-asset-at-a-time evaluation and no portfolio-level risk modeling. Its value is
demonstrating that the pipeline is leakage-free, reproducible, and produces an honest, non-cherry-picked
comparison — not that any of these models should inform a real trading decision.

## Real forecast and backtest examples (served, Phase 6)

Both captured from the live API (`GET/POST`), against the registered models above and this
deployment's actual price data — Demo Mode's synthetic AAPL series, honestly labeled
`"data_source": "demo"` in the response, not the real research data the model trained on:

```
GET /api/v1/stocks/AAPL/forecast
{
  "ticker": "AAPL", "model_name": "xgboost", "horizon_days": 5,
  "predicted_direction": "Neutral", "expected_return": 0.00455,
  "probabilities": {"Bearish": 0.286, "Neutral": 0.405, "Bullish": 0.308},
  "data_source": "demo", ...
}
```

`GET /forecast/explanation` for the same request: top direction factors were `atr_14`
(-0.065), `volatility_10d` (-0.062), `rolling_volume_mean_20` (-0.061) — all pushing away from a
confident directional call, consistent with a "Neutral" prediction.

A `POST /research/backtest` run (AAPL/MSFT/JPM, ~150 days of demo data, 10 bps commission + 5 bps
slippage) produced a real, non-fabricated equity curve and metrics — reported here as a
demonstration that the engine runs end to end, not as evidence about strategy quality (150 days of
*demo* data carries the same "no real predictive meaning" caveat as the forecast above).

## Leakage tests

- `tests/unit/test_features.py::test_no_lookahead_truncating_the_future_does_not_change_past_feature_values`
  and `::test_no_lookahead_per_ticker_in_a_multi_ticker_panel` — features computed on the full
  series vs. a truncated series are byte-identical up to the truncation point.
- `tests/unit/test_targets.py::test_targets_module_only_uses_negative_shift_for_the_future_target` —
  AST-based inspection of every feature module's source, asserting no negative `.shift()` exists
  outside `ml.targets.targets`.
- `tests/unit/test_sequences.py::TestSequenceScalerLeakage` (3 tests) — fitting `SequenceScaler` on
  train-only produces different parameters than fitting on train+validation combined (a numeric
  proof of isolation, not an API-usage check); transform-before-fit raises; validation data is
  transformed with the *training* fit's parameters, never its own.
- `tests/unit/test_targets.py`/`test_temporal_split.py` — no ticker's warm-up/future-target NaNs
  leak across a ticker boundary; split boundaries have zero gap and zero overlap by construction.
- `docs/decisions.md` ADR-017 records the walk-through of why the classification thresholds are
  derived from the training split only.
- `tests/unit/test_inference_serving.py::TestGenerateHistoricalPredictions::test_output_has_no_future_information_truncation_invariant`
  — the same truncation-invariance proof, now through the batch historical-scoring path.
- `tests/unit/test_backtest_engine.py::TestCriticalLeakageAndTimingTests` (4 tests) — a signal is
  never scored against the same close it was generated from; truncating future rows never changes
  an earlier day's equity/weights; a future price spike never changes an earlier day's recorded
  return; one ticker's return never uses another ticker's price.
- `tests/integration/test_news_sentiment_aggregation.py::TestTemporalLeakage` (5 tests) — an
  article published after `as_of`/`until` is excluded from both the sentiment distribution and the
  momentum calculation; moving `as_of` forward can only add articles, never remove one already
  counted; window boundaries are inclusive on both ends (an article published exactly at `since` or
  `until` counts); a far-future article does not leak into the momentum sub-window calculation.

## Known limitations

- **Not split/dividend-adjusted.** `research_sample_sp500.csv` is a raw-price snapshot — a large
  stock split inside the window would show up as a fabricated "crash" in raw features. None of the
  11 tickers had a split in this window, but a future provider swap must adjust for this before it
  can be trusted for names that do.
  **Survivorship bias.** All 11 tickers are large, still-listed, currently prominent names —
  no delisted or failed companies are represented, which tends to make a sample like this look
  more benign than the broader market historically was.
- **Static snapshot, not a live feed.** Retrieved once (2026-09-11); a real production system needs
  an incrementally-updated provider, which is exactly the ABC `ResearchDataProvider` exists to let
  a future implementation slot into without touching any downstream code.
- **FB, not Meta.** The sample predates the 2021 rename — reported as `FB` throughout, not silently
  relabeled.
- **Portfolio backtest is still not a full brokerage simulation.** `ml.backtest` (Phase 6) fixed
  the per-ticker-only gap (ADR-018/ADR-024) with real multi-asset position sizing and one
  consolidated equity curve, but still doesn't model fractional-share rounding, market-impact-
  scaling slippage, intraday fills, or borrow costs.
- **Low per-ticker trade counts.** Several tickers produced under 10 trades in the ~7-month test
  window (a model that stays flat most of the time), which makes `win_rate`/`profit_factor` for
  those tickers, and their cross-ticker mean, high-variance and easy to over-read — reported as
  computed, not smoothed or filtered.
- **Small universe, mostly single-window evaluation.** 11 tickers; the primary train/validation/test
  split is one non-overlapping ~7-month test period. Phase 6 added ONE real, actually-executed
  walk-forward example (2 rolling windows, XGBoost-return only) proving the framework genuinely
  retrains rather than re-scoring one split — it is not a complete multi-model, multi-window study;
  LSTM, GRU, and the direction model are not walked forward.
- **The forecast/backtest APIs serve XGBoost only.** LSTM/GRU inference is still not exposed over
  HTTP — XGBoost is the best-performing model from Phase 5's comparison, so this isn't a quality
  compromise. (Phase 7 did add `torch`/`transformers` to the backend for FinBERT, so "no torch in
  the backend" — the original reason LSTM/GRU serving was deferred — no longer holds; LSTM/GRU
  serving remains undone simply because nothing has needed it yet, not because of a dependency
  barrier. See ADR-027.)
- **XGBoost/scikit-learn version pin.** `xgboost==2.1.3` (as originally pinned) fails to
  `load_model()` a saved estimator under `scikit-learn==1.6.0` (`AttributeError:
  'super' object has no attribute '__sklearn_tags__'`) — a real upstream incompatibility, not a bug
  in this codebase, caught by `tests/integration/test_xgboost_integration.py`'s save/load
  round-trip test. Fixed by pinning `xgboost==2.1.4` (both `ml/` and `backend/`).
- **Demo-data inference/backtests carry no real predictive meaning.** Disclosed via `data_source`
  on every response (never hidden), but worth restating: any forecast or backtest run against this
  deployment's default Demo Mode data is a demonstration of the serving architecture, not a
  real-world result — only a run against real historical data (`RESEARCH_DATASET_VERSION`) reflects
  the model's validated research performance. The identical caveat applies to Phase 7's demo news:
  `DemoNewsProvider`'s synthetic headlines produce genuine FinBERT sentiment scores, but the
  *content* being scored is fabricated, so the sentiment signal itself carries no real-world meaning
  until a real news provider is wired in.
- **No real (or fake) demonstration that sentiment adds predictive value.** Phase 7 explicitly does
  not run — and this document does not claim — any experiment testing whether news sentiment
  predicts subsequent returns. `ml.backtest`'s signal generation (`ml.backtest.signals`) does not
  consume sentiment at all yet; sentiment and forecasting remain two separate, uncombined
  capabilities in this phase.
- **Entity mapping only covers securities already tracked.** `entity_extraction_service` matches
  against the `securities` table — an article about a company not yet ingested into that table
  (e.g. a private company, or a public one this deployment hasn't tracked) is correctly left
  unmapped, never guessed.
- **Small, single-provider news universe.** Only `DemoNewsProvider`'s fixed ~80-article fixture
  (10 tickers × 8 templates) exists; sentiment aggregates over short windows (24h) can be based on
  very few articles per ticker, making them easy to over-read — reported as computed, not smoothed.
- **Daily-granularity sentiment history only.** `GET /sentiment/history` aggregates one point per
  calendar day; a real intraday news cycle (multiple market-moving articles in one day) collapses
  into a single daily average.

## Research agent (Phase 8) — a backend/`app/agent/` concern, not an `ml/` one

Phase 8 added a grounded LLM research agent (`app/agent/`) that reasons over this pipeline's
outputs — forecasts, SHAP factors, sentiment, backtests — through typed tool calls, never by
querying `ml/` directly or reimplementing any of its logic. Every number the agent's answers cite
still traces back to exactly the same code documented in this file
(`ml.inference`/`ml.explainability`/`ml.backtest`/`ml.nlp`); the agent adds a reasoning/citation
layer on top, not a new data or modeling path. See [architecture.md](architecture.md) "Research
agent flow" for the request/tool/evidence loop and [decisions.md](decisions.md) ADR-029 through
ADR-033 for the agent's own design decisions (LLM provider abstraction, the closed tool set and
no-vector-DB retrieval choice, rate limiting, conversation-memory scope, and citation formatting).
This document's own scope — data contracts, feature/target design, training, evaluation,
inference serving, and NLP methodology — is unchanged by Phase 8.

## Recommended Phase 9

1. A real multi-asset walk-forward study (all models, multiple rolling windows) once a larger
   historical sample is available — `ml.backtest.walk_forward`'s framework already supports this;
   Phase 6 ran one small, fast, XGBoost-only example as proof.
2. LSTM/GRU inference serving, if a real need emerges — `torch` is already a backend dependency as
   of Phase 7 (ADR-027), so this is no longer blocked on adding it.
3. A real (paid or free-tier) historical/live data vendor behind a new `ResearchDataProvider`/
   `MarketDataProvider`-style implementation, addressing the split-adjustment and survivorship-bias
   limitations above — and, symmetrically, a real licensed news provider behind `NewsProvider`
   (ADR-028), addressing Phase 7's demo-only news universe.
4. A real portfolio-management product surface (persisted positions, rebalancing schedules,
   multi-strategy comparison) — `ml.backtest` is the correct engine underneath this, not something
   to be replaced.
5. If a genuine sentiment-informed strategy is ever built, it must be a real, out-of-sample
   experiment (sentiment as an additional `ml.backtest.signals` input, evaluated the same
   leakage-free way price-based signals already are) — never a claim made without one.
6. A real live-provider integration check for the research agent's `AnthropicLLMProvider` (Phase 8
   verified this path only against a deterministic fake — see ADR-029's known limitation) once a
   provisioned API key is available in whatever environment runs this next.
