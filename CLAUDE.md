# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Run the full pipeline (manual — with pause at end)
.\actualizar.bat

# Run the full pipeline (direct, no pause)
$env:PYTHONIOENCODING = "utf-8"; python run_all.py

# Install dependencies into the local venv
.\.venv\Scripts\pip install -r requirements.txt

# Run with the venv Python explicitly
.\.venv\Scripts\python run_all.py
```

Always run from the project root — `run_all.py` loads `config.json` relative to CWD and will exit if it's not found.

Logs go to `data/cache/run.log`. Scheduler logs go to `data/cache/scheduler.log`.

## Architecture

The pipeline has four sequential steps, all orchestrated by `run_all.py`:

1. **`pipeline/fetch_prices.py`** — downloads ETF prices via yfinance for all 11 sector ETFs (XLK, XLF, XLV, …) plus SPY/QQQ/IWM. Produces `prices_result` dict with per-ticker price, YTD, 6m/1y return, PE (forward preferred, trailing fallback — expected for ETFs), div yield, 52w high/low.

2. **`pipeline/fetch_news.py`** — fetches RSS articles per sector using a 5-level fallback chain: Yahoo Finance → CNBC → MarketWatch → Google News → cache. Keywords per sector are defined in `config.json`. Returns articles annotated with source.

3. **`pipeline/sentiment.py`** — runs FinBERT (`ProsusAI/finbert`) on article text. Model loads once as a singleton. Annotates articles in-place and returns per-sector score/label/confidence.

4. **`pipeline/aggregate.py`** — merges all three results + `data/schwab_manual.json` → writes two files:
   - `data/output.json` — human-readable full data
   - `data/data.js` — `window.SP500_DATA = {...};` assigned globally so `sp500-heatmap.html` works on `file://` without CORS issues

**`sp500-heatmap.html`** is fully standalone (no server). It reads `data/data.js` via a `<script>` tag, auto-reloads every 5 minutes by comparing `meta.updated_at` and re-renders in place without a page reload, showing a toast on update.

**`config.json`** is the single source of truth: thresholds, model name, RSS URLs, sector tickers/keywords, output paths. Modify it instead of touching Python constants.

**`data/schwab_manual.json`** holds monthly manual Schwab sector ratings. Keys starting with `_` are ignored (used for comments/metadata).

## Key design rules

- The pipeline **never crashes on missing data** — all failures go into `warnings[]` and `run_status` (`success` / `partial` / `failed`).
- `PYTHONIOENCODING=utf-8` must be set before running on Windows to avoid cp1252 errors with `→` and `⚠` characters. Both `.bat` files already do this.
- `forwardPE` is not available for ETFs in yfinance — the code silently falls back to `trailingPE`. This is expected behavior, not a bug.
- Task Scheduler runs `actualizar_scheduler.bat` daily (no pause, logs to scheduler.log, uses `%~dp0` for the working directory).
