"""
Descarga noticias por sector usando 5 niveles de fallback en orden de prioridad.
Nunca lanza excepciones: todos los errores quedan en warnings[].

Prioridad:
  1. Yahoo Finance RSS por ticker
  2. CNBC RSS + filtro keywords
  3. MarketWatch RSS + filtro keywords
  4. Google News RSS por query
  5. Cache del run anterior
"""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_feed(url: str, timeout: int, retries: int) -> list:
    """
    Descarga y parsea un feed RSS.
    Usa requests para controlar el timeout antes de pasar el contenido a feedparser.
    Retorna lista de entries (puede ser vacía).
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SP500Bot/1.0)"}
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if feed.entries:
                return feed.entries
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                raise e
    return []


def _keywords_match(entry: dict, keywords: list) -> bool:
    """True si title o summary contienen al menos un keyword (case-insensitive)."""
    text = (
        entry.get("title", "") + " " + entry.get("summary", "")
    ).lower()
    return any(kw.lower() in text for kw in keywords)


def _parse_published(entry) -> str | None:
    try:
        if entry.get("published_parsed"):
            return datetime(*entry.published_parsed[:6]).isoformat()
    except Exception:
        pass
    return None


def _to_article(entry) -> dict:
    source = ""
    if isinstance(entry.get("source"), dict):
        source = entry["source"].get("title", "")
    elif hasattr(entry, "source") and hasattr(entry.source, "title"):
        source = entry.source.title

    return {
        "title":           entry.get("title", "").strip(),
        "source":          source,
        "url":             entry.get("link", ""),
        "published":       _parse_published(entry),
        "summary":         entry.get("summary", "")[:400].strip(),
        "sentiment_label": None,
        "sentiment_score": None,
    }


def _dedup(articles: list) -> list:
    """Elimina duplicados por URL."""
    seen = set()
    out  = []
    for a in articles:
        key = a.get("url", "")
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out


# ── Cache ────────────────────────────────────────────────────────────────────

def _cache_path(ticker: str, cache_dir: Path) -> Path | None:
    files = sorted(cache_dir.glob(f"news_{ticker}_*.json"), reverse=True)
    return files[0] if files else None


def _load_cache(ticker: str, cache_dir: Path) -> list:
    path = _cache_path(ticker, cache_dir)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_cache(ticker: str, articles: list, cache_dir: Path):
    cache_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    path = cache_dir / f"news_{ticker}_{date_str}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"No se pudo guardar cache para {ticker}: {e}")


# ── Fetch por sector ─────────────────────────────────────────────────────────

def fetch_news_sector(sector_cfg: dict, cfg: dict) -> dict:
    """
    Intenta obtener noticias para un sector usando 5 niveles de fallback.
    Retorna dict con articles, source_breakdown y warnings.
    """
    ticker   = sector_cfg["ticker"]
    keywords = sector_cfg.get("keywords", [])
    feeds    = cfg["rss_feeds"]
    timeout  = cfg["news"]["rss_timeout_seconds"]
    retries  = cfg["news"]["rss_retry_attempts"]
    max_art  = cfg["news"]["max_articles_per_sector"]
    cache_dir = Path(cfg["output"]["cache_dir"])

    warnings = []
    articles = []
    source_breakdown = {
        "yahoo_rss":      0,
        "cnbc_rss":       0,
        "marketwatch_rss":0,
        "google_news_rss":0,
        "cache_fallback": 0,
    }

    # ── Prioridad 1: Yahoo Finance RSS por ticker ─────────────────────────
    try:
        url     = feeds["yahoo_template"].format(ticker=ticker)
        entries = _get_feed(url, timeout, retries)
        new_art = [_to_article(e) for e in entries]
        articles.extend(new_art)
        source_breakdown["yahoo_rss"] = len(new_art)
        if not new_art:
            warnings.append(f"{ticker}: Yahoo RSS retornó feed vacío")
    except Exception as e:
        warnings.append(f"{ticker}: Yahoo RSS falló — {e}")

    # ── Prioridad 2: CNBC RSS + filtro keywords ──────────────────────────
    if len(articles) < 5:
        try:
            entries  = _get_feed(feeds["cnbc"], timeout, retries)
            filtered = [_to_article(e) for e in entries if _keywords_match(e, keywords)]
            need     = max(0, max_art - len(articles))
            articles.extend(filtered[:need])
            source_breakdown["cnbc_rss"] = len(filtered[:need])
            if not filtered:
                warnings.append(f"{ticker}: CNBC RSS sin resultados para keywords")
        except Exception as e:
            warnings.append(f"{ticker}: CNBC RSS falló — {e}")

    # ── Prioridad 3: MarketWatch RSS + filtro keywords ───────────────────
    if len(articles) < 5:
        try:
            entries  = _get_feed(feeds["marketwatch"], timeout, retries)
            filtered = [_to_article(e) for e in entries if _keywords_match(e, keywords)]
            need     = max(0, max_art - len(articles))
            articles.extend(filtered[:need])
            source_breakdown["marketwatch_rss"] = len(filtered[:need])
            if not filtered:
                warnings.append(f"{ticker}: MarketWatch RSS sin resultados para keywords")
        except Exception as e:
            warnings.append(f"{ticker}: MarketWatch RSS falló — {e}")

    # ── Prioridad 4: Google News RSS ─────────────────────────────────────
    if len(articles) < 3:
        try:
            query   = quote_plus(f"{ticker} {keywords[0] if keywords else 'stocks'} stock market")
            url     = feeds["google_news_template"].format(query=query)
            entries = _get_feed(url, timeout, retries)
            need    = max(0, max_art - len(articles))
            new_art = [_to_article(e) for e in entries[:need]]
            articles.extend(new_art)
            source_breakdown["google_news_rss"] = len(new_art)
            if new_art:
                warnings.append(f"{ticker}: usó Google News RSS como fallback (prioridad 4)")
            else:
                warnings.append(f"{ticker}: Google News RSS también vacío")
        except Exception as e:
            warnings.append(f"{ticker}: Google News RSS falló — {e}")

    # ── Prioridad 5: Cache del run anterior ───────────────────────────────
    if not articles:
        cached = _load_cache(ticker, cache_dir)
        if cached:
            articles = cached
            source_breakdown["cache_fallback"] = len(cached)
            warnings.append(
                f"{ticker}: todas las fuentes live fallaron → usando cache del run anterior"
            )
        else:
            warnings.append(
                f"{ticker}: sin artículos disponibles y sin cache — sentiment será null"
            )

    articles = _dedup(articles)[:max_art]

    if articles:
        _save_cache(ticker, articles, cache_dir)

    return {
        "articles":         articles,
        "source_breakdown": source_breakdown,
        "warnings":         warnings,
    }


def fetch_all_news(cfg: dict) -> dict:
    """
    Descarga noticias para todos los sectores definidos en cfg.
    Siempre retorna un dict válido; los fallos quedan en warnings[].
    """
    all_warnings = []
    by_sector    = {}

    for sector in cfg["sectors"]:
        ticker = sector["ticker"]
        result = fetch_news_sector(sector, cfg)
        by_sector[ticker] = result
        all_warnings.extend(result["warnings"])
        count = len(result["articles"])
        logger.info(f"  {ticker}: {count} artículos | fuentes: {result['source_breakdown']}")

    return {"by_sector": by_sector, "warnings": all_warnings}
