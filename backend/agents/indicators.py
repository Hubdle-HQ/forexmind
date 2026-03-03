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


def calculate_levels(
    entry_price: float,
    direction: str,
    atr: float,
    pair: str,
    atr_sl_multiplier: float = 1.5,
    rr_ratio: float = 2.0,
) -> dict[str, Any]:
    """
    Calculates mathematically correct SL and TP levels using ATR.
    Guarantees fixed R:R ratio every time.

    Rules:
    - SL distance = ATR * atr_sl_multiplier (default 1.5x ATR)
    - TP distance = SL distance * rr_ratio (default 2.0 = 1:2 R:R)
    - BUY:  SL = entry - sl_distance, TP = entry + tp_distance
    - SELL: SL = entry + sl_distance, TP = entry - tp_distance
    - Round to correct decimal places: JPY pairs 3 decimals, others 5 decimals

    Returns:
    {
        "entry_price": float,
        "stop_loss": float,
        "take_profit": float,
        "sl_distance": float,
        "tp_distance": float,
        "risk_reward_ratio": float,
        "atr_used": float,
        "pip_value": float
    }
    """
    if direction not in ("BUY", "SELL"):
        raise ValueError(f"direction must be BUY or SELL, got {direction}")
    if atr is None or float(atr) <= 0:
        raise ValueError(f"atr must be > 0, got {atr}")

    atr_f = float(atr)
    sl_distance = atr_f * atr_sl_multiplier
    tp_distance = sl_distance * rr_ratio

    is_jpy = "JPY" in pair.upper()
    decimals = 3 if is_jpy else 5
    pip_size = 0.01 if is_jpy else 0.0001
    pip_value = round(sl_distance / pip_size, 1)

    if direction == "BUY":
        stop_loss = round(entry_price - sl_distance, decimals)
        take_profit = round(entry_price + tp_distance, decimals)
    else:
        stop_loss = round(entry_price + sl_distance, decimals)
        take_profit = round(entry_price - tp_distance, decimals)

    result = {
        "entry_price": round(entry_price, decimals),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "sl_distance": sl_distance,
        "tp_distance": tp_distance,
        "risk_reward_ratio": rr_ratio,
        "atr_used": atr_f,
        "pip_value": pip_value,
    }
    logger.info(
        "ATR levels for %s: Entry %s SL %s TP %s R:R 1:%s",
        pair,
        result["entry_price"],
        result["stop_loss"],
        result["take_profit"],
        int(rr_ratio),
    )
    return result


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


MIN_MTF_CANDLES = 10


