"""
OANDA v20 API price fetcher.

Fetches candlestick (OHLCV) data for any currency pair.
Uses requests for HTTP (no new dependencies).
"""
import logging
import os
import sys
from pathlib import Path

import requests

# Add backend to path for db imports
_backend = Path(__file__).resolve().parent.parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

logger = logging.getLogger(__name__)

OANDA_BASE_URL = "https://api-fxpractice.oanda.com"
OANDA_BASE_URL_LIVE = "https://api-fxtrade.oanda.com"


def _normalize_instrument(pair: str) -> str:
    """Convert pair like 'AUD/USD' or 'AUDUSD' to OANDA format 'AUD_USD'."""
    return pair.replace("/", "_").upper()


def fetch_candles(
    pair: str,
    count: int = 100,
    granularity: str = "H1",
    price: str = "M",
) -> list[dict]:
    """
    Fetch candlestick data from OANDA v20 API.

    Args:
        pair: Currency pair (e.g. 'AUD/USD', 'EUR_USD').
        count: Number of candles to return (default 100).
        granularity: Candle timeframe (default H1). Options: S5, S10, S15, S30, M1, M2, M4, M5, M10, M15, M30, H1, H2, H3, H4, H6, H8, H12, D, W, M.
        price: Price type - M (midpoint), B (bid), A (ask). Default M.

    Returns:
        List of candles, each with: time, o, h, l, c, volume, complete.
    """
    api_key = os.getenv("OANDA_API_KEY")
    if not api_key:
        raise ValueError("OANDA_API_KEY not set in .env")

    env = (os.getenv("OANDA_ENVIRONMENT") or "practice").lower()
    base = OANDA_BASE_URL_LIVE if env == "live" else OANDA_BASE_URL
    instrument = _normalize_instrument(pair)
    url = f"{base}/v3/instruments/{instrument}/candles"

    count = max(count, 100)
    params = {
        "count": count,
        "granularity": granularity,
        "price": price,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    candles: list[dict] = []
    for c in data.get("candles", []):
        mid = c.get("mid") or c.get("bid") or c.get("ask") or {}
        candles.append({
            "time": c.get("time"),
            "o": float(mid.get("o", 0)),
            "h": float(mid.get("h", 0)),
            "l": float(mid.get("l", 0)),
            "c": float(mid.get("c", 0)),
            "volume": int(c.get("volume", 0)),
            "complete": c.get("complete", True),
        })
    return candles


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    candles = fetch_candles("AUD/USD", count=100, granularity="H1")
    logger.info("Fetched %d candles for AUD/USD H1", len(candles))
    if candles:
        logger.info("Last 3 candles (OHLCV):")
        for c in candles[-3:]:
            logger.info("  %s | O=%.5f H=%.5f L=%.5f C=%.5f V=%d", c["time"], c["o"], c["h"], c["l"], c["c"], c["volume"])
