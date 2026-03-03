"""
ForexMind FastAPI backend.

Endpoints: /generate-signal, /health, /pipeline-status, /signal-accuracy
"""
import logging
import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add backend to path
_backend = Path(__file__).resolve().parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from agents.graph import build_graph
from db.supabase_client import get_supabase
from monitoring.daily_refresh import run_daily_refresh

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ForexMind API",
    version="1.0.0",
    description="Multi-agent Forex signal generation pipeline. Endpoints: generate-signal, health, pipeline-status, signal-accuracy.",
    servers=[{"url": "http://localhost:8000", "description": "Local development"}],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_pair(pair: str) -> str:
    """Convert AUDUSD or AUD/USD to AUD/USD."""
    p = pair.strip().upper().replace(" ", "")
    if "/" not in p and len(p) == 6:
        return f"{p[:3]}/{p[3:]}"
    return p if "/" in p else pair


class GenerateSignalRequest(BaseModel):
    pair: str = "AUD/USD"


class GenerateSignalResponse(BaseModel):
    pair: str
    macro_sentiment: dict | None
    technical_setup: dict | None
    user_patterns: dict | None
    coach_advice: str | None
    final_signal: dict | None
    should_trade: bool
    error: str | None


@app.post("/generate-signal", response_model=GenerateSignalResponse)
def generate_signal(
    req: GenerateSignalRequest | None = Body(default=None),
    pair: str | None = None,
) -> dict:
    """
    Run the full five-agent LangGraph pipeline for the given pair.
    Accepts pair in JSON body {"pair": "AUDUSD"} or query param ?pair=AUDUSD.
    """
    p = _normalize_pair((req.pair if req else None) or pair or "AUD/USD")
    try:
        compiled = build_graph()
        result = compiled.invoke({"pair": p})
        return {
            "pair": p,
            "macro_sentiment": result.get("macro_sentiment"),
            "technical_setup": result.get("technical_setup"),
            "user_patterns": result.get("user_patterns"),
            "coach_advice": result.get("coach_advice"),
            "final_signal": result.get("final_signal"),
            "should_trade": result.get("should_trade", False),
            "error": result.get("error"),
        }
    except Exception as e:
        logger.exception("generate-signal failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health() -> dict:
    """Return current status of all pipeline sources from pipeline_health (latest per source)."""
    try:
        supabase = get_supabase()
        # Get latest entry per source (last 24h)
        rows = (
            supabase.table("pipeline_health")
            .select("source", "status", "error_msg", "checked_at")
            .order("checked_at", desc=True)
            .limit(100)
            .execute()
        )
        data = rows.data or []
        # Dedupe by source (keep most recent)
        seen: set[str] = set()
        by_source: list[dict] = []
        for r in data:
            src = r.get("source", "")
            if src and src not in seen:
                seen.add(src)
                by_source.append({
                    "source": src,
                    "status": r.get("status"),
                    "error_msg": r.get("error_msg"),
                    "checked_at": r.get("checked_at"),
                })
        return {"sources": by_source, "ok": all(s.get("status") == "ok" for s in by_source)}
    except Exception as e:
        logger.exception("health failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pipeline-status")
def pipeline_status() -> dict:
    """Return last 24 hours of health log entries."""
    try:
        supabase = get_supabase()
        # Last 24h: use raw SQL or filter. Supabase doesn't have built-in time filter in select.
        # We'll get last N rows (enough for 24h of activity)
        rows = (
            supabase.table("pipeline_health")
            .select("id", "source", "status", "error_msg", "checked_at")
            .order("checked_at", desc=True)
            .limit(200)
            .execute()
        )
        data = rows.data or []
        # Filter to last 24h if checked_at is available
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        filtered = []
        for r in data:
            ct = r.get("checked_at")
            if ct:
                try:
                    dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    if dt >= cutoff:
                        filtered.append(r)
                except (ValueError, TypeError):
                    filtered.append(r)
            else:
                filtered.append(r)
        return {"entries": filtered[:100], "count": len(filtered)}
    except Exception as e:
        logger.exception("pipeline-status failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run-daily-refresh")
def run_daily_refresh_endpoint() -> dict:
    """
    Run daily data refresh: scrapers, embed new docs, mark old stale,
    signal evaluator, health check. Called by cron at 6am AEST.
    """
    try:
        results = run_daily_refresh()
        return {"ok": True, "results": results}
    except Exception as e:
        logger.exception("run-daily-refresh failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/latest-signal")
def latest_signal() -> dict:
    """
    Return the most recent signal_outcomes row (for verifying technical_context).
    Use after generating a signal to check if technical_context was stored.
    """
    try:
        supabase = get_supabase()
        rows = (
            supabase.table("signal_outcomes")
            .select("id, pair, direction, entry, tp, sl, generated_at, resolved_at, technical_context")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        data = rows.data or []
        if not data:
            return {"message": "No signals in signal_outcomes"}
        row = data[0]
        ctx = row.get("technical_context")
        has_ctx = bool(ctx and isinstance(ctx, dict) and len(ctx) > 0)
        return {
            "id": row.get("id"),
            "pair": row.get("pair"),
            "direction": row.get("direction"),
            "generated_at": row.get("generated_at"),
            "resolved_at": row.get("resolved_at"),
            "technical_context_populated": has_ctx,
            "technical_context": row.get("technical_context"),
        }
    except Exception as e:
        logger.exception("latest-signal failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signal-outcomes-status")
def signal_outcomes_status() -> dict:
    """
    Diagnostic: counts of signal_outcomes by state.
    Use to debug why signals aren't resolving.
    """
    try:
        from datetime import datetime, timedelta, timezone

        supabase = get_supabase()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        timeout_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
        timeout_str = timeout_cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Total
        all_rows = supabase.table("signal_outcomes").select("id", count="exact").execute()
        total = getattr(all_rows, "count", None) or len(all_rows.data or [])

        # Unresolved (resolved_at IS NULL)
        unresolved = (
            supabase.table("signal_outcomes")
            .select("id, pair, direction, entry, tp, sl, generated_at, resolved_at")
            .is_("resolved_at", "null")
            .execute()
        )
        unresolved_data = unresolved.data or []
        unresolved_count = len(unresolved_data)

        # Eligible for resolution: unresolved AND generated_at < 24h ago
        eligible = [r for r in unresolved_data if r.get("generated_at") and r.get("generated_at") < cutoff_str]
        eligible_count = len(eligible)

        # Too fresh (generated < 24h ago, won't be picked up yet)
        too_fresh = [r for r in unresolved_data if r.get("generated_at") and r.get("generated_at") >= cutoff_str]

        # Old enough to expire (generated > 72h ago, will be marked expired)
        can_expire = [r for r in eligible if r.get("generated_at") and r.get("generated_at") < timeout_str]

        return {
            "total": total,
            "unresolved_count": unresolved_count,
            "eligible_for_resolution": eligible_count,
            "too_fresh_count": len(too_fresh),
            "can_expire_count": len(can_expire),
            "cutoff_24h": cutoff_str,
            "cutoff_72h": timeout_str,
            "sample_unresolved": unresolved_data[:5] if unresolved_data else [],
        }
    except Exception as e:
        logger.exception("signal-outcomes-status failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/resolve-signals")
def resolve_signals_endpoint() -> dict:
    """
    Run ONLY the signal evaluator (no scrapers, RAG, etc).
    Use for testing resolution without full daily refresh.
    """
    try:
        from evals.signal_evaluator import resolve_unresolved_signals

        n = resolve_unresolved_signals()
        return {"ok": True, "signals_resolved": n}
    except Exception as e:
        logger.exception("resolve-signals failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signal-accuracy")
def signal_accuracy() -> dict:
    """Return win rate from signal_outcomes (resolved signals only)."""
    try:
        supabase = get_supabase()
        rows = (
            supabase.table("signal_outcomes")
            .select("hit_tp", "hit_sl")
            .execute()
        )
        data = rows.data or []
        resolved = [r for r in data if r.get("hit_tp") is not None or r.get("hit_sl") is not None]
        wins = sum(1 for r in resolved if r.get("hit_tp") is True)
        total = len(resolved)
        win_rate = wins / total if total > 0 else 0.0
        return {
            "resolved_count": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(win_rate, 4),
        }
    except Exception as e:
        logger.exception("signal-accuracy failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root() -> dict:
    """Root endpoint."""
    return {"service": "ForexMind API", "version": "1.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
