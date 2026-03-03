"""
LlamaIndex + pgvector ingestion and retrieval for forex_documents.

Chunk + embed + insert into Supabase pgvector.
Uses OpenAI text-embedding-3-small (1536 dims) for embeddings.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
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


def build_pattern_text(signal_data: dict, technical_context: dict) -> str:
    """
    Builds a plain English description of a trading pattern
    for embedding and future RAG retrieval (Week 5B).

    This function stores memory only.
    It does not influence any signal, quality score, or LLM prompt.

    Args:
        signal_data: dict from signal_outcomes row
        technical_context: dict with indicators, structure, mtf keys

    Returns:
        str: plain English pattern description under 300 words
    """
    pair = str(signal_data.get("pair", "unknown"))
    direction = str(signal_data.get("direction", "unknown"))
    setup = str(signal_data.get("setup", technical_context.get("setup", "unknown")))
    entry = signal_data.get("entry") or signal_data.get("entry_price") or 0
    sl = signal_data.get("sl") or signal_data.get("stop_loss") or 0
    tp = signal_data.get("tp") or signal_data.get("take_profit") or 0
    rr = signal_data.get("risk_reward") or 2.0

    ind = technical_context.get("indicators") or {}
    struct = technical_context.get("structure") or {}
    mtf = technical_context.get("mtf") or {}
    levels = technical_context.get("levels") or {}

    rsi_val = ind.get("rsi_14")
    rsi_zone = ind.get("rsi_zone", "unknown")
    rsi_str = f"{rsi_zone} ({rsi_val})" if rsi_val is not None else rsi_zone

    session = str(signal_data.get("session", technical_context.get("session", "unknown")))
    d1_bias = str(mtf.get("d1_bias", "unknown"))
    h4_structure = str(mtf.get("h4_structure", "unknown"))
    timeframe_alignment = str(mtf.get("timeframe_alignment", "unknown"))
    ema_trend = str(ind.get("ema_trend", struct.get("ema_trend", "unknown")))
    structure_bias = str(struct.get("structure_bias", "unknown"))
    broke_asian_range = str(struct.get("broke_asian_range", "none"))
    atr_used = levels.get("atr_used") or ind.get("atr_14") or 0

    if not entry and levels:
        entry = levels.get("entry_price", 0)
    if not sl and levels:
        sl = levels.get("stop_loss", 0)
    if not tp and levels:
        tp = levels.get("take_profit", 0)
    if not rr and levels:
        rr = levels.get("risk_reward_ratio", 2.0)

    return (
        f"{pair} {direction} signal. Setup: {setup}. "
        f"Session: {session}. D1 bias {d1_bias}, H4 structure {h4_structure}. "
        f"Timeframe alignment {timeframe_alignment}. "
        f"RSI zone {rsi_str}. EMA trend {ema_trend}. "
        f"Structure bias {structure_bias}. Asian range: {broke_asian_range} broken. "
        f"ATR {atr_used}. Entry {entry}, SL {sl}, TP {tp}, R:R 1:{int(rr)}."
    )


def embed_and_store_pattern(
    signal_outcomes_id: int,
    signal_data: dict,
    technical_context: dict,
    outcome: str,
    pips_result: float,
) -> bool:
    """
    Builds pattern text, embeds with OpenAI,
    inserts into pattern_outcomes table.

    Called by signal_evaluator.py after resolution only.
    Never called during signal generation.
    Never influences trading decisions.

    Args:
        signal_outcomes_id: id from signal_outcomes row
        signal_data: full resolved row from signal_outcomes
        technical_context: stored at signal creation time
        outcome: "win" | "loss" | "expired"
        pips_result: actual pips result from resolution

    Returns:
        bool: True if stored successfully, False if failed
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("embed_and_store_pattern: OPENAI_API_KEY not set")
        return False

    try:
        pattern_text = build_pattern_text(signal_data, technical_context)
    except Exception as e:
        logger.error("build_pattern_text failed: %s", e)
        return False

    try:
        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=pattern_text)
        embedding = response.data[0].embedding
    except Exception as e:
        logger.error("embed_and_store_pattern: embedding failed: %s", e)
        return False

    ind = technical_context.get("indicators") or {}
    struct = technical_context.get("structure") or {}
    mtf = technical_context.get("mtf") or {}
    levels = technical_context.get("levels") or {}

    entry = float(signal_data.get("entry") or signal_data.get("entry_price") or 0)
    sl = float(signal_data.get("sl") or signal_data.get("stop_loss") or 0)
    tp = float(signal_data.get("tp") or signal_data.get("take_profit") or 0)
    rr = float(signal_data.get("risk_reward") or levels.get("risk_reward_ratio", 2.0))

    hit_tp = signal_data.get("hit_tp")
    hit_sl = signal_data.get("hit_sl")

    row = {
        "signal_outcomes_id": signal_outcomes_id,
        "pair": str(signal_data.get("pair", "unknown")),
        "direction": str(signal_data.get("direction", "unknown")),
        "setup": str(signal_data.get("setup", technical_context.get("setup", "unknown"))),
        "session": str(signal_data.get("session", technical_context.get("session", "unknown"))),
        "d1_bias": str(mtf.get("d1_bias")) if mtf.get("d1_bias") else None,
        "h4_structure": str(mtf.get("h4_structure")) if mtf.get("h4_structure") else None,
        "timeframe_alignment": str(mtf.get("timeframe_alignment")) if mtf.get("timeframe_alignment") else None,
        "rsi_zone": str(ind.get("rsi_zone")) if ind.get("rsi_zone") else None,
        "ema_trend": str(ind.get("ema_trend")) if ind.get("ema_trend") else None,
        "structure_bias": str(struct.get("structure_bias")) if struct.get("structure_bias") else None,
        "broke_asian_range": str(struct.get("broke_asian_range")) if struct.get("broke_asian_range") else None,
        "atr_used": float(levels.get("atr_used") or ind.get("atr_14") or 0),
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "risk_reward": rr,
        "outcome": outcome,
        "pips_result": pips_result,
        "hit_tp": hit_tp,
        "hit_sl": hit_sl,
        "embedding": embedding,
        "pattern_text": pattern_text,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        supabase = get_supabase()
        supabase.table("pattern_outcomes").insert(row).execute()
    except Exception as e:
        logger.error("embed_and_store_pattern: insert failed: %s", e)
        return False

    try:
        result = supabase.table("pattern_outcomes").select("id", count="exact").execute()
        pattern_count = getattr(result, "count", None) or len(result.data or [])
        if pattern_count in [50, 100, 200]:
            logger.info(
                "Pattern RAG milestone reached: %d patterns stored. "
                "Week 5B retrieval activation threshold: 100 patterns.",
                pattern_count,
            )
    except Exception:
        pass

    return True


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
