"""
Combina los resultados de fetch_prices, fetch_news y sentiment en output.json.
También escribe data/data.js para que el HTML lo consuma sin servidor (file://).
Nunca lanza excepciones: los fallos quedan en warnings[] y run_status.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_schwab(cfg: dict) -> dict:
    """Carga ratings manuales de Schwab. Retorna {} si el archivo no existe."""
    path = Path("data/schwab_manual.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Filtrar keys internas del JSON (comienzan con _)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except FileNotFoundError:
        logger.warning("schwab_manual.json no encontrado → schwab_rating = N/A para todos")
        return {}
    except Exception as e:
        logger.warning(f"Error leyendo schwab_manual.json: {e}")
        return {}


def _missing_fields(price: dict, sentiment: dict) -> list:
    """Lista de campos ausentes o null en los datos de un sector."""
    missing = []
    for field in ["price", "daily_change", "ytd", "six_month", "one_year",
                  "pe_fwd", "div_yield"]:
        if price.get(field) is None:
            missing.append(field)
    if not sentiment.get("available", False):
        missing.append("sentiment")
    return missing


def _news_freshness_hours(articles: list) -> float | None:
    """Horas desde el artículo más antiguo en la lista."""
    dates = []
    for a in articles:
        pub = a.get("published")
        if pub:
            try:
                dates.append(datetime.fromisoformat(pub))
            except Exception:
                pass
    if not dates:
        return None
    oldest = min(dates)
    return round((datetime.now() - oldest).total_seconds() / 3600, 1)


def _determine_run_status(all_warnings: list, sectors: list) -> str:
    """
    "success"  → todo OK o solo warnings menores
    "partial"  → ≥3 sectores sin precio, o ≥3 sectores sin sentimiento
    "failed"   → sin datos de precios y sin noticias en la mayoría de sectores
    """
    no_price = sum(1 for s in sectors if s["data_quality"]["price_data_fresh"] is False)
    no_sent  = sum(1 for s in sectors if not s["data_quality"]["sentiment_available"])
    total    = len(sectors)

    if no_price >= total:
        return "failed"
    if no_price >= 3 or no_sent >= total:
        return "partial"
    return "success"


def build_output(cfg: dict,
                 prices_result: dict,
                 news_result: dict,
                 sentiment_results: dict) -> dict:
    """Arma el JSON final fusionando todas las fuentes."""
    all_warnings = []
    all_warnings.extend(prices_result.get("warnings", []))
    all_warnings.extend(news_result.get("warnings",   []))

    schwab            = _load_schwab(cfg)
    sectors_out       = []
    news_in_output    = cfg["output"]["news_in_output"]
    sources_news_used = {}

    for sector_cfg in cfg["sectors"]:
        ticker     = sector_cfg["ticker"]
        price      = prices_result["sectors"].get(ticker, {})
        news_data  = news_result["by_sector"].get(ticker, {})
        sentiment  = sentiment_results.get(ticker, {})

        articles         = news_data.get("articles", [])
        source_breakdown = news_data.get("source_breakdown", {})
        sources_news_used[ticker] = [k for k, v in source_breakdown.items() if v > 0]

        missing = _missing_fields(price, sentiment)

        # Avisar si la muestra de artículos es baja
        min_art = cfg["sentiment"]["min_articles_for_confidence"]
        if 0 < len(articles) < min_art:
            all_warnings.append(
                f"{ticker}: solo {len(articles)} artículos analizados "
                f"(mínimo recomendado: {min_art}) — confidence puede ser baja"
            )

        sector_entry = {
            "ticker":         ticker,
            "sector_name":    sector_cfg["sector_name"],
            "sector_name_en": sector_cfg["sector_name_en"],
            "market_weight":  sector_cfg.get("market_weight_default"),

            # Precios
            "price":        price.get("price"),
            "daily_change": price.get("daily_change"),
            "ytd":          price.get("ytd"),
            "six_month":    price.get("six_month"),
            "one_year":     price.get("one_year"),
            "pe_fwd":       price.get("pe_fwd"),
            "pe_type":      price.get("pe_type"),
            "div_yield":    price.get("div_yield"),
            "p52_high":     price.get("p52_high"),
            "p52_low":      price.get("p52_low"),

            # Schwab (manual)
            "schwab_rating": schwab.get(ticker, "N/A"),

            # Sentimiento
            "sentiment": {
                "score":              sentiment.get("score"),
                "label":              sentiment.get("label", "unavailable"),
                "confidence":         sentiment.get("confidence"),
                "articles_count":     sentiment.get("articles_count", 0),
                "analyzed_count":     sentiment.get("analyzed_count", 0),
                "pos_pct":            sentiment.get("pos_pct"),
                "neg_pct":            sentiment.get("neg_pct"),
                "neu_pct":            sentiment.get("neu_pct"),
                "available":          sentiment.get("available", False),
                "low_sample_warning": sentiment.get("low_sample_warning", False),
            },

            "source_breakdown": source_breakdown,

            "data_quality": {
                "missing_fields":      missing,
                "pe_type":             price.get("pe_type"),
                "news_freshness_hours":_news_freshness_hours(articles),
                "sentiment_available": sentiment.get("available", False),
                "price_data_fresh":    price.get("price") is not None,
                "articles_count":      len(articles),
            },

            # Top N noticias con sentimiento anotado
            "news": articles[:news_in_output],
        }

        sectors_out.append(sector_entry)

    # ── Índices ───────────────────────────────────────────────────────────
    indices_out = {}
    for idx in cfg.get("indices", ["SPY", "QQQ", "IWM"]):
        idx_data = prices_result["indices"].get(idx, {})
        indices_out[idx] = {
            "ytd":   idx_data.get("ytd"),
            "daily": idx_data.get("daily_change"),
        }
        if idx_data.get("ytd") is None:
            all_warnings.append(f"Índice {idx}: YTD no disponible")

    run_status   = _determine_run_status(all_warnings, sectors_out)
    total_art    = sum(s["sentiment"]["articles_count"] for s in sectors_out)

    return {
        "meta": {
            "updated_at":       datetime.now().isoformat(timespec="seconds"),
            "market_date":      datetime.now().strftime("%Y-%m-%d"),
            "articles_analyzed":total_art,
            "run_status":       run_status,
            "warnings":         all_warnings,
            "sources_used": {
                "prices":          "yfinance",
                "sentiment_model": cfg["sentiment"]["model"],
                "schwab":          "schwab_manual.json"
                                   if Path("data/schwab_manual.json").exists()
                                   else "N/A (archivo no encontrado)",
                "news_by_sector":  sources_news_used,
            },
        },
        "indices": indices_out,
        "sectors": sectors_out,
    }


def write_outputs(data: dict, cfg: dict):
    """
    Escribe data/output.json (legible) y data/data.js (consumido por el HTML).
    data.js usa window.SP500_DATA para funcionar sin servidor (file:// protocol).
    """
    # output.json
    json_path = Path(cfg["output"]["json_path"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Escrito: {json_path}")

    # data.js
    js_path = Path(cfg["output"]["js_path"])
    js_path.parent.mkdir(parents=True, exist_ok=True)
    json_inline = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    js_content  = (
        f"// Auto-generado por aggregate.py — {data['meta']['updated_at']}\n"
        f"// NO editar manualmente\n"
        f"window.SP500_DATA = {json_inline};\n"
    )
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js_content)
    logger.info(f"Escrito: {js_path}")
