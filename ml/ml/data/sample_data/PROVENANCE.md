# `research_sample_sp500.csv` — provenance

**This is real historical market data, not synthetic data.** It is entirely separate from
`backend/app/providers/market_data/demo.py`'s `DemoMarketDataProvider`, which generates synthetic
prices for the running application's Demo Mode. Nothing in `ml/` reads from or writes to the
application database — see `docs/ml-pipeline.md` for the full data-environment separation.

## Source

- **Origin dataset:** "S&P 500 stock data" (daily OHLCV for S&P 500 constituents, 2013–2018),
  originally published on Kaggle and redistributed by Plotly in their public examples repository.
- **Retrieved from:** `https://raw.githubusercontent.com/plotly/datasets/master/all_stocks_5yr.csv`
  (a static file in the `plotly/datasets` GitHub repository).
- **License:** MIT (per the `plotly/datasets` repository's published license) — permits reuse,
  including for this kind of research/educational purpose.
- **Retrieval date:** 2026-09-11 (via a direct HTTPS request to the URL above; no scraping,
  no authentication, no automated browser interaction — a single static-file download).
- **Why this source, not a live vendor API:** no market-data API key is configured in this
  environment (`MARKET_DATA_API_KEY` is reserved, unset — see `backend/app/core/config.py`), and
  vendor sites tested for a scriptable, ToS-compliant historical-data endpoint (Stooq, Yahoo
  Finance) either required browser-only JavaScript verification or rate-limited/blocked
  unauthenticated programmatic access — see ADR in `docs/decisions.md`. This is a real, permissively
  licensed, statically-hosted dataset instead of a fabricated one or an unreliable scrape.

## What was kept

The original file has 446 tickers / ~545k rows. This subset keeps 11 tickers chosen for sector
diversity and name recognition, unmodified except for selection and re-sorting (ticker, then
date):

`AAPL, MSFT, AMZN, GOOGL, JNJ, JPM, FB, NVDA, DIS, KO, PG`

| Field | Value |
|---|---|
| Rows | 13,850 (1,259 trading days × 11 tickers, verified equal per ticker) |
| Date range | 2013-02-08 to 2018-02-07 (inclusive), verified identical across all 11 tickers |
| Columns | `date, open, high, low, close, volume, ticker` |
| Missing values | none (verified — no empty fields, no `NaN`, no duplicate `(ticker, date)` pairs) |
| Chronological order | verified strictly ascending per ticker |

## Known limitations (documented, not hidden)

- **No adjusted-close / split-and-dividend adjustment column.** `close` is as published in the
  source file. A real corporate action (e.g. a stock split) inside the window would show up as a
  large single-day price jump rather than a smooth adjustment. `ml/data/validation.py` flags
  large single-day moves as *suspicious*, not as an error — see `docs/ml-pipeline.md`.
- **Survivorship / point-in-time bias.** These are S&P 500 constituents as compiled by the
  original dataset's author around 2018, not the actual index membership at each historical date.
  A ticker that was added to or removed from the index during 2013–2018 is included or excluded
  based on 2018 membership, not historical membership. Irrelevant for this phase's purpose
  (pipeline correctness, not an index-replication strategy) but would matter for any real
  portfolio-construction use.
- **`FB` predates the 2021 Meta Platforms rename** — this is the real historical ticker for the
  company during 2013–2018, not an error.
- **Single static snapshot, not a live feed.** There is no ongoing ingestion of this file; it is
  a fixed, versioned research dataset (`RESEARCH_DATASET_VERSION` in `ml/data/contracts.py`).
  A future real-vendor `ResearchDataProvider` implementation would supersede it without changing
  any downstream code — see `ml/data/research_provider.py`.

## Reproducing this extraction

```bash
curl -s "https://raw.githubusercontent.com/plotly/datasets/master/all_stocks_5yr.csv" -o all_stocks_5yr.csv
python - <<'PY'
import csv
tickers = ["AAPL","MSFT","AMZN","GOOGL","JNJ","JPM","FB","NVDA","DIS","KO","PG"]
rows = []
with open("all_stocks_5yr.csv") as f:
    for row in csv.DictReader(f):
        if row["Name"] in tickers:
            rows.append(row)
rows.sort(key=lambda r: (r["Name"], r["date"]))
with open("research_sample_sp500.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "open", "high", "low", "close", "volume", "ticker"])
    for r in rows:
        w.writerow([r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"], r["Name"]])
PY
```
