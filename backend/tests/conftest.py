"""
Pytest configuration and shared fixtures for ForexMind agent tests.
Ensures backend is on path and loads .env.
"""
from pathlib import Path
import sys

import pytest

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# Load .env before any agent imports
from dotenv import load_dotenv
load_dotenv(_backend.parent / ".env")


def _make_candle(time: str, o: float, h: float, l: float, c: float) -> dict:
    """Create OANDA-style candle dict."""
    return {"time": time, "o": o, "h": h, "l": l, "c": c}


@pytest.fixture
def sample_candles() -> list[dict]:
    """50+ H1 candles for indicator/structure tests. Ascending then flat."""
    base = 0.6500
    candles = []
    for i in range(60):
        o = base + i * 0.0001
        h = o + 0.0005
        l = o - 0.0002
        c = o + 0.0002
        # OANDA format
        t = f"2026-02-24T{i % 24:02d}:00:00.000000000Z"
        candles.append(_make_candle(t, o, h, l, c))
    return candles


@pytest.fixture
def sample_candles_hh_hl() -> list[dict]:
    """Candles with higher highs and higher lows (uptrend structure)."""
    base = 0.6500
    candles = []
    for i in range(60):
        o = base + i * 0.0003
        h = o + 0.0008
        l = o - 0.0001
        c = o + 0.0004
        t = f"2026-02-24T{i % 24:02d}:00:00.000000000Z"
        candles.append(_make_candle(t, o, h, l, c))
    return candles


@pytest.fixture
def sample_candles_ll_lh() -> list[dict]:
    """Candles with lower lows and lower highs (downtrend structure)."""
    base = 0.6600
    candles = []
    for i in range(60):
        o = base - i * 0.0003
        h = o + 0.0002
        l = o - 0.0006
        c = o - 0.0003
        t = f"2026-02-24T{i % 24:02d}:00:00.000000000Z"
        candles.append(_make_candle(t, o, h, l, c))
    return candles
