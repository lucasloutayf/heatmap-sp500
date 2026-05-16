"""
Análisis de sentimiento financiero usando FinBERT (ProsusAI/finbert).
El modelo se carga una sola vez y queda en memoria para el resto del run.
Los thresholds de clasificación vienen exclusivamente de cfg["sentiment"].
Nunca lanza excepciones: los fallos quedan reflejados en el dict retornado.
"""
import logging

logger = logging.getLogger(__name__)

_MODEL_PIPELINE = None  # singleton: se instancia en la primera llamada


def _load_model(model_name: str):
    """Carga el pipeline de FinBERT una sola vez. Retorna None si falla."""
    global _MODEL_PIPELINE
    if _MODEL_PIPELINE is not None:
        return _MODEL_PIPELINE
    try:
        from transformers import pipeline as hf_pipeline
        logger.info(f"Cargando modelo '{model_name}' (descarga única ~440 MB en primer run)...")
        _MODEL_PIPELINE = hf_pipeline(
            "text-classification",
            model=model_name,
            top_k=None,   # retorna scores para las 3 clases
            device=-1,    # CPU; cambiar a 0 si hay GPU disponible
            truncation=True,
        )
        logger.info("Modelo cargado correctamente.")
        return _MODEL_PIPELINE
    except Exception as e:
        logger.error(f"No se pudo cargar FinBERT '{model_name}': {e}")
        logger.error("El sentimiento quedará como 'unavailable' para todos los sectores.")
        return None


def _run_inference(pipe, text: str, max_len: int) -> dict | None:
    """
    Ejecuta FinBERT sobre un texto.
    Retorna dict {positive, negative, neutral} o None si falla.
    """
    try:
        text = text.strip()[:max_len]
        if not text:
            return None
        result = pipe(text)
        # result: [[{label, score}, {label, score}, {label, score}]]
        raw = result[0] if isinstance(result[0], list) else result
        return {item["label"].lower(): item["score"] for item in raw}
    except Exception as e:
        logger.debug(f"Error en inferencia individual: {e}")
        return None


def _null_sentiment(articles_count: int) -> dict:
    return {
        "score":               None,
        "label":               "unavailable",
        "confidence":          None,
        "articles_count":      articles_count,
        "analyzed_count":      0,
        "pos_pct":             None,
        "neg_pct":             None,
        "neu_pct":             None,
        "available":           False,
        "low_sample_warning":  False,
    }


def compute_sector_sentiment(articles: list, cfg: dict) -> dict:
    """
    Corre FinBERT sobre todos los artículos de un sector.
    Anota cada artículo in-place con sentiment_label y sentiment_score.
    Retorna dict de sentimiento agregado a nivel sector.
    """
    sent_cfg      = cfg["sentiment"]
    model_name    = sent_cfg["model"]
    threshold_pos = sent_cfg["threshold_bullish"]
    threshold_neg = sent_cfg["threshold_bearish"]
    min_articles  = sent_cfg["min_articles_for_confidence"]
    max_len       = sent_cfg["max_text_length"]

    if not articles:
        return _null_sentiment(0)

    pipe = _load_model(model_name)
    if pipe is None:
        return _null_sentiment(len(articles))

    scores_list = []
    labels_list = []
    confs_list  = []

    for article in articles:
        text = (
            article.get("title", "") + " " + article.get("summary", "")
        ).strip()

        scores = _run_inference(pipe, text, max_len)
        if scores is None:
            continue

        pos = scores.get("positive", 0.0)
        neg = scores.get("negative", 0.0)
        neu = scores.get("neutral",  0.0)

        article_score = pos - neg
        article_label = max(scores, key=scores.get)
        article_conf  = max(pos, neg, neu)

        scores_list.append(article_score)
        labels_list.append(article_label)
        confs_list.append(article_conf)

        # Anotar el artículo en lugar para que aggregate.py lo persista
        article["sentiment_score"] = round(article_score, 4)
        article["sentiment_label"] = article_label

    if not scores_list:
        return _null_sentiment(len(articles))

    analyzed = len(scores_list)
    avg_score = sum(scores_list) / analyzed
    avg_conf  = sum(confs_list)  / analyzed

    pos_pct = round(labels_list.count("positive") / analyzed * 100)
    neg_pct = round(labels_list.count("negative") / analyzed * 100)
    neu_pct = 100 - pos_pct - neg_pct  # evitar redondeo inconsistente

    if avg_score > threshold_pos:
        label = "bullish"
    elif avg_score < threshold_neg:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "score":              round(avg_score, 4),
        "label":              label,
        "confidence":         round(avg_conf, 4),
        "articles_count":     len(articles),
        "analyzed_count":     analyzed,
        "pos_pct":            pos_pct,
        "neg_pct":            neg_pct,
        "neu_pct":            neu_pct,
        "available":          True,
        "low_sample_warning": analyzed < min_articles,
    }
