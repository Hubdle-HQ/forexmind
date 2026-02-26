"""
JournalAgent: Queries RAG for user trades matching pair and setup type,
calculates win rate, applies win-rate gate to return mode (market_patterns or personal_edge).
Output: mode, win_rate, pattern_notes, trade_count.
"""
import logging
import re
import sys
from pathlib import Path

from langfuse import observe

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase
from rag.ingest import retrieve_documents

logger = logging.getLogger(__name__)


def _log_health(source: str, status: str, error_msg: str | None = None) -> None:
    """Log to pipeline_health."""
    get_supabase().table("pipeline_health").insert(
        {"source": source, "status": status, "error_msg": error_msg}
    ).execute()

TRADE_SOURCE = "user_trade"
TOP_K = 50
WIN_RATE_THRESHOLD = 0.52
MIN_TRADES_FOR_PERSONAL_EDGE = 30


def _parse_trade_outcome(content: str) -> str | None:
    """Extract outcome (win/loss) from trade content. Returns 'win', 'loss', or None."""
    m = re.search(r"outcome:\s*(\w+)", content, re.IGNORECASE)
    if m:
        o = m.group(1).lower()
        if o in ("win", "loss"):
            return o
    return None


def _parse_trade_user_id(content: str) -> str:
    """Extract user_id from trade content."""
    m = re.search(r"user_id:\s*(\S+)", content, re.IGNORECASE)
    return m.group(1) if m else ""


def _trades_match_pair_setup(content: str, pair: str, setup_type: str, user_id: str) -> bool:
    """Check if trade content matches pair, setup_type, and user_id."""
    pair_norm = pair.upper().replace("/", " ").replace("_", " ").strip()
    pair_compact = pair_norm.replace(" ", "")
    setup_norm = setup_type.lower().replace(" ", "_")
    content_upper = content.upper()
    content_lower = content.lower()
    has_pair = pair_norm in content_upper or pair_compact in content_upper.replace(" ", "").replace("/", "")
    has_setup = setup_norm in content_lower
    has_user = not user_id or f"user_id: {user_id}" in content or f"user_id:{user_id}" in content
    return has_pair and has_setup and has_user


@observe(name="journal_agent")
def run_journal_agent(
    pair: str,
    setup_type: str,
    user_id: str = "default",
) -> dict:
    """
    Query RAG for trades matching pair and setup type, calculate win rate, apply win-rate gate.
    Returns { mode, win_rate, pattern_notes, trade_count }.
    """
    try:
        query = f"{pair} {setup_type} user trade"
        docs = retrieve_documents(query, top_k=TOP_K)

        # Filter to user_trade source and matching pair/setup/user
        trades: list[dict] = []
        for d in docs:
            if d.get("source") != TRADE_SOURCE:
                continue
            content = d.get("content", "")
            if not _trades_match_pair_setup(content, pair, setup_type, user_id):
                continue
            outcome = _parse_trade_outcome(content)
            if outcome:
                trades.append({"outcome": outcome, "content": content})

        wins = sum(1 for t in trades if t["outcome"] == "win")
        total = len(trades)
        win_rate = wins / total if total > 0 else 0.0

        # Win-rate gate
        if total < MIN_TRADES_FOR_PERSONAL_EDGE:
            result = {
                "mode": "market_patterns",
                "win_rate": win_rate,
                "pattern_notes": f"Fewer than {MIN_TRADES_FOR_PERSONAL_EDGE} trades for this pair/setup. Use market patterns.",
                "trade_count": total,
            }
        elif win_rate < WIN_RATE_THRESHOLD:
            result = {
                "mode": "market_patterns",
                "win_rate": win_rate,
                "pattern_notes": f"Personal pattern underperforming (win rate {win_rate:.1%} < {WIN_RATE_THRESHOLD:.0%}). Use market patterns.",
                "trade_count": total,
            }
        else:
            result = {
                "mode": "personal_edge",
                "win_rate": win_rate,
                "pattern_notes": f"Personal edge: {total} trades, {win_rate:.1%} win rate for {pair} {setup_type}.",
                "trade_count": total,
            }
        _log_health("journal_agent", "ok")
        return result
    except Exception as e:
        logger.exception("JournalAgent failed: %s", e)
        _log_health("journal_agent", "failed", str(e))
        return {
            "mode": "market_patterns",
            "win_rate": 0.0,
            "pattern_notes": f"Error: {e}",
            "trade_count": 0,
        }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="AUD/USD", help="Currency pair")
    parser.add_argument("--setup", default="trend_continuation", help="Setup type")
    parser.add_argument("--user-id", default="default", help="User ID")
    args = parser.parse_args()

    result = run_journal_agent(args.pair, args.setup, args.user_id)
    print("Result:", result)
