"""
ForexFactory economic calendar scraper.
Primary: scrape calendar HTML for high-impact events (next 7 days).
Fallback: ForexFactory XML calendar feed (ff_calendar_thisweek.xml).
"""
import logging
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Add backend to path for db imports
_backend = Path(__file__).resolve().parent.parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

CALENDAR_HTML_URL = "https://www.forexfactory.com/calendar"
CALENDAR_XML_URL = "https://www.forexfactory.com/ff_calendar_thisweek.xml"
FF_SCRAPER_PRIMARY_URL = os.getenv("FF_SCRAPER_PRIMARY_URL", CALENDAR_HTML_URL)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

IMPACT_MAP = {
    "ff-impact-red": "high",
    "ff-impact-ora": "medium",
    "ff-impact-yel": "low",
    "ff-impact-gra": "low",
}


def _log_health(source: str, status: str, error_msg: str | None = None) -> None:
    """Log a row to pipeline_health."""
    supabase = get_supabase()
    supabase.table("pipeline_health").insert(
        {"source": source, "status": status, "error_msg": error_msg}
    ).execute()


def _format_event_text(event: dict) -> str:
    """Format event as readable text for embedding."""
    parts = [
        f"Event: {event.get('event_name', '')}",
        f"Currency: {event.get('currency', '')}",
        f"Date/Time: {event.get('datetime', '')}",
        f"Impact: {event.get('impact', '')}",
    ]
    if event.get("forecast"):
        parts.append(f"Forecast: {event['forecast']}")
    if event.get("previous"):
        parts.append(f"Previous: {event['previous']}")
    return " | ".join(parts)


def scrape_calendar_html() -> list[dict]:
    """Scrape ForexFactory calendar HTML for high-impact events (next 7 days)."""
    events: list[dict] = []
    current_date = ""

    for week in ["this", "next"]:
        url = f"{FF_SCRAPER_PRIMARY_URL}?week={week}" if "?" not in FF_SCRAPER_PRIMARY_URL else f"{FF_SCRAPER_PRIMARY_URL}&week={week}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for row in soup.select("tr.calendar__row"):
            if "calendar__row--day-breaker" in (row.get("class") or []):
                continue
            if "calendar__row--no-event" in (row.get("class") or []):
                date_cell = row.select_one("td.calendar__date")
                if date_cell:
                    current_date = date_cell.get_text(strip=True)
                continue

            date_cell = row.select_one("td.calendar__date")
            time_cell = row.select_one("td.calendar__time")
            curr_cell = row.select_one("td.calendar__currency")
            impact_cell = row.select_one("td.calendar__impact")
            event_cell = row.select_one("td.calendar__event")
            forecast_cell = row.select_one("td.calendar__forecast")
            prev_cell = row.select_one("td.calendar__previous")

            if date_cell:
                current_date = date_cell.get_text(strip=True)
            if not event_cell:
                continue

            impact = "low"
            if impact_cell:
                icon = impact_cell.select_one("span")
                if icon:
                    cls_str = " ".join(icon.get("class") or [])
                    for cls, level in IMPACT_MAP.items():
                        if cls in cls_str:
                            impact = level
                            break

            event_name = event_cell.get_text(strip=True)
            currency = (curr_cell.get_text(strip=True) or "").strip()
            time_str = (time_cell.get_text(strip=True) or "").strip()
            datetime_str = f"{current_date} {time_str}".strip() if current_date else time_str

            if impact in ("high", "medium"):
                events.append(
                    {
                        "event_name": event_name,
                        "currency": currency,
                        "datetime": datetime_str,
                        "impact": impact,
                        "forecast": (forecast_cell.get_text(strip=True) or "").strip() or None,
                        "previous": (prev_cell.get_text(strip=True) or "").strip() or None,
                    }
                )

    return events[:50]


def fetch_calendar_xml() -> list[dict]:
    """Fallback: fetch ForexFactory XML calendar feed (ff_calendar_thisweek.xml)."""
    resp = requests.get(CALENDAR_XML_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    events: list[dict] = []

    def _text(el: ET.Element | None) -> str:
        return (el.text or "").strip() if el is not None else ""

    def _attr(el: ET.Element, name: str) -> str:
        return (el.get(name) or "").strip()

    for item in root.iter():
        if item.tag in ("event", "row", "item"):
            event_name = _attr(item, "title") or _attr(item, "name") or _text(item.find("title")) or _text(item.find("name"))
            if not event_name:
                continue
            impact_raw = _attr(item, "impact") or _text(item.find("impact"))
            impact = "low"
            if impact_raw:
                imp_lower = impact_raw.lower()
                if "high" in imp_lower or "red" in imp_lower:
                    impact = "high"
                elif "medium" in imp_lower or "orange" in imp_lower or "ora" in imp_lower:
                    impact = "medium"
            if impact in ("high", "medium"):
                events.append(
                    {
                        "event_name": event_name,
                        "currency": _attr(item, "currency") or _text(item.find("currency")),
                        "datetime": _attr(item, "date") or _attr(item, "time") or _text(item.find("date")),
                        "impact": impact,
                        "forecast": None,
                        "previous": None,
                    }
                )
    return events[:50]


def fetch_forexfactory_events() -> list[dict]:
    """
    Orchestrator: try primary (HTML) first, then XML fallback.
    Return high/medium impact events for next 7 days.
    """
    # Primary: HTML scrape
    try:
        events = scrape_calendar_html()
        if events:
            _log_health("forexfactory", "ok")
            return events
    except Exception as e:
        logger.warning("ForexFactory HTML scrape failed: %s", e)
        _log_health("forexfactory", "failed", str(e))

    # Fallback: XML feed
    try:
        events = fetch_calendar_xml()
        if events:
            _log_health("forexfactory_fallback", "ok")
            return events
    except Exception as e:
        logger.warning("ForexFactory XML fallback failed: %s", e)
        _log_health("forexfactory", "failed", f"XML fallback: {e}")

    raise RuntimeError("All ForexFactory sources failed")


def fetch_and_embed_forexfactory() -> list[dict]:
    """
    Fetch ForexFactory events, format as text, embed into forex_documents with source=forexfactory.
    Returns list of formatted event strings that were embedded.
    """
    from rag.ingest import ingest_document

    events = fetch_forexfactory_events()
    embedded: list[str] = []
    for ev in events:
        text = _format_event_text(ev)
        ingest_document(text, source="forexfactory")
        embedded.append(text)
    return embedded


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--embed", action="store_true", help="Embed events into forex_documents and test retrieval")
    args = parser.parse_args()

    if args.embed:
        embedded = fetch_and_embed_forexfactory()
        logger.info("Embedded %d events into forex_documents", len(embedded))
        from rag.ingest import retrieve_documents

        results = retrieve_documents("RBA interest rate announcement", top_k=10)
        forexfactory_results = [r for r in results if r.get("source") == "forexfactory"]
        logger.info("Query 'RBA interest rate announcement' returned %d forexfactory results", len(forexfactory_results))
        for r in forexfactory_results[:5]:
            logger.info("  - %s", r.get("content", "")[:80])
    else:
        events = fetch_forexfactory_events()
        logger.info("Fetched %d high/medium impact events", len(events))
        for i, ev in enumerate(events[:10], 1):
            logger.info("  %d. [%s] %s @ %s (%s)", i, ev.get("currency"), ev.get("event_name"), ev.get("datetime"), ev.get("impact"))
