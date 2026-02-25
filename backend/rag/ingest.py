"""
LlamaIndex + pgvector ingestion and retrieval for forex_documents.

Chunk + embed + insert into Supabase pgvector.
Uses OpenAI text-embedding-3-small (1536 dims) for embeddings.
"""

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Add backend to path for db imports
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from db.supabase_client import get_supabase

load_dotenv(_backend.parent / ".env")

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def _get_embedding(text: str) -> list[float]:
    """Generate embedding for text using OpenAI."""
    client = OpenAI()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def ingest_document(text: str, source: str | None = None) -> None:
    """
    Generate embedding for text and insert into forex_documents.
    """
    embedding = _get_embedding(text)
    supabase = get_supabase()
    row: dict = {
        "content": text,
        "metadata": {},
        "embedding": embedding,
        "source": source,
    }
    supabase.table("forex_documents").insert(row).execute()
    logger.info("Ingested document (source=%s)", source or "unknown")


def retrieve_documents(query: str, top_k: int = 5) -> list[dict]:
    """
    Generate query embedding and return top_k similar documents with similarity scores.
    Requires match_forex_documents RPC (run backend/db/match_forex_documents.sql).
    """
    query_embedding = _get_embedding(query)
    # Pass as string — PostgREST doesn't reliably serialize list to vector type.
    embedding_str = json.dumps(query_embedding)
    supabase = get_supabase()
    response = supabase.rpc(
        "match_forex_documents",
        {
            "query_embedding": embedding_str,
            "match_threshold": 0.0,
            "match_count": top_k,
        },
    ).execute()
    rows = response.data if response.data is not None else []
    return [
        {
            "id": r["id"],
            "content": r["content"],
            "metadata": r.get("metadata") or {},
            "source": r.get("source"),
            "similarity": float(r["similarity"]) if r.get("similarity") is not None else 0.0,
        }
        for r in rows
    ]


# --- Test documents (RBA, interest rates, AUD) ---
TEST_DOCUMENTS: list[tuple[str, str]] = [
    (
        "The Reserve Bank of Australia held the cash rate at 4.35% at its February 2025 meeting. "
        "The Board noted that inflation remains above the 2-3% target band but is moderating. "
        "Further rate decisions will depend on incoming data.",
        "rba_statement",
    ),
    (
        "RBA Governor Michele Bullock stated that the Board is not ruling anything in or out regarding "
        "future interest rate moves. The path of rates will be data-dependent, with a focus on "
        "services inflation and the labour market.",
        "rba_speech",
    ),
    (
        "Australian dollar strength has been supported by resilient commodity prices and narrowing "
        "interest rate differentials with the US. AUD/USD remains sensitive to RBA and Fed policy "
        "divergence.",
        "aud_analysis",
    ),
    (
        "The RBA's latest Statement on Monetary Policy revised down growth forecasts and indicated "
        "that a restrictive policy stance will be maintained until inflation is clearly returning "
        "to target. Market pricing suggests rate cuts may begin in late 2025.",
        "rba_smp",
    ),
    (
        "Interest rates in Australia have risen sharply since May 2022. The full effect of these "
        "increases is still working through the economy. Household spending has slowed as mortgage "
        "repayments absorb a larger share of income.",
        "rba_rates",
    ),
]


def _run_round_trip_test() -> None:
    """Run ingest and retrieval tests, log baseline result."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    logger.info("Ingesting %d test documents...", len(TEST_DOCUMENTS))
    for text, source in TEST_DOCUMENTS:
        ingest_document(text, source=source)

    # Verify rows in Supabase
    supabase = get_supabase()
    count_resp = supabase.table("forex_documents").select("id", count="exact").execute()
    count = count_resp.count if hasattr(count_resp, "count") else len(count_resp.data or [])
    logger.info("Rows in forex_documents: %s", count)

    # Retrieval: relevant query
    logger.info('Retrieving with query "RBA interest rate decision"...')
    relevant_results = retrieve_documents("RBA interest rate decision", top_k=5)
    logger.info("Top 5 results (relevant query):")
    for i, r in enumerate(relevant_results, 1):
        logger.info("  %d. similarity=%.4f source=%s", i, r["similarity"], r.get("source"))
        logger.info("     content: %s...", (r["content"][:80] + "..." if len(r["content"]) > 80 else r["content"]))

    # Retrieval: unrelated query
    logger.info('Retrieving with unrelated query "best pizza recipes"...')
    unrelated_results = retrieve_documents("best pizza recipes", top_k=5)
    logger.info("Top 5 results (unrelated query):")
    for i, r in enumerate(unrelated_results, 1):
        logger.info("  %d. similarity=%.4f", i, r["similarity"])

    # Log first successful retrieval as baseline
    baseline = {
        "query": "RBA interest rate decision",
        "top_5_results": [
            {"id": r["id"], "similarity": r["similarity"], "source": r.get("source"), "content_preview": r["content"][:100]}
            for r in relevant_results
        ],
    }
    baseline_path = Path(__file__).resolve().parent.parent.parent / "baseline_retrieval.txt"
    with open(baseline_path, "w") as f:
        f.write("LlamaIndex + pgvector Round-Trip Test — Baseline Retrieval\n")
        f.write("=" * 60 + "\n\n")
        f.write(json.dumps(baseline, indent=2))
    logger.info("Baseline logged to %s", baseline_path)


if __name__ == "__main__":
    _run_round_trip_test()
