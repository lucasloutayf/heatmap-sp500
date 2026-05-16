"""
Orquestador del pipeline S&P 500 Heatmap.
Ejecutar desde la raíz del proyecto: python run_all.py
"""
import json
import logging
import sys
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
Path("data/cache").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/cache/run.log", encoding="utf-8"),
    ],
)
# Forzar UTF-8 en la consola de Windows para evitar UnicodeEncodeError con caracteres especiales
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
logger = logging.getLogger("run_all")


def load_config() -> dict:
    try:
        with open("config.json", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("config.json no encontrado. ¿Estás ejecutando desde la raíz del proyecto?")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"config.json tiene formato JSON inválido: {e}")
        sys.exit(1)


def main():
    logger.info("=" * 60)
    logger.info("  S&P 500 Heatmap — Iniciando pipeline")
    logger.info("=" * 60)

    cfg = load_config()

    # ── Step 1: Precios ───────────────────────────────────────────────────
    logger.info("PASO 1/4 — Descargando precios (yfinance)...")
    try:
        from pipeline.fetch_prices import fetch_prices
        prices_result = fetch_prices(cfg)
        n_warns = len(prices_result["warnings"])
        logger.info(f"  → Completado. Warnings: {n_warns}")
    except Exception as e:
        logger.error(f"  → FALLO CRÍTICO en fetch_prices: {e}")
        prices_result = {"sectors": {}, "indices": {}, "warnings": [f"FALLO CRÍTICO fetch_prices: {e}"]}

    # ── Step 2: Noticias ──────────────────────────────────────────────────
    logger.info("PASO 2/4 — Descargando noticias (RSS con fallback)...")
    try:
        from pipeline.fetch_news import fetch_all_news
        news_result = fetch_all_news(cfg)
        total_art = sum(len(v["articles"]) for v in news_result["by_sector"].values())
        n_warns   = len(news_result["warnings"])
        logger.info(f"  → {total_art} artículos recolectados. Warnings: {n_warns}")
    except Exception as e:
        logger.error(f"  → FALLO CRÍTICO en fetch_news: {e}")
        news_result = {
            "by_sector": {s["ticker"]: {"articles": [], "source_breakdown": {}, "warnings": []}
                          for s in cfg["sectors"]},
            "warnings": [f"FALLO CRÍTICO fetch_news: {e}"],
        }

    # ── Step 3: Sentimiento ───────────────────────────────────────────────
    logger.info("PASO 3/4 — Calculando sentimiento con FinBERT...")
    sentiment_results = {}
    try:
        from pipeline.sentiment import compute_sector_sentiment
        for sector in cfg["sectors"]:
            ticker   = sector["ticker"]
            articles = news_result["by_sector"].get(ticker, {}).get("articles", [])
            result   = compute_sector_sentiment(articles, cfg)
            sentiment_results[ticker] = result
            logger.info(
                f"  {ticker}: {result['label']} "
                f"(score={result['score']}, analiz.={result.get('analyzed_count', 0)}/{result['articles_count']})"
            )
    except Exception as e:
        logger.error(f"  → FALLO CRÍTICO en sentiment: {e}")
        for sector in cfg["sectors"]:
            sentiment_results[sector["ticker"]] = {
                "score": None, "label": "unavailable", "confidence": None,
                "articles_count": 0, "analyzed_count": 0,
                "pos_pct": None, "neg_pct": None, "neu_pct": None,
                "available": False, "low_sample_warning": False,
            }

    # ── Step 4: Agregación y escritura ────────────────────────────────────
    logger.info("PASO 4/4 — Generando output.json...")
    try:
        from pipeline.aggregate import build_output, write_outputs
        output = build_output(cfg, prices_result, news_result, sentiment_results)
        write_outputs(output, cfg)
    except Exception as e:
        logger.error(f"  → FALLO CRÍTICO en aggregate: {e}")
        sys.exit(1)

    # ── Resumen final ─────────────────────────────────────────────────────
    status   = output["meta"]["run_status"]
    n_warns  = len(output["meta"]["warnings"])
    art_tot  = output["meta"]["articles_analyzed"]

    logger.info("=" * 60)
    logger.info(f"  COMPLETADO — status: {status.upper()} | warnings: {n_warns} | artículos: {art_tot}")
    logger.info("=" * 60)

    if output["meta"]["warnings"]:
        logger.info("Warnings del run:")
        for w in output["meta"]["warnings"]:
            logger.info(f"  ⚠  {w}")

    if status == "failed":
        logger.error("El pipeline terminó en estado FAILED. Revisa los warnings.")
        sys.exit(1)


if __name__ == "__main__":
    main()
