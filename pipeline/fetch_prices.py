"""
Descarga precios, retornos y métricas fundamentales via yfinance.
Nunca lanza excepciones: todos los errores quedan en warnings[].
"""
import logging
from datetime import datetime

import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_history(ticker_obj, **kwargs):
    """Wrapper para yf.Ticker.history() que retorna None en caso de fallo."""
    try:
        df = ticker_obj.history(**kwargs)
        return df if not df.empty else None
    except Exception as e:
        return None


def _pct_change(df):
    """Retorno porcentual entre primer y último Close de un DataFrame."""
    if df is None or len(df) < 2:
        return None
    try:
        start = float(df["Close"].iloc[0])
        end   = float(df["Close"].iloc[-1])
        if start == 0:
            return None
        return round((end - start) / start * 100, 2)
    except Exception:
        return None


def fetch_ticker(ticker: str, cfg: dict) -> tuple[dict, list]:
    """
    Descarga todos los datos de precio para un ticker.
    Retorna (data_dict, warnings_list).
    """
    warnings = []
    data = {
        "price":        None,
        "daily_change": None,
        "ytd":          None,
        "six_month":    None,
        "one_year":     None,
        "pe_fwd":       None,
        "pe_type":      None,
        "div_yield":    None,
        "p52_high":     None,
        "p52_low":      None,
    }

    try:
        t = yf.Ticker(ticker)
    except Exception as e:
        warnings.append(f"{ticker}: no se pudo crear objeto yf.Ticker — {e}")
        return data, warnings

    # ── Precio actual y cambio diario ──────────────────────────────────────
    hist_2d = _safe_history(t, period="2d")
    if hist_2d is not None and len(hist_2d) >= 1:
        data["price"] = round(float(hist_2d["Close"].iloc[-1]), 2)
        if len(hist_2d) >= 2:
            prev = float(hist_2d["Close"].iloc[-2])
            if prev != 0:
                data["daily_change"] = round(
                    (data["price"] - prev) / prev * 100, 2
                )
            else:
                warnings.append(f"{ticker}: precio previo = 0, daily_change omitido")
        else:
            warnings.append(f"{ticker}: solo 1 día disponible — daily_change = null")
    else:
        warnings.append(f"{ticker}: sin datos de precio reciente")

    # ── YTD ───────────────────────────────────────────────────────────────
    ytd_start = cfg["prices"]["ytd_start"]
    hist_ytd = _safe_history(t, start=ytd_start)
    result_ytd = _pct_change(hist_ytd)
    if result_ytd is None:
        warnings.append(f"{ticker}: datos insuficientes para YTD desde {ytd_start}")
    data["ytd"] = result_ytd

    # ── 6 meses ────────────────────────────────────────────────────────────
    hist_6m = _safe_history(t, period=cfg["prices"]["history_period_6m"])
    result_6m = _pct_change(hist_6m)
    if result_6m is None:
        warnings.append(f"{ticker}: datos insuficientes para retorno 6M")
    data["six_month"] = result_6m

    # ── 1 año ──────────────────────────────────────────────────────────────
    hist_1y = _safe_history(t, period=cfg["prices"]["history_period_1y"])
    result_1y = _pct_change(hist_1y)
    if result_1y is None:
        warnings.append(f"{ticker}: datos insuficientes para retorno 1Y")
    data["one_year"] = result_1y

    # ── P/E ────────────────────────────────────────────────────────────────
    info = {}
    try:
        info = t.info or {}
    except Exception as e:
        warnings.append(f"{ticker}: t.info falló — {e} (pe y div_yield serán null)")

    pe_prefer = cfg["prices"]["pe_prefer"]
    try:
        fwd = info.get("forwardPE")
        trl = info.get("trailingPE")
        if pe_prefer == "forward" and fwd and float(fwd) > 0:
            data["pe_fwd"]  = round(float(fwd), 2)
            data["pe_type"] = "forward"
        elif trl and float(trl) > 0:
            data["pe_fwd"]  = round(float(trl), 2)
            data["pe_type"] = "trailing"
            if pe_prefer == "forward":
                warnings.append(
                    f"{ticker}: forwardPE no disponible → usando trailingPE"
                )
        else:
            warnings.append(f"{ticker}: pe_fwd y pe_trailing no disponibles")
    except Exception as e:
        warnings.append(f"{ticker}: error procesando P/E — {e}")

    # ── Dividend Yield ─────────────────────────────────────────────────────
    try:
        raw = info.get("dividendYield")
        if raw is not None and float(raw) > 0:
            data["div_yield"] = round(float(raw) * 100, 2)
        else:
            warnings.append(f"{ticker}: dividendYield no disponible o cero")
    except Exception as e:
        warnings.append(f"{ticker}: error procesando dividendYield — {e}")

    # ── Rango 52 semanas ──────────────────────────────────────────────────
    try:
        p52hi = info.get("fiftyTwoWeekHigh")
        p52lo = info.get("fiftyTwoWeekLow")
        data["p52_high"] = round(float(p52hi), 2) if p52hi else None
        data["p52_low"]  = round(float(p52lo), 2) if p52lo else None
        if not p52hi or not p52lo:
            warnings.append(f"{ticker}: rango 52 semanas no disponible")
    except Exception as e:
        warnings.append(f"{ticker}: error procesando rango 52 semanas — {e}")

    return data, warnings


def fetch_prices(cfg: dict) -> dict:
    """
    Descarga datos para todos los sectores e índices definidos en cfg.
    Siempre retorna un dict válido; los fallos quedan en warnings[].
    """
    sector_tickers = [s["ticker"] for s in cfg["sectors"]]
    index_tickers  = cfg.get("indices", ["SPY", "QQQ", "IWM"])
    all_warnings   = []
    sectors_data   = {}
    indices_data   = {}

    for ticker in sector_tickers + index_tickers:
        data, warns = fetch_ticker(ticker, cfg)
        all_warnings.extend(warns)
        if ticker in index_tickers:
            indices_data[ticker] = data
        else:
            sectors_data[ticker] = data

    return {
        "sectors":  sectors_data,
        "indices":  indices_data,
        "warnings": all_warnings,
    }
