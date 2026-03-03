"""
Technical indicator calculator — RSI, EMA, ATR from OHLCV candles.
Uses pandas and pandas-ta only.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

MIN_CANDLES = 50


def _normalize_candle(c: dict[str, Any]) -> dict[str, float]:
    """Normalize OANDA (o,h,l,c) or standard (open,high,low,close) to standard keys."""
    o = c.get("open") or c.get("o", 0)
    h = c.get("high") or c.get("h", 0)
    l = c.get("low") or c.get("l", 0)
    cl = c.get("close") or c.get("c", 0)
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(cl)}


def calculate_indicators(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Takes raw OANDA H1 candles (OHLCV dicts) and returns
    calculated indicator values as a clean dict.

    Input candle format:
    { "time": str, "open": float, "high": float,
      "low": float, "close": float, "volume": int }
    Or OANDA format: { "o", "h", "l", "c", "volume" }

    Returns:
    {
        "rsi_14": float,           # RSI value 0-100
        "ema_20": float,           # EMA 20 value
        "ema_50": float,           # EMA 50 value
        "atr_14": float,           # ATR 14 value
        "ema_trend": "bullish"|"bearish"|"neutral",  # EMA20 vs EMA50
        "rsi_zone": "overbought"|"oversold"|"neutral",  # >70 / <30 / middle
        "current_price": float,    # last close
        "candle_count": int        # number of candles used
    }
    """
    if len(candles) < MIN_CANDLES:
        raise ValueError(f"Minimum {MIN_CANDLES} candles required, got {len(candles)}")

    normalized = [_normalize_candle(c) for c in candles]
    df = pd.DataFrame(normalized)

    result: dict[str, Any] = {
        "rsi_14": None,
        "ema_20": None,
        "ema_50": None,
        "atr_14": None,
        "ema_trend": "neutral",
        "rsi_zone": "neutral",
        "current_price": float(df["close"].iloc[-1]) if len(df) > 0 else 0.0,
        "candle_count": len(candles),
    }

    try:
        import pandas_ta as ta

        rsi = ta.rsi(df["close"], length=14)
        if rsi is not None and len(rsi) > 0 and pd.notna(rsi.iloc[-1]):
            result["rsi_14"] = round(float(rsi.iloc[-1]), 2)
            if result["rsi_14"] > 70:
                result["rsi_zone"] = "overbought"
            elif result["rsi_14"] < 30:
                result["rsi_zone"] = "oversold"
    except Exception as e:
        logger.warning("pandas-ta RSI calculation failed: %s", e)

    try:
        import pandas_ta as ta

        ema_20 = ta.ema(df["close"], length=20)
        ema_50 = ta.ema(df["close"], length=50)
        if ema_20 is not None and len(ema_20) > 0 and pd.notna(ema_20.iloc[-1]):
            result["ema_20"] = round(float(ema_20.iloc[-1]), 5)
        if ema_50 is not None and len(ema_50) > 0 and pd.notna(ema_50.iloc[-1]):
            result["ema_50"] = round(float(ema_50.iloc[-1]), 5)
        if result["ema_20"] is not None and result["ema_50"] is not None:
            diff = abs(result["ema_20"] - result["ema_50"])
            if diff <= 0.0001:
                result["ema_trend"] = "neutral"
            elif result["ema_20"] > result["ema_50"]:
                result["ema_trend"] = "bullish"
            else:
                result["ema_trend"] = "bearish"
    except Exception as e:
        logger.warning("pandas-ta EMA calculation failed: %s", e)

    try:
        import pandas_ta as ta

        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        if atr is not None and len(atr) > 0 and pd.notna(atr.iloc[-1]):
            result["atr_14"] = round(float(atr.iloc[-1]), 5)
    except Exception as e:
        logger.warning("pandas-ta ATR calculation failed: %s", e)

    return result
