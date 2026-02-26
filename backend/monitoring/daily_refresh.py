"""
Daily data refresh: scrapers, embed, mark stale, signal evaluator, health check.
RAGAS evaluation runs weekly on Sundays only.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

RAG_SOURCES = (
    "rba_scraper",
    "rba_fallback",
    "rba_newsapi_fallback",
    "forexfactory",
    "forexfactory_fallback",
)


def _fetch_page_content(url: str) -> str:
    """Fetch and extract main content from a page."""
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.select("nav, footer, .share, .enquiries, [role='navigation']"):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile("content|main"))
    if not main:
        main = soup.body
    if not main:
        return ""
    return main.get_text(separator=" ", strip=True)


def _run_scrapers_and_embed() -> tuple[int, int]:
    """
    Run RBA and ForexFactory scrapers, embed new documents.
    Returns (rba_count, forexfactory_count).
    """
    from rag.ingest import ingest_document
    from rag.sources.forexfactory import fetch_and_embed_forexfactory
    from rag.sources.rba_scraper import fetch_rba_data

    rba_count = 0
    try:
        items = fetch_rba_data()
        for item in items:
            content = item.get("content") or item.get("summary") or ""
            if not content and item.get("url"):
                try:
                    content = _fetch_page_content(item["url"])
                except Exception as e:
                    logger.warning("Failed to fetch RBA URL %s: %s", item.get("url"), e)
                    content = item.get("title", "")
            if not content:
                content = item.get("title", "RBA update")
            source = item.get("source", "rba_scraper")
            ingest_document(content[:50000], source=source)
            rba_count += 1
        logger.info("Embedded %d RBA documents", rba_count)
    except Exception as e:
        logger.exception("RBA scrape and embed failed: %s", e)

    ff_count = 0
    try:
        embedded = fetch_and_embed_forexfactory()
        ff_count = len(embedded)
        logger.info("Embedded %d ForexFactory documents", ff_count)
    except Exception as e:
        logger.exception("ForexFactory scrape and embed failed: %s", e)

    return (rba_count, ff_count)


def _mark_old_documents_stale() -> int:
    """Mark forex_documents from RAG sources as stale. Returns count updated."""
    supabase = get_supabase()
    # Get count first
    count_resp = (
        supabase.table("forex_documents")
        .select("id", count="exact")
        .in_("source", list(RAG_SOURCES))
        .execute()
    )
    count = count_resp.count if hasattr(count_resp, "count") else len(count_resp.data or [])
    if count > 0:
        supabase.table("forex_documents").update({"is_stale": True}).in_("source", list(RAG_SOURCES)).execute()
    logger.info("Marked %d documents as stale", count)
    return count


def run_daily_refresh() -> dict:
    """
    Run full daily refresh:
    1. Mark old documents as stale
    2. Run scrapers and embed new documents
    3. Run signal evaluator
    4. Run health check
    5. Check for failures and send alert
    """
    results: dict = {
        "stale_marked": 0,
        "rba_embedded": 0,
        "forexfactory_embedded": 0,
        "signals_resolved": 0,
        "health": {},
        "alert_sent": False,
        "ragas_scores": {},
    }

    # 1. Mark old as stale (before ingesting so new ones stay fresh)
    try:
        results["stale_marked"] = _mark_old_documents_stale()
    except Exception as e:
        logger.exception("Mark stale failed: %s", e)

    # 2. Run scrapers and embed
    try:
        rba_count, ff_count = _run_scrapers_and_embed()
        results["rba_embedded"] = rba_count
        results["forexfactory_embedded"] = ff_count
    except Exception as e:
        logger.exception("Scrape and embed failed: %s", e)

    # 3. Signal evaluator
    try:
        from evals.signal_evaluator import resolve_unresolved_signals

        results["signals_resolved"] = resolve_unresolved_signals()
    except Exception as e:
        logger.exception("Signal evaluator failed: %s", e)

    # 4. Health check
    try:
        from monitoring.health_check import run_all_checks

        results["health"] = run_all_checks()
    except Exception as e:
        logger.exception("Health check failed: %s", e)

    # 5. Check failures and send alert
    try:
        from monitoring.alerts import check_and_send_failure_alerts

        results["alert_sent"] = check_and_send_failure_alerts()
    except Exception as e:
        logger.exception("Failure alert check failed: %s", e)

    # 6. RAGAS evaluation (Sundays only)
    if datetime.now(timezone.utc).weekday() == 6:
        try:
            from evals.rag_evaluator import run_ragas_evaluation

            results["ragas_scores"] = run_ragas_evaluation()
        except Exception as e:
            logger.exception("RAGAS evaluation failed: %s", e)

    return results
