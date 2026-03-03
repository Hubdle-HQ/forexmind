"""
Technical indicator calculator — RSI, EMA, ATR from OHLCV candles.
Structure detection — HH/HL, EMA cross, Asian range, etc.
Uses pandas and pandas-ta only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

MIN_CANDLES = 50
MIN_STRUCTURE_CANDLES = 10


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


def get_pair_pip_threshold(pair: str) -> float:
    """Returns correct pip threshold for at_ema_20 check."""
    if "JPY" in pair.upper():
        return 0.05
    return 0.0005


def detect_structure(
    candles: list[dict[str, Any]],
    indicators: dict[str, Any],
    pair: str = "",
) -> dict[str, Any]:
    """
    Takes raw candles + calculated indicators from Week 1.
    Returns coded structural facts — no LLM involved.
    All logic is pure Python rules, not estimation.

    Returns:
    {
        "hh_hl": bool,           # Higher highs + higher lows = uptrend structure
        "ll_lh": bool,           # Lower lows + lower highs = downtrend structure
        "ema_cross": "bullish"|"bearish"|"none",  # EMA20 crossed EMA50 in last 3 candles
        "broke_asian_range": "up"|"down"|"none",  # Price broke above/below Asian session range
        "at_ema_20": bool,       # Current price within threshold of EMA20 (pullback zone)
        "structure_bias": "bullish"|"bearish"|"neutral"  # Overall coded bias
    }
    """
    result: dict[str, Any] = {
        "hh_hl": False,
        "ll_lh": False,
        "ema_cross": "none",
        "broke_asian_range": "none",
        "at_ema_20": False,
        "structure_bias": "neutral",
    }

    if len(candles) < MIN_STRUCTURE_CANDLES:
        logger.warning("detect_structure: need at least %d candles, got %d", MIN_STRUCTURE_CANDLES, len(candles))
        return result

    normalized = [_normalize_candle(c) for c in candles]
    highs = [c["high"] for c in normalized]
    lows = [c["low"] for c in normalized]
    current_price = indicators.get("current_price") or (normalized[-1]["close"] if normalized else 0.0)
    ema_20 = indicators.get("ema_20")
    ema_50 = indicators.get("ema_50")
    rsi_zone = indicators.get("rsi_zone") or "neutral"

    # HH/HL and LL/LH
    try:
        high_last, high_3 = highs[-1], highs[-3]
        low_last, low_3 = lows[-1], lows[-3]
        result["hh_hl"] = high_last > high_3 and low_last > low_3
        result["ll_lh"] = high_last < high_3 and low_last < low_3
    except (IndexError, TypeError) as e:
        logger.warning("detect_structure HH/HL failed: %s", e)

    # EMA cross in last 3 candles
    try:
        if ema_20 is not None and ema_50 is not None:
            df = pd.DataFrame(normalized)
            import pandas_ta as ta
            ema20_series = ta.ema(df["close"], length=20)
            ema50_series = ta.ema(df["close"], length=50)
            if ema20_series is not None and ema50_series is not None and len(ema20_series) >= 3 and len(ema50_series) >= 3:
                e20_prev = float(ema20_series.iloc[-3])
                e50_prev = float(ema50_series.iloc[-3])
                e20_now = float(ema20_series.iloc[-1])
                e50_now = float(ema50_series.iloc[-1])
                if e20_prev <= e50_prev and e20_now > e50_now:
                    result["ema_cross"] = "bullish"
                elif e20_prev >= e50_prev and e20_now < e50_now:
                    result["ema_cross"] = "bearish"
    except Exception as e:
        logger.warning("detect_structure EMA cross failed: %s", e)

    # Asian range (UTC 22:00 to 07:00)
    try:
        asian_highs: list[float] = []
        asian_lows: list[float] = []
        for i, c in enumerate(candles):
            t = c.get("time")
            if not t:
                continue
            try:
                s = str(t).replace("Z", "+00:00").split(".")[0]
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                hour = dt.hour
                if hour >= 22 or hour <= 7:
                    asian_highs.append(normalized[i]["high"])
                    asian_lows.append(normalized[i]["low"])
            except (ValueError, TypeError, IndexError):
                continue
        if asian_highs and asian_lows:
            asian_high = max(asian_highs)
            asian_low = min(asian_lows)
            if current_price > asian_high:
                result["broke_asian_range"] = "up"
            elif current_price < asian_low:
                result["broke_asian_range"] = "down"
    except Exception as e:
        logger.warning("detect_structure Asian range failed: %s", e)

    # at_ema_20
    try:
        if ema_20 is not None:
            threshold = get_pair_pip_threshold(pair) if pair else 0.0005
            result["at_ema_20"] = abs(float(current_price) - float(ema_20)) < threshold
    except (TypeError, ValueError) as e:
        logger.warning("detect_structure at_ema_20 failed: %s", e)

    # structure_bias
    try:
        hh_hl = result["hh_hl"]
        ll_lh = result["ll_lh"]
        ema_cross = result["ema_cross"]
        if (hh_hl or ema_cross == "bullish") and rsi_zone != "overbought":
            result["structure_bias"] = "bullish"
        elif (ll_lh or ema_cross == "bearish") and rsi_zone != "oversold":
            result["structure_bias"] = "bearish"
    except Exception as e:
        logger.warning("detect_structure structure_bias failed: %s", e)

    return result
