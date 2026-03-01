"""
Signal Outcome Evaluator — Auto-resolve signal_outcomes 24h after generation.

Queries unresolved signals, fetches OANDA price data, determines TP/SL hit order,
updates rows, and provides rolling 30-day win rate.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase
from rag.sources.price_data import fetch_candles

logger = logging.getLogger(__name__)

# H1 candles: 72 covers ~3 days for safety
CANDLE_COUNT = 72
CANDLE_GRANULARITY = "H1"
RESOLVE_AFTER_HOURS = 24
RESOLVE_TIMEOUT_HOURS = 72  # If neither TP nor SL hit after this, mark as expired


def _pip_size(pair: str) -> float:
    """Return pip size for pair. JPY pairs use 0.01, others 0.0001."""
    pair_upper = pair.upper().replace("/", "")
    if "JPY" in pair_upper:
        return 0.01
    return 0.0001


def _pips_result(pair: str, direction: str, entry: float, hit_tp: bool, tp: float, sl: float) -> float:
    """Compute pips result: positive for win, negative for loss."""
    pip = _pip_size(pair)
    if direction == "BUY":
        if hit_tp:
            return round((tp - entry) / pip, 1)
        return round((entry - sl) / pip, 1) * -1
    # SELL
    if hit_tp:
        return round((entry - tp) / pip, 1)
    return round((sl - entry) / pip, 1) * -1


def _resolve_single(
    row: dict[str, Any],
    candles: list[dict],
    generated_at: datetime,
) -> tuple[bool, bool, float] | None:
    """
    Determine TP/SL outcome from candles. Returns (hit_tp, hit_sl, pips_result) or None if unresolved.
    Candles must be sorted by time ascending.
    """
    pair = str(row.get("pair", ""))
    direction = str(row.get("direction", "BUY")).upper()
    entry = float(row.get("entry", 0))
    tp = float(row.get("tp", 0))
    sl = float(row.get("sl", 0))

    if direction not in ("BUY", "SELL") or entry <= 0 or tp <= 0 or sl <= 0:
        return None

    # Filter candles to those after generated_at
    gen_ts = generated_at.timestamp() if hasattr(generated_at, "timestamp") else generated_at
    filtered = []
    for c in candles:
        t = c.get("time")
        if not t:
            continue
        # OANDA returns ISO strings (e.g. "2026-02-24T12:00:00.000000000Z")
        try:
            if isinstance(t, str):
                s = t.replace("Z", "+00:00").split(".")[0]
                ct = datetime.fromisoformat(s)
            else:
                ct = t
            if hasattr(ct, "timestamp"):
                ct_ts = ct.timestamp()
            else:
                continue
            if ct_ts >= gen_ts:
                filtered.append({**c, "_ts": ct_ts})
        except Exception:
            continue

    filtered.sort(key=lambda x: x["_ts"])

    hit_tp_first: bool | None = None
    for c in filtered:
        h, l = float(c.get("h", 0)), float(c.get("l", 0))
        o, cl = float(c.get("o", 0)), float(c.get("c", 0))
        if h <= 0 or l <= 0:
            continue

        if direction == "BUY":
            tp_hit = h >= tp
            sl_hit = l <= sl
        else:  # SELL
            tp_hit = l <= tp
            sl_hit = h >= sl

        if tp_hit and sl_hit:
            # Both in same candle: use candle direction
            bullish = cl > o
            if direction == "BUY":
                hit_tp_first = bullish
            else:
                hit_tp_first = not bullish
            break
        if tp_hit:
            hit_tp_first = True
            break
        if sl_hit:
            hit_tp_first = False
            break

    if hit_tp_first is None:
        return None

    hit_tp = hit_tp_first
    hit_sl = not hit_tp_first
    pips = _pips_result(pair, direction, entry, hit_tp, tp, sl)
    return (hit_tp, hit_sl, pips)


def _parse_generated_at(val: Any) -> datetime | None:
    """Parse generated_at to datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val
    if isinstance(val, str):
        try:
            s = val.replace("Z", "+00:00").split(".")[0]
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except (ValueError, TypeError):
            return None
    return None


