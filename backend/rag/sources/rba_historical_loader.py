"""
Load 50 historical RBA statements (2022–present, post-COVID rate cycle).
Chunk into 500-token segments, embed, insert into forex_documents with source=rba_historical.
"""
import logging
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Add backend to path for db imports
_backend = Path(__file__).resolve().parent.parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from rag.ingest import ingest_document

logger = logging.getLogger(__name__)

RBA_BASE = "https://www.rba.gov.au"
# ~500 tokens ≈ 2000 chars (English ~4 chars/token)
CHUNK_CHARS = 2000
# Keywords for rate-cycle relevance (prioritize these)
RATE_KEYWORDS = (
    "monetary policy",
    "cash rate",
    "interest rate",
    "inflation",
    "statement by",
    "reserve bank board",
    "philip lowe",
    "michele bullock",
)


def _chunk_text(text: str, chunk_size: int = CHUNK_CHARS) -> list[str]:
    """Split text into ~500-token segments, breaking at sentence boundaries."""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    current = ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= chunk_size:
            current = f"{current} {sent}".strip() if current else sent
        else:
            if current:
                chunks.append(current)
            current = sent
    if current:
        chunks.append(current)
    return chunks


def _fetch_statement_urls() -> list[tuple[str, str]]:
    """Fetch RBA media release URLs from 2022 to present. Prioritize rate-cycle statements."""
    all_items: list[tuple[str, str]] = []
    for year in range(2022, 2026):
        url = f"{RBA_BASE}/media-releases/{year}/"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a[href*='/media-releases/']"):
                href = link.get("href", "")
                if not re.search(r"/media-releases/\d{4}/mr-\d{2}-\d{2,3}\.html$", href.split("?")[0]):
                    continue
                title = link.get_text(strip=True)
                if not title or "RSS" in title:
                    continue
                full_url = href if href.startswith("http") else f"{RBA_BASE}{href}"
                all_items.append((title, full_url))
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
    # Prioritize rate-cycle statements
    def _score(item: tuple[str, str]) -> int:
        t = item[0].lower()
        return sum(1 for k in RATE_KEYWORDS if k in t)

    all_items.sort(key=_score, reverse=True)
    seen = set()
    unique: list[tuple[str, str]] = []
    for title, url in all_items:
        if url not in seen:
            seen.add(url)
            unique.append((title, url))
    return unique[:50]


def _fetch_statement_content(url: str) -> str:
    """Fetch and extract main content from a single RBA statement page."""
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # Remove nav, footer, share, enquiries
    for tag in soup.select("nav, footer, .share, .enquiries, [role='navigation']"):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile("content|main"))
    if not main:
        main = soup.body
    if not main:
        return ""
    text = main.get_text(separator=" ", strip=True)
    return text


def load_rba_historical() -> int:
    """
    Load 50 RBA statements (2022–present), chunk into 500-token segments,
    embed each chunk, insert into forex_documents with source=rba_historical.
    Returns total rows inserted.
    """
    urls = _fetch_statement_urls()
    logger.info("Found %d statements to load", len(urls))
    total_chunks = 0
    for i, (title, url) in enumerate(urls, 1):
        try:
            content = _fetch_statement_content(url)
            if not content or len(content) < 100:
                logger.warning("Skipping %s (insufficient content)", title[:50])
                continue
            chunks = _chunk_text(content)
            for chunk in chunks:
                ingest_document(chunk, source="rba_historical")
                total_chunks += 1
            logger.info("  %d/%d: %s (%d chunks)", i, len(urls), title[:50], len(chunks))
        except Exception as e:
            logger.warning("Failed %s: %s", url, e)
    return total_chunks


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-retrieval", action="store_true", help="Run retrieval tests after loading")
    args = parser.parse_args()

    rows = load_rba_historical()
    logger.info("Inserted %d chunks into forex_documents (source=rba_historical)", rows)

    if args.test_retrieval and rows > 0:
        from rag.ingest import retrieve_documents

        logger.info("--- Retrieval test: 'hawkish RBA statement inflation' ---")
        r1 = retrieve_documents("hawkish RBA statement inflation", top_k=10)
        rba_hist = [r for r in r1 if r.get("source") == "rba_historical"]
        for r in rba_hist[:5]:
            logger.info("  %.3f | %s", r["similarity"], (r.get("content") or "")[:100])

        logger.info("--- Retrieval test: 'RBA cutting rates dovish' ---")
        r2 = retrieve_documents("RBA cutting rates dovish", top_k=10)
        rba_hist2 = [r for r in r2 if r.get("source") == "rba_historical"]
        for r in rba_hist2[:5]:
            logger.info("  %.3f | %s", r["similarity"], (r.get("content") or "")[:100])
