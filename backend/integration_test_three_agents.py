#!/usr/bin/env python3
"""
Integration test: MacroAgent + TechnicalAgent + JournalAgent for AUD/USD, GBP/USD, EUR/USD.
Prints complete state after all three agents. Verifies pipeline_health.
"""
import logging
import sys
from pathlib import Path

# Add backend to path
_backend = Path(__file__).resolve().parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from agents.graph import build_graph
from agents.graph import ForexState
from db.supabase_client import get_supabase

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PAIRS = ["AUD/USD", "GBP/USD", "EUR/USD"]


def run_integration_test() -> None:
    """Run three-agent pipeline for each pair, print complete state."""
    compiled = build_graph()

    for pair in PAIRS:
        logger.info("")
        logger.info("=" * 60)
        logger.info("PAIR: %s", pair)
        logger.info("=" * 60)
        initial: ForexState = {"pair": pair}
        result = compiled.invoke(initial)

        # Complete state after macro, technical, journal (coach runs but is placeholder)
        logger.info("--- Complete state after macro + technical + journal ---")
        for key in ["pair", "macro_sentiment", "technical_setup", "user_patterns"]:
            val = result.get(key)
            if val is not None:
                if isinstance(val, dict) and key in ("macro_sentiment", "technical_setup", "user_patterns"):
                    # Pretty-print agent outputs
                    logger.info("  %s:", key)
                    for k, v in val.items():
                        logger.info("    %s: %s", k, v)
                else:
                    logger.info("  %s: %s", key, val)
        logger.info("")


def check_pipeline_health() -> None:
    """Confirm pipeline_health has entries for macro_agent, technical_agent, journal_agent."""
    supabase = get_supabase()
    health = (
        supabase.table("pipeline_health")
        .select("source", "status", "checked_at")
        .order("checked_at", desc=True)
        .limit(50)
        .execute()
    )
    rows = health.data or []
    sources = {r["source"] for r in rows}
    required = {"macro_agent", "technical_agent", "journal_agent"}
    if required <= sources:
        logger.info("pipeline_health: macro_agent, technical_agent, journal_agent all logged")
    else:
        logger.warning("pipeline_health: missing %s", required - sources)
    logger.info("Recent pipeline_health sources: %s", sorted(sources))


def print_week2_review() -> None:
    """Print Week 2 review notes."""
    logger.info("")
    logger.info("--- Week 2 Review ---")
    logger.info("MacroAgent: RAG returns RBA content; dovish/neutral fits inflation moderating narrative.")
    logger.info("TechnicalAgent: Uses live OANDA H1 candles; setup/direction vary by pair. Verify on chart.")
    logger.info("JournalAgent: Win-rate gate applied: <30 trades or <52%% win rate -> market_patterns.")
    logger.info("Langfuse: Each agent has @observe; check dashboard for macro_agent, technical_agent, journal_agent spans.")


if __name__ == "__main__":
    run_integration_test()
    logger.info("")
    logger.info("--- pipeline_health check ---")
    check_pipeline_health()
    print_week2_review()
