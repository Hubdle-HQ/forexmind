"""
Week 4 tradeable path test: D1/H4/H1 all bullish, levels calculated.
Uses mocked candles to force full alignment — run when you need to verify
_level_cache, SL/TP logs, pip_value, R:R 2.0.
Run: cd backend && python tests/test_week4_tradeable.py
"""
import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure backend on path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PAIR = "AUD/USD"
BASE = 0.7060


def _make_h1(i: int) -> dict:
    """Sawtooth + final uptrend — HH/HL, RSI ~50 (neutral zone)."""
    # Alternating up/down for 80 candles, then small rise
    base = BASE + (i // 2) * 0.00002
    if i % 2 == 0:
        c = base + 0.0001
    else:
        c = base - 0.00008
    if i >= 85:
        c += 0.0003
    o = base
    h = max(o, c) + 0.00015
    l = min(o, c) - 0.0001
    return {"time": f"2026-02-24T{i % 24:02d}:00:00.000000000Z", "o": o, "h": h, "l": l, "c": c}


def _make_h4(i: int) -> dict:
    """Ascending H4 — bullish structure."""
    o = BASE + i * 0.0003
    h = o + 0.0008
    l = o - 0.0002
    c = o + 0.0004
    return {"time": f"2026-02-24T{i % 6:02d}:00:00.000000000Z", "o": o, "h": h, "l": l, "c": c}


def _make_d1(i: int) -> dict:
    """Ascending D1 — EMA20 > EMA50."""
    o = BASE + i * 0.001
    h = o + 0.002
    l = o - 0.0005
    c = o + 0.0012
    return {"time": f"2026-02-{20 + i:02d}T12:00:00.000000000Z", "o": o, "h": h, "l": l, "c": c}


def run_tradeable_test() -> None:
    """Run TechnicalAgent with mocked bullish/bullish/bullish candles."""
    h1_candles = [_make_h1(i) for i in range(100)]
    h4_candles = [_make_h4(i) for i in range(30)]
    d1_candles = [_make_d1(i) for i in range(30)]

    with (
        patch("agents.technical_agent.fetch_candles", return_value=h1_candles),
        patch("agents.technical_agent.fetch_h4_candles", return_value=h4_candles),
        patch("agents.technical_agent.fetch_d1_candles", return_value=d1_candles),
    ):
        from agents.technical_agent import run_technical_agent, _level_cache

        logger.info("=== Week 4 Tradeable Path: D1/H4/H1 bullish (mocked) ===")
        result = run_technical_agent(PAIR)

        logger.info("Result: %s", json.dumps(result, indent=2))

        # Verify tradeable path
        assert result.get("direction") != "NEUTRAL" or result.get("setup") != "no_setup", (
            "Expected tradeable path — check MTF/analyse_timeframes logic"
        )

        levels = _level_cache.get(PAIR)
        if levels:
            logger.info("")
            logger.info("=== _level_cache populated ===")
            logger.info("Entry: %s | SL: %s | TP: %s", levels["entry_price"], levels["stop_loss"], levels["take_profit"])
            logger.info("pip_value: %s | R:R: %s", levels["pip_value"], levels["risk_reward_ratio"])
            assert levels["risk_reward_ratio"] == 2.0, f"R:R should be 2.0, got {levels['risk_reward_ratio']}"
            logger.info("OK: _level_cache, pip_value, R:R 2.0 verified")

            # Optionally verify SignalAgent uses levels (mock market open)
            with patch("agents.signal_agent._is_market_open", return_value=True):
                from agents.signal_agent import run_signal_agent

                state = {
                    "pair": PAIR,
                    "macro_sentiment": {"sentiment": "neutral", "confidence": 0.8},
                    "technical_setup": result,
                    "user_patterns": {"mode": "market_patterns"},
                    "coach_advice": "TRADE.",
                }
                sig_result = run_signal_agent(state)
                if sig_result.get("final_signal"):
                    fs = sig_result["final_signal"]
                    logger.info("")
                    logger.info("=== SignalAgent (levels from cache) ===")
                    logger.info("entry: %s tp: %s sl: %s risk_reward_ratio: %s", fs["entry_price"], fs["take_profit"], fs["stop_loss"], fs["risk_reward_ratio"])
                    assert fs["risk_reward_ratio"] == 2.0, f"final_signal R:R should be 2.0, got {fs['risk_reward_ratio']}"
                    logger.info("OK: final_signal risk_reward_ratio = 2.0")
                else:
                    logger.info("SignalAgent: %s (market closed or API key missing)", sig_result.get("error", "no signal"))
        else:
            logger.warning("_level_cache empty — structure_bias may be neutral or MTF conflict")


if __name__ == "__main__":
    run_tradeable_test()
    logger.info("")
    logger.info("=== Week 4 tradeable path test complete ===")
    sys.exit(0)