def analyse_timeframes(
    h1_candles: list[dict[str, Any]],
    h4_candles: list[dict[str, Any]],
    d1_candles: list[dict[str, Any]],
    pair: str,
) -> dict[str, Any]:
    """
    Analyses D1, H4, H1 candles independently.
    Returns structured timeframe context.
    ALL logic is coded rules — no LLM.

    Returns:
    {
        "d1_bias": "bullish"|"bearish"|"neutral",
        "d1_ema_trend": "bullish"|"bearish"|"neutral",
        "h4_structure": "bullish"|"bearish"|"neutral",
        "h4_ema_trend": "bullish"|"bearish"|"neutral",
        "h1_direction": "bullish"|"bearish"|"neutral",
        "timeframe_alignment": "full"|"partial"|"conflict",
        "conflict_detected": bool,
        "conflict_reason": str | None,
        "tradeable": bool
    }
    """
    result: dict[str, Any] = {
        "d1_bias": "neutral",
        "d1_ema_trend": "neutral",
        "h4_structure": "neutral",
        "h4_ema_trend": "neutral",
        "h1_direction": "neutral",
        "timeframe_alignment": "partial",
        "conflict_detected": False,
        "conflict_reason": None,
        "tradeable": True,
    }

    pip_thresh = get_pair_pip_threshold(pair)
    d1_neutral_thresh = pip_thresh * 0.4

    # D1 bias (big picture trend)
    try:
        if len(d1_candles) >= MIN_MTF_CANDLES:
            norm_d1 = [_normalize_candle(c) for c in d1_candles]
            df_d1 = pd.DataFrame(norm_d1)
            import pandas_ta as ta
            ema20_d1 = ta.ema(df_d1["close"], length=20)
            ema50_d1 = ta.ema(df_d1["close"], length=50)
            if ema20_d1 is not None and ema50_d1 is not None and len(ema20_d1) > 0 and len(ema50_d1) > 0:
                e20 = float(ema20_d1.iloc[-1])
                e50 = float(ema50_d1.iloc[-1])
                diff = abs(e20 - e50)
                if diff <= d1_neutral_thresh:
                    result["d1_bias"] = "neutral"
                    result["d1_ema_trend"] = "neutral"
                elif e20 > e50:
                    result["d1_bias"] = "bullish"
                    result["d1_ema_trend"] = "bullish"
                else:
                    result["d1_bias"] = "bearish"
                    result["d1_ema_trend"] = "bearish"
        else:
            logger.warning("analyse_timeframes: D1 candles < %d, using neutral", MIN_MTF_CANDLES)
    except Exception as e:
        logger.warning("analyse_timeframes D1 failed: %s", e)

    # H4 structure (setup context)
    try:
        if len(h4_candles) >= MIN_MTF_CANDLES:
            norm_h4 = [_normalize_candle(c) for c in h4_candles]
            df_h4 = pd.DataFrame(norm_h4)
            import pandas_ta as ta
            ema20_h4 = ta.ema(df_h4["close"], length=20)
            rsi_h4 = ta.rsi(df_h4["close"], length=14)
            last_close = float(df_h4["close"].iloc[-1])
            if ema20_h4 is not None and len(ema20_h4) > 0 and pd.notna(ema20_h4.iloc[-1]):
                e20 = float(ema20_h4.iloc[-1])
                rsi_val = float(rsi_h4.iloc[-1]) if rsi_h4 is not None and len(rsi_h4) > 0 and pd.notna(rsi_h4.iloc[-1]) else 50.0
                if e20 > last_close * 0.999 and rsi_val > 50:
                    result["h4_structure"] = "bullish"
                elif e20 < last_close * 1.001 and rsi_val < 50:
                    result["h4_structure"] = "bearish"
                else:
                    result["h4_structure"] = "neutral"
            if ema20_h4 is not None and len(ema20_h4) >= 3:
                vals = [float(ema20_h4.iloc[i]) for i in range(-3, 0)]
                if vals[0] < vals[1] < vals[2]:
                    result["h4_ema_trend"] = "bullish"
                elif vals[0] > vals[1] > vals[2]:
                    result["h4_ema_trend"] = "bearish"
        else:
            logger.warning("analyse_timeframes: H4 candles < %d, using neutral", MIN_MTF_CANDLES)
    except Exception as e:
        logger.warning("analyse_timeframes H4 failed: %s", e)

    # H1 direction (entry trigger)
    try:
        if len(h1_candles) >= 5:
            norm_h1 = [_normalize_candle(c) for c in h1_candles]
            last_close = norm_h1[-1]["close"]
            open_5_ago = norm_h1[-5]["open"]
            df_h1 = pd.DataFrame(norm_h1)
            import pandas_ta as ta
            atr_series = ta.atr(df_h1["high"], df_h1["low"], df_h1["close"], length=14)
            h1_atr: float | None = None
            if atr_series is not None and len(atr_series) > 0 and pd.notna(atr_series.iloc[-1]):
                h1_atr = float(atr_series.iloc[-1])
            diff = abs(last_close - open_5_ago)
            if h1_atr is not None and diff <= h1_atr * 0.3:
                result["h1_direction"] = "neutral"
            elif last_close > open_5_ago:
                result["h1_direction"] = "bullish"
            else:
                result["h1_direction"] = "bearish"
    except Exception as e:
        logger.warning("analyse_timeframes H1 direction failed: %s", e)

    # Conflict detection (STRICT)
    d1_bias = result["d1_bias"]
    h4_structure = result["h4_structure"]
    h1_direction = result["h1_direction"]

    if d1_bias == "bullish" and h4_structure == "bearish":
        result["conflict_detected"] = True
        result["conflict_reason"] = "D1 bullish but H4 bearish — opposing structure"
    elif d1_bias == "bearish" and h4_structure == "bullish":
        result["conflict_detected"] = True
        result["conflict_reason"] = "D1 bearish but H4 bullish — opposing structure"
    elif d1_bias == "bullish" and h1_direction == "bearish" and h4_structure != "bullish":
        result["conflict_detected"] = True
        result["conflict_reason"] = "D1 bullish but H1 bearish — H4 not confirming"
    elif d1_bias == "bearish" and h1_direction == "bullish" and h4_structure != "bearish":
        result["conflict_detected"] = True
        result["conflict_reason"] = "D1 bearish but H1 bullish — H4 not confirming"

    # Timeframe alignment
    if result["conflict_detected"]:
        result["timeframe_alignment"] = "conflict"
        result["tradeable"] = False
    else:
        directions = [d1_bias, h4_structure, h1_direction]
        bull_count = sum(1 for d in directions if d == "bullish")
        bear_count = sum(1 for d in directions if d == "bearish")
        if bull_count == 3 or bear_count == 3:
            result["timeframe_alignment"] = "full"
        else:
            result["timeframe_alignment"] = "partial"
        result["tradeable"] = True

    return result