def resolve_unresolved_signals() -> int:
    """
    Query signal_outcomes for unresolved signals (resolved_at IS NULL, generated_at > 24h ago).
    For each: fetch OANDA candles, determine TP/SL outcome, update row.
    Returns count of resolved signals.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RESOLVE_AFTER_HOURS)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    supabase = get_supabase()
    rows = (
        supabase.table("signal_outcomes")
        .select("id, pair, direction, entry, tp, sl, generated_at, langfuse_trace_id")
        .is_("resolved_at", "null")
        .lt("generated_at", cutoff_str)
        .execute()
    )
    data = rows.data or []
    resolved_count = 0

    for row in data:
        row_id = row.get("id")
        pair = str(row.get("pair", ""))
        gen_at = _parse_generated_at(row.get("generated_at"))
        if not gen_at:
            logger.warning("Signal %s has invalid generated_at, skipping", row_id)
            continue

        try:
            candles = fetch_candles(pair, count=CANDLE_COUNT, granularity=CANDLE_GRANULARITY)
        except Exception as e:
            logger.exception("Failed to fetch candles for %s: %s", pair, e)
            continue

        result = _resolve_single(row, candles, gen_at)
        if result is None:
            # Timeout: if signal is older than RESOLVE_TIMEOUT_HOURS, mark as expired
            age_hours = (datetime.now(timezone.utc) - gen_at).total_seconds() / 3600
            if age_hours >= RESOLVE_TIMEOUT_HOURS:
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                try:
                    supabase.table("signal_outcomes").update({
                        "hit_tp": False,
                        "hit_sl": False,
                        "pips_result": 0.0,
                        "resolved_at": now_str,
                    }).eq("id", row_id).execute()
                    resolved_count += 1
                    logger.info("Expired signal %s (no TP/SL hit within %dh)", row_id, RESOLVE_TIMEOUT_HOURS)
                except Exception as e:
                    logger.exception("Failed to expire signal %s: %s", row_id, e)
            else:
                logger.debug("Signal %s could not be resolved (no TP/SL hit in window)", row_id)
            continue

        hit_tp, hit_sl, pips_result = result
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            supabase.table("signal_outcomes").update({
                "hit_tp": hit_tp,
                "hit_sl": hit_sl,
                "pips_result": pips_result,
                "resolved_at": now_str,
            }).eq("id", row_id).execute()
            resolved_count += 1
            logger.info("Resolved signal %s: hit_tp=%s hit_sl=%s pips=%s", row_id, hit_tp, hit_sl, pips_result)

            # Langfuse score logging (when langfuse_trace_id is available in schema)
            _log_langfuse_score(row_id, row, hit_tp)
        except Exception as e:
            logger.exception("Failed to update signal %s: %s", row_id, e)

    return resolved_count


def _log_langfuse_score(row_id: int, row: dict[str, Any], hit_tp: bool) -> None:
    """
    Log score 1.0 (win) or 0.0 (loss) to the originating Langfuse trace.
    Requires langfuse_trace_id column in signal_outcomes and signal_agent to store it.
    No-op when trace_id is not available.
    """
    trace_id = row.get("langfuse_trace_id") if isinstance(row, dict) else None
    if not trace_id:
        return
    try:
        from langfuse import get_client
        langfuse = get_client()
        score = 1.0 if hit_tp else 0.0
        langfuse.create_score(
            trace_id=str(trace_id),
            name="signal_outcome",
            value=score,
            data_type="NUMERIC",
            comment="TP hit" if hit_tp else "SL hit",
        )
        logger.info("Logged Langfuse score %.1f for trace %s (signal %s)", score, trace_id, row_id)
    except Exception as e:
        logger.warning("Langfuse score logging failed for signal %s: %s", row_id, e)


def get_rolling_30d_win_rate() -> dict[str, Any]:
    """
    Compute rolling 30-day win rate from resolved signals.
    Excludes expired signals (hit_tp=False and hit_sl=False) from win rate.
    Returns dict with: win_rate, resolved_count, wins, losses.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    supabase = get_supabase()
    rows = (
        supabase.table("signal_outcomes")
        .select("hit_tp", "hit_sl")
        .not_.is_("resolved_at", "null")
        .gte("resolved_at", cutoff_str)
        .execute()
    )
    data = rows.data or []
    # Exclude expired (neither TP nor SL hit)
    resolved = [r for r in data if r.get("hit_tp") is True or r.get("hit_sl") is True]
    wins = sum(1 for r in resolved if r.get("hit_tp") is True)
    total = len(resolved)
    win_rate = round(wins / total, 4) if total > 0 else 0.0
    return {
        "win_rate": win_rate,
        "resolved_count": total,
        "wins": wins,
        "losses": total - wins,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    n = resolve_unresolved_signals()
    logger.info("Resolved %d signals", n)
    stats = get_rolling_30d_win_rate()
    logger.info("Rolling 30d: win_rate=%.2f%% resolved=%d wins=%d losses=%d",
                stats["win_rate"] * 100, stats["resolved_count"], stats["wins"], stats["losses"])
