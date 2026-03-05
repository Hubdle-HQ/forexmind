"""
Signal rejection logging — records pipeline runs where no signal was generated.
Tracks: gate failures (macro_gate, technical_quality_gate, error_gate) and
Claude NO TRADE decisions (claude_no_trade) with full reasoning in rejection_details.
Used for evaluation: rejection distribution, threshold tuning, setup quality analysis.
"""
import logging
from typing import Any

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def log_signal_rejection(
    pair: str,
    rejection_reason: str,
    rejection_details: str | None = None,
    macro_sentiment: dict | None = None,
    technical_setup: dict | None = None,
    technical_context: dict | None = None,
    error_message: str | None = None,
    langfuse_trace_id: str | None = None,
) -> None:
    """
    Insert a row into signal_rejections when the CoachAgent gate fails.
    Fails gracefully (logs warning) if Supabase is unavailable.
    """
    try:
        macro_sent = str(macro_sentiment.get("sentiment", "neutral")) if macro_sentiment else None
        macro_conf = float(macro_sentiment.get("confidence", 0)) if macro_sentiment else None
        tech_qual = float(technical_setup.get("quality", 0)) if technical_setup else None
        tech_setup = str(technical_setup.get("setup", "unknown")) if technical_setup else None
        tech_dir = str(technical_setup.get("direction", "NEUTRAL")) if technical_setup else None

        row: dict[str, Any] = {
            "pair": pair,
            "rejection_reason": rejection_reason,
            "rejection_details": rejection_details,
            "macro_sentiment": macro_sent,
            "macro_confidence": macro_conf,
            "technical_quality": tech_qual,
            "technical_setup": tech_setup,
            "technical_direction": tech_dir,
            "technical_context": technical_context,
            "error_message": error_message,
            "langfuse_trace_id": langfuse_trace_id,
        }
        # Remove None values to avoid overwriting defaults
        row = {k: v for k, v in row.items() if v is not None}

        get_supabase().table("signal_rejections").insert(row).execute()
        logger.info("Logged signal rejection for %s: %s", pair, rejection_reason)
    except Exception as e:
        logger.error(
            "Failed to log signal rejection for %s (table may not exist — run migration 003): %s",
            pair,
            e,
            exc_info=True,
        )
