# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```powershell
# Create and activate virtualenv (Windows)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

First run downloads the FinBERT model (~440 MB) from HuggingFace. Subsequent runs use the local cache.

## Commands

```powershell
# Run the pipeline locally (generates data/output.json)
$env:PYTHONIOENCODING = "utf-8"; python run_all.py

# Or via batch file (with pause at end)
.\actualizar.bat

# Run all unit tests
python -m unittest tests.test_aggregate -v

# Run a single test method
python -m unittest tests.test_aggregate.TestWriteOutputsNoDataJs.test_output_json_is_valid -v

# Serve HTML locally for development (needs internet — HTML fetches from Supabase)
python -m http.server 8000
# Then open: http://localhost:8000/docs/sp500-heatmap.html
```

Always run from the project root — `run_all.py` loads `config.json` relative to CWD and will exit if it's not found.

Logs go to `data/cache/run.log`.

## Architecture

The pipeline has four sequential steps, all orchestrated by `run_all.py`:

1. **`pipeline/fetch_prices.py`** — downloads prices for 11 sector ETFs (XLK, XLF, XLV, …) plus SPY/QQQ/IWM via yfinance. Produces `prices_result` dict with per-ticker price, YTD, 6m/1y return, PE (trailing), dividend yield, 52w high/low.

2. **`pipeline/fetch_news.py`** — fetches RSS articles per sector using a 5-level fallback chain: Yahoo Finance → CNBC → MarketWatch → Google News → cache. Keywords per sector are defined in `config.json`. Returns articles annotated with source.

3. **`pipeline/sentiment.py`** — runs FinBERT (`ProsusAI/finbert`) on article text. Model loads once as a singleton. Annotates articles in-place and returns per-sector score/label/confidence.

4. **`pipeline/aggregate.py`** — merges all three results + `data/schwab_manual.json` → writes **only** `data/output.json` (human-readable full data).

**`config.json`** is the single source of truth: thresholds, model name, RSS URLs, sector tickers/keywords, output paths. Contains `output` section with `json_path`, `cache_dir`, `news_in_output`.

**`data/schwab_manual.json`** holds monthly manual Schwab sector ratings. Update monthly. Valid values: `Most Favored`, `More Favored`, `Neutral`, `Less Favored`, `Least Favored`. Keys starting with `_` are ignored (used for comments/metadata).

### output.json schema

The HTML (`docs/sp500-heatmap.html`) consumes this file via `fetch()` from Supabase Storage:

```
{
  "meta": { updated_at, market_date, articles_analyzed, run_status, warnings[], sources_used },
  "indices": { "SPY": { ytd, daily }, "QQQ": {...}, "IWM": {...} },
  "sectors": [ { ticker, sector_name, price, daily_change, ytd, six_month, one_year,
                  pe_fwd, pe_type, div_yield, p52_high, p52_low, schwab_rating,
                  sentiment: { score, label, confidence, pos_pct, neg_pct, neu_pct, available },
                  data_quality: { missing_fields[], sentiment_available, price_data_fresh, ... },
                  news: [ { title, source, url, published, summary, sentiment_label, sentiment_score } ]
                } ]
}
```

### Cloud Deployment

- **`.github/workflows/pipeline.yml`** — runs pipeline daily at 21:30 UTC, Monday–Friday. On success, uploads `data/output.json` to Supabase Storage bucket `heatmap-data` (public access). Requires GitHub Actions secrets: `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (set in the `production` environment).
- **`docs/sp500-heatmap.html`** — hosted on GitHub Pages. Fetches `output.json` from Supabase Storage public URL via `fetch()` with cache-busting (`?v=timestamp` + `cache: 'no-store'`). No local file dependency.
- **`actualizar.bat`** — manual local run for testing. Sets `PYTHONIOENCODING=utf-8` to prevent Windows encoding errors.

## Key design rules

- The pipeline **never crashes on missing data** — all failures go into `warnings[]` and `run_status` (`success` / `partial` / `failed`).
- `PYTHONIOENCODING=utf-8` is required on Windows to avoid encoding errors with `→` and `⚠` characters. Set in `actualizar.bat` and the GitHub Actions workflow.
- `forwardPE` is not available for ETFs in yfinance — the code silently falls back to `trailingPE`. This is expected behavior, not a bug.
- `data/output.json` is generated and gitignored. GitHub Actions uploads it to Supabase Storage bucket `heatmap-data` (public) after each successful run.
- `DATA_URL` in `docs/sp500-heatmap.html` must match the real Supabase project URL.
- The HTML uses `fetch()` with `?v=timestamp` + `cache: 'no-store'` for cache busting (Supabase CDN + browser cache).
- `prices.ytd_start` in `config.json` must be updated each January (e.g., `"2026-01-01"` → `"2027-01-01"`).
