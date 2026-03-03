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


def detect_patterns(
    candles: list[dict[str, Any]],
    indicators: dict[str, Any],
    structure: dict[str, Any],
    mtf: dict[str, Any],
    pair: str,
) -> dict[str, Any]:
    """
    Detects exactly 4 coded patterns.
    All conditions are explicit coded rules.
    No LLM estimation anywhere in this function.

    IMPORTANT: This function requires mtf to be populated.
    It must only be called after analyse_timeframes() has run
    and after the MTF conflict gate has passed.
    Never call this function with an empty or None mtf dict.

    Priority order (first match wins):
    1. trend_continuation_ema_pullback  (highest quality)
    2. engulfing_at_key_level
    3. break_of_structure_reversal
    4. asian_range_breakout

    Args:
        candles:    H1 OHLCV list — minimum 30 candles required
        indicators: output from calculate_indicators() Week 1
        structure:  output from detect_structure() Week 2
        mtf:        output from analyse_timeframes() Week 3
                    MUST be populated — do not pass empty dict
        pair:       currency pair string e.g. "GBP/JPY"

    Returns:
    {
        "pattern_detected":  bool,
        "pattern_name":      str,
        "pattern_direction": "BUY"|"SELL"|"NEUTRAL",
        "quality_floor":     float,
        "quality_ceiling":   float,
        "conditions_met":    list[str]
    }
    """

    def _no_pattern_result() -> dict:
        return {
            "pattern_detected": False,
            "pattern_name": "no_pattern",
            "pattern_direction": "NEUTRAL",
            "quality_floor": 0.0,
            "quality_ceiling": 1.0,
            "conditions_met": [],
        }

    if not mtf or not indicators or not structure:
        logger.warning(
            "detect_patterns called with missing inputs for %s — returning no_pattern",
            pair,
        )
        return _no_pattern_result()

    if len(candles) < 30:
        logger.debug("detect_patterns: need at least 30 candles for %s, got %d", pair, len(candles))
        return _no_pattern_result()

    normalized = [_normalize_candle(c) for c in candles]
    pip_thresh = get_pair_pip_threshold(pair)

    # Extract values with safe defaults
    rsi_val = float(indicators.get("rsi_14") or 50.0)
    ema_20 = float(indicators.get("ema_20") or 0.0)
    ema_50 = float(indicators.get("ema_50") or 0.0)
    atr_val = float(indicators.get("atr_14") or 0.0)
    current_price = float(indicators.get("current_price") or 0.0)
    ema_trend = str(indicators.get("ema_trend", "neutral"))
    d1_bias = str(mtf.get("d1_bias", "neutral"))
    h4_structure = str(mtf.get("h4_structure", "neutral"))
    hh_hl = bool(structure.get("hh_hl", False))
    ll_lh = bool(structure.get("ll_lh", False))
    at_ema_20 = bool(structure.get("at_ema_20", False))

    if atr_val <= 0:
        logger.debug("detect_patterns: ATR zero or negative for %s", pair)
        return _no_pattern_result()

    # --- 1. trend_continuation_ema_pullback ---
    conds: list[str] = []
    if ema_trend == "bullish" and d1_bias == "bullish" and at_ema_20:
        o1, h1, l1, c1 = normalized[-1]["open"], normalized[-1]["high"], normalized[-1]["low"], normalized[-1]["close"]
        if ema_20 > 0:
            touch = abs(l1 - ema_20) < atr_val * 0.3
            if touch and c1 > o1 and 40 <= rsi_val <= 60:
                conds = ["ema_trend bullish", "d1_bias bullish", "at_ema_20 True", "pullback rejection BUY", "RSI 40-60"]
                logger.info(
                    "Pattern detected for %s: trend_continuation_ema_pullback BUY "
                    "quality [0.72-0.88] conditions: %s",
                    pair,
                    conds,
                )
                return {
                    "pattern_detected": True,
                    "pattern_name": "trend_continuation_ema_pullback",
                    "pattern_direction": "BUY",
                    "quality_floor": 0.72,
                    "quality_ceiling": 0.88,
                    "conditions_met": conds,
                }
    if ema_trend == "bearish" and d1_bias == "bearish" and at_ema_20:
        o1, h1, l1, c1 = normalized[-1]["open"], normalized[-1]["high"], normalized[-1]["low"], normalized[-1]["close"]
        if ema_20 > 0:
            touch = abs(h1 - ema_20) < atr_val * 0.3
            if touch and c1 < o1 and 40 <= rsi_val <= 60:
                conds = ["ema_trend bearish", "d1_bias bearish", "at_ema_20 True", "pullback rejection SELL", "RSI 40-60"]
                logger.info(
                    "Pattern detected for %s: trend_continuation_ema_pullback SELL "
                    "quality [0.72-0.88] conditions: %s",
                    pair,
                    conds,
                )
                return {
                    "pattern_detected": True,
                    "pattern_name": "trend_continuation_ema_pullback",
                    "pattern_direction": "SELL",
                    "quality_floor": 0.72,
                    "quality_ceiling": 0.88,
                    "conditions_met": conds,
                }

    # --- 2. engulfing_at_key_level ---
    o1, h1, l1, c1 = normalized[-1]["open"], normalized[-1]["high"], normalized[-1]["low"], normalized[-1]["close"]
    o2, c2 = normalized[-2]["open"], normalized[-2]["close"]
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    bullish_engulf = c1 > o1 and (c1 > o2 and o1 < c2)
    bearish_engulf = c1 < o1 and (c1 < o2 and o1 > c2)
    engulfing = body1 > body2 and (bullish_engulf or bearish_engulf)

    if engulfing:
        if body2 <= 0:
            pass
        else:
            swing_high = max(n["high"] for n in normalized[-20:]) if len(normalized) >= 20 else h1
            swing_low = min(n["low"] for n in normalized[-20:]) if len(normalized) >= 20 else l1
            near_ema50 = abs(current_price - ema_50) <= atr_val * 1.0 if ema_50 else False
            near_swing_high = abs(current_price - swing_high) <= atr_val * 1.0
            near_swing_low = abs(current_price - swing_low) <= atr_val * 1.0
            key_level = near_ema50 or near_swing_high or near_swing_low

            if bullish_engulf and key_level and rsi_val < 65:
                conds = ["engulfing bullish", "key_level True", "RSI < 65"]
                logger.info(
                    "Pattern detected for %s: engulfing_at_key_level BUY "
                    "quality [0.70-0.85] conditions: %s",
                    pair,
                    conds,
                )
                return {
                    "pattern_detected": True,
                    "pattern_name": "engulfing_at_key_level",
                    "pattern_direction": "BUY",
                    "quality_floor": 0.70,
                    "quality_ceiling": 0.85,
                    "conditions_met": conds,
                }
            if bearish_engulf and key_level and rsi_val > 35:
                conds = ["engulfing bearish", "key_level True", "RSI > 35"]
                logger.info(
                    "Pattern detected for %s: engulfing_at_key_level SELL "
                    "quality [0.70-0.85] conditions: %s",
                    pair,
                    conds,
                )
                return {
                    "pattern_detected": True,
                    "pattern_name": "engulfing_at_key_level",
                    "pattern_direction": "SELL",
                    "quality_floor": 0.70,
                    "quality_ceiling": 0.85,
                    "conditions_met": conds,
                }

    # --- 3. break_of_structure_reversal ---
    # Reversal: prior downtrend + break above = bullish; prior uptrend + break below = bearish
    highs = [n["high"] for n in normalized]
    lows = [n["low"] for n in normalized]
    if len(highs) >= 6 and len(lows) >= 6:
        recent_high = max(highs[-6:-1])
        recent_low = min(lows[-6:-1])
        bullish_bos = current_price > recent_high and ll_lh  # prior downtrend, break up = reversal
        bearish_bos = current_price < recent_low and hh_hl    # prior uptrend, break down = reversal

        if bullish_bos or bearish_bos:
            df = pd.DataFrame(normalized)
            import pandas_ta as ta
            rsi_series = ta.rsi(df["close"], length=14)
            rsi_1 = float(rsi_series.iloc[-1]) if rsi_series is not None and len(rsi_series) >= 1 and pd.notna(rsi_series.iloc[-1]) else 50.0
            rsi_2 = float(rsi_series.iloc[-2]) if rsi_series is not None and len(rsi_series) >= 2 and pd.notna(rsi_series.iloc[-2]) else 50.0

            if bullish_bos and h4_structure != "bearish":
                rsi_cross_above = rsi_1 > 50 and rsi_2 <= 50
                if rsi_cross_above:
                    conds = ["prior uptrend hh_hl", "BOS bullish", "RSI cross above 50", "H4 not bearish"]
                    logger.info(
                        "Pattern detected for %s: break_of_structure_reversal BUY "
                        "quality [0.68-0.83] conditions: %s",
                        pair,
                        conds,
                    )
                    return {
                        "pattern_detected": True,
                        "pattern_name": "break_of_structure_reversal",
                        "pattern_direction": "BUY",
                        "quality_floor": 0.68,
                        "quality_ceiling": 0.83,
                        "conditions_met": conds,
                    }
            if bearish_bos and h4_structure != "bullish":
                rsi_cross_below = rsi_1 < 50 and rsi_2 >= 50
                if rsi_cross_below:
                    conds = ["prior downtrend ll_lh", "BOS bearish", "RSI cross below 50", "H4 not bullish"]
                    logger.info(
                        "Pattern detected for %s: break_of_structure_reversal SELL "
                        "quality [0.68-0.83] conditions: %s",
                        pair,
                        conds,
                    )
                    return {
                        "pattern_detected": True,
                        "pattern_name": "break_of_structure_reversal",
                        "pattern_direction": "SELL",
                        "quality_floor": 0.68,
                        "quality_ceiling": 0.83,
                        "conditions_met": conds,
                    }

    # --- 4. asian_range_breakout ---
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
        asian_range = asian_high - asian_low
        if asian_range > atr_val * 0.3:
            now_hour = 12
            try:
                last_t = candles[-1].get("time")
                if last_t:
                    s = str(last_t).replace("Z", "+00:00").split(".")[0]
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    now_hour = dt.hour
            except (ValueError, TypeError):
                pass

            in_valid_window = 7 <= now_hour <= 16
            if in_valid_window:
                bullish_break = current_price > asian_high + (atr_val * 0.1)
                bearish_break = current_price < asian_low - (atr_val * 0.1)
                body = abs(c1 - o1)
                candle_range = h1 - l1 if h1 > l1 else 0.0001
                strong_candle = body / candle_range > 0.6 if candle_range > 0 else False

                if bullish_break and strong_candle and h4_structure != "bearish":
                    conds = ["asian range valid", "bullish breakout", "strong candle", "London/NY window", "H4 not bearish"]
                    logger.info(
                        "Pattern detected for %s: asian_range_breakout BUY "
                        "quality [0.68-0.82] conditions: %s",
                        pair,
                        conds,
                    )
                    return {
                        "pattern_detected": True,
                        "pattern_name": "asian_range_breakout",
                        "pattern_direction": "BUY",
                        "quality_floor": 0.68,
                        "quality_ceiling": 0.82,
                        "conditions_met": conds,
                    }
                if bearish_break and strong_candle and h4_structure != "bullish":
                    conds = ["asian range valid", "bearish breakout", "strong candle", "London/NY window", "H4 not bullish"]
                    logger.info(
                        "Pattern detected for %s: asian_range_breakout SELL "
                        "quality [0.68-0.82] conditions: %s",
                        pair,
                        conds,
                    )
                    return {
                        "pattern_detected": True,
                        "pattern_name": "asian_range_breakout",
                        "pattern_direction": "SELL",
                        "quality_floor": 0.68,
                        "quality_ceiling": 0.82,
                        "conditions_met": conds,
                    }

    logger.debug("No pattern matched for %s", pair)
    return _no_pattern_result()
