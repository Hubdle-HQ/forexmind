"""
RBA data source with 3-layer fallback:
1. Primary: rba.gov.au/media-releases scraper
2. Fallback 1: RBA RSS feed
3. Fallback 2: NewsAPI search "Reserve Bank Australia" (last 7 days)
"""
import logging
import re
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
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

PRIMARY_URL = "https://www.rba.gov.au/media-releases/"
RSS_URL = "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"
NEWSAPI_URL = "https://newsapi.org/v2/everything"

# Configurable for fallback test — set to invalid URL to force fallback
RBA_SCRAPER_PRIMARY_URL = os.getenv("RBA_SCRAPER_PRIMARY_URL", PRIMARY_URL)


def _log_health(source: str, status: str, error_msg: str | None = None) -> None:
    """Log a row to pipeline_health and send alert on failure."""
    supabase = get_supabase()
    supabase.table("pipeline_health").insert(
        {"source": source, "status": status, "error_msg": error_msg}
    ).execute()
    if status == "failed":
        try:
            from monitoring.alerts import send_pipeline_failure_alert

            send_pipeline_failure_alert(source=source, error_msg=error_msg or "")
        except Exception as e:
            logger.exception("Failed to send alert email: %s", e)


def scrape_primary() -> list[dict]:
    """Scrape rba.gov.au/media-releases for latest statements."""
    resp = requests.get(RBA_SCRAPER_PRIMARY_URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[dict] = []
    # Only match release URLs: /media-releases/YYYY/mr-YY-NN.html (exclude nav links)
    release_pattern = re.compile(r"/media-releases/\d{4}/mr-\d{2}-\d{2,3}\.html$")
    for link in soup.select("a[href*='/media-releases/']"):
        href = link.get("href", "").split("?")[0].rstrip("/")
        if not release_pattern.search(href):
            continue
        title = link.get_text(strip=True)
        if not title or "RSS Feed" in title:
            continue
        url = href if href.startswith("http") else f"https://www.rba.gov.au{href}"
        items.append({"title": title, "url": url, "source": "rba_scraper"})
    return items[:20]


def fetch_rss() -> list[dict]:
    """Fetch RBA RSS feed at rba.gov.au/rss/rss-cb-media-releases.xml."""
    feed = feedparser.parse(RSS_URL)
    items: list[dict] = []
    for entry in feed.entries[:20]:
        items.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "content": entry.get("summary", "") or entry.get("description", ""),
                "source": "rba_fallback",
            }
        )
    return items


def fetch_newsapi_fallback() -> list[dict]:
    """NewsAPI fallback: search 'Reserve Bank Australia' with last 7 days filter."""
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        raise ValueError("NEWSAPI_KEY not set")
    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(days=7)
    params = {
        "q": "Reserve Bank Australia",
        "from": from_date.strftime("%Y-%m-%d"),
        "to": to_date.strftime("%Y-%m-%d"),
        "apiKey": api_key,
        "pageSize": 20,
        "sortBy": "publishedAt",
    }
    resp = requests.get(NEWSAPI_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    articles = data.get("articles", [])
    return [
        {
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "content": a.get("description", "") or a.get("content", "") or "",
            "source": "rba_newsapi_fallback",
        }
        for a in articles
        if a.get("title") and a.get("url")
    ]


def fetch_rba_data() -> list[dict]:
    """
    Orchestrator: try primary → RSS fallback → NewsAPI fallback.
    Log to pipeline_health at each step. Send alert on failure.
    """
    # Primary
    try:
        items = scrape_primary()
        if items:
            _log_health("rba_scraper", "ok")
            return items
    except Exception as e:
        logger.warning("Primary RBA scraper failed: %s", e)
        _log_health("rba_scraper", "failed", str(e))

    # Fallback 1: RSS
    try:
        items = fetch_rss()
        if items:
            _log_health("rba_fallback", "ok")
            return items
    except Exception as e:
        logger.warning("RBA RSS fallback failed: %s", e)
        _log_health("rba_scraper", "failed", f"RSS fallback: {e}")

    # Fallback 2: NewsAPI
    try:
        items = fetch_newsapi_fallback()
        if items:
            _log_health("rba_newsapi_fallback", "ok")
            return items
    except Exception as e:
        logger.warning("NewsAPI fallback failed: %s", e)
        _log_health("rba_scraper", "failed", f"NewsAPI fallback: {e}")

    raise RuntimeError("All RBA data sources failed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    items = fetch_rba_data()
    logger.info("Fetched %d items", len(items))
    for i, item in enumerate(items[:5], 1):
        logger.info("  %d. %s", i, item.get("title", "")[:60])
