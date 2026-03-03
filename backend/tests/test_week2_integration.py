"""
Week 2 integration test: TechnicalAgent with live OANDA + LLM.
Runs against real APIs — use for manual smoke testing.
Run: cd backend && python -m pytest tests/test_week2_integration.py -v -s
Or:  cd backend && python tests/test_week2_integration.py
"""
import json
import logging
import sys
from pathlib import Path

import pytest

# Ensure backend on path (conftest does this for pytest, but standalone needs it)
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from agents.indicators import calculate_indicators, detect_structure, get_pair_pip_threshold
from agents.technical_agent import run_technical_agent
from rag.sources.price_data import fetch_candles

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PAIR = "AUD/USD"


@pytest.mark.integration
def test_indicators_and_structure_live() -> None:
    """Fetch live candles, run indicators + structure (no LLM)."""
    logger.info("=== Week 2: Indicators + Structure (live OANDA) ===")
    candles = fetch_candles(PAIR, count=100, granularity="H1")
    assert candles, "No candles fetched — check OANDA_API_KEY"
    indicators = calculate_indicators(candles)
    structure = detect_structure(candles, indicators, pair=PAIR)
    logger.info("Indicators: RSI=%.1f, EMA20=%.5f, zone=%s",
                indicators.get("rsi_14"), indicators.get("ema_20"), indicators.get("rsi_zone"))
    logger.info("Structure: %s", json.dumps(structure, indent=2))
    assert get_pair_pip_threshold(PAIR) == 0.0005
    assert get_pair_pip_threshold("GBP/JPY") == 0.05


@pytest.mark.integration
def test_technical_agent_full_pipeline() -> None:
    """Run full TechnicalAgent (OANDA + RAG + LLM)."""
    logger.info("=== Week 2: TechnicalAgent (full pipeline) ===")
    result = run_technical_agent(PAIR)
    logger.info("Result: %s", json.dumps(result, indent=2))
    assert "setup" in result and "direction" in result and "quality" in result
    assert result["direction"] in ("BUY", "SELL", "NEUTRAL")
    assert 0 <= result["quality"] <= 1


if __name__ == "__main__":
    # Run as script: cd backend && python tests/test_week2_integration.py
    sys.exit(pytest.main([__file__, "-v", "-s", "-m", "integration"]))
