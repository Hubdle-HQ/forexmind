"""
Health check: run all scrapers and log current status to pipeline_health.

Checks: RBA scraper, ForexFactory scraper, OANDA price data.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def _log_health(source: str, status: str, error_msg: str | None = None) -> None:
    """Insert a row into pipeline_health."""
    supabase = get_supabase()
    supabase.table("pipeline_health").insert(
        {"source": source, "status": status, "error_msg": error_msg}
    ).execute()
    logger.info("Logged health: %s -> %s", source, status)


def run_all_checks() -> dict[str, str]:
    """
    Run all scrapers and log status to pipeline_health.
    Returns dict mapping source -> status (ok/failed).
    """
    results: dict[str, str] = {}

    # RBA scraper
    try:
        from rag.sources.rba_scraper import fetch_rba_data

        fetch_rba_data()
        results["rba_scraper"] = "ok"
    except Exception as e:
        logger.exception("RBA scraper failed: %s", e)
        _log_health("rba_scraper", "failed", str(e))
        results["rba_scraper"] = "failed"

    # ForexFactory scraper
    try:
        from rag.sources.forexfactory import fetch_forexfactory_events

        fetch_forexfactory_events()
        results["forexfactory"] = "ok"
    except Exception as e:
        logger.exception("ForexFactory scraper failed: %s", e)
        _log_health("forexfactory", "failed", str(e))
        results["forexfactory"] = "failed"

    # OANDA price data (no fallback per CURSOR.md)
    try:
        from rag.sources.price_data import fetch_candles

        fetch_candles("AUD/USD", count=1, granularity="H1")
        _log_health("oanda_price", "ok")
        results["oanda_price"] = "ok"
    except Exception as e:
        logger.exception("OANDA price check failed: %s", e)
        _log_health("oanda_price", "failed", str(e))
        results["oanda_price"] = "failed"

    return results
