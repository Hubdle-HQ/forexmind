"""
SignalAgent: Generates structured trade signal from full state.
Model: GPT-4o Mini. Output saved to signal_outcomes table.
"""
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langfuse import observe
from openai import OpenAI

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase
from rag.sources.price_data import fetch_candles

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"


def _extract_json(text: str) -> dict | None:
    """Extract JSON from model response. Handles markdown code blocks."""
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.replace("json", "").strip()
            if part.startswith("{"):
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _build_prompt(state: dict[str, Any]) -> str:
    """Build prompt for structured signal generation."""
    pair = state.get("pair", "AUD/USD")
    macro = state.get("macro_sentiment") or {}
    technical = state.get("technical_setup") or {}
    user_patterns = state.get("user_patterns") or {}
    coach_advice = state.get("coach_advice") or ""

    # Get current price from OANDA for realistic entry
    try:
        candles = fetch_candles(pair, count=1, granularity="H1")
        current_price = float(candles[-1]["c"]) if candles else 0.65
    except Exception:
        current_price = 0.65  # fallback

    return f"""You are a forex signal generator. Given the analysis below, produce a structured trade signal.

Pair: {pair}
Current approximate price: {current_price}

Macro: {macro.get('sentiment', 'neutral')} (confidence {macro.get('confidence', 0):.2f})
Technical: {technical.get('setup', 'unknown')} {technical.get('direction', 'NEUTRAL')} (quality {technical.get('quality', 0):.2f})
User mode: {user_patterns.get('mode', 'market_patterns')}

Coach recommendation:
{coach_advice}

Generate a trade signal. Use the current price as reference for entry, and calculate take_profit and stop_loss with a sensible risk_reward_ratio (e.g. 1.5 to 2.5). For BUY: entry < tp, sl below entry. For SELL: entry > tp, sl above entry.

Respond with valid JSON only, no other text. Use this exact structure:
{{
  "pair": "{pair}",
  "direction": "BUY" or "SELL",
  "entry_price": <float>,
  "take_profit": <float>,
  "stop_loss": <float>,
  "risk_reward_ratio": <float>,
  "confidence_percentage": <int 0-100>,
  "reasoning_summary": "<brief string>",
  "mode": "market_patterns" or "personal_edge",
  "generated_at": "<ISO 8601 timestamp>"
}}"""


@observe(name="signal_agent")
def run_signal_agent(state: dict[str, Any]) -> dict[str, Any]:
    """
    Generate structured signal from full state. Save to signal_outcomes.
    Returns { final_signal: dict or None, error: str or None }.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"final_signal": None, "error": "OPENAI_API_KEY not set"}

    prompt = _build_prompt(state)
    client = OpenAI(api_key=api_key)

    signal = None
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            text = (resp.choices[0].message.content or "").strip()
            signal = _extract_json(text)
            if signal is not None:
                break
            raise ValueError("Model returned non-JSON")
        except Exception as e:
            if attempt == 0:
                logger.warning("SignalAgent attempt 1 failed, retrying: %s", e)
            else:
                logger.exception("SignalAgent failed: %s", e)
                return {"final_signal": None, "error": str(e)}

    if signal is None:
        return {"final_signal": None, "error": "Could not parse structured output"}

    # Validate and normalize
    pair = str(signal.get("pair", state.get("pair", "AUD/USD")))
    direction = str(signal.get("direction", "BUY")).upper()
    if direction not in ("BUY", "SELL"):
        direction = "BUY"
    entry_price = float(signal.get("entry_price", 0))
    take_profit = float(signal.get("take_profit", 0))
    stop_loss = float(signal.get("stop_loss", 0))
    risk_reward = float(signal.get("risk_reward_ratio", 1.5))
    confidence_pct = int(signal.get("confidence_percentage", 70))
    confidence_pct = max(0, min(100, confidence_pct))
    reasoning = str(signal.get("reasoning_summary", ""))
    mode = str(signal.get("mode", "market_patterns"))
    if mode not in ("market_patterns", "personal_edge"):
        mode = "market_patterns"

    gen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    final_signal = {
        "pair": pair,
        "direction": direction,
        "entry_price": entry_price,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "risk_reward_ratio": risk_reward,
        "confidence_percentage": confidence_pct,
        "reasoning_summary": reasoning,
        "mode": mode,
        "generated_at": gen_at,
    }

    # Save to signal_outcomes
    try:
        signal_id = uuid.uuid4()
        trace_id = None
        try:
            from langfuse import get_client
            trace_id = get_client().get_current_trace_id()
        except Exception:
            pass
        insert_data = {
            "signal_id": str(signal_id),
            "pair": pair,
            "direction": direction,
            "entry": entry_price,
            "tp": take_profit,
            "sl": stop_loss,
            "hit_tp": None,
            "hit_sl": None,
            "pips_result": None,
            "generated_at": gen_at,
            "resolved_at": None,
        }
        if trace_id:
            insert_data["langfuse_trace_id"] = trace_id
        get_supabase().table("signal_outcomes").insert(insert_data).execute()
        final_signal["signal_id"] = str(signal_id)
        logger.info("Saved signal to signal_outcomes: %s", signal_id)
    except Exception as e:
        logger.exception("Failed to save signal: %s", e)
        final_signal["save_error"] = str(e)

    return {"final_signal": final_signal}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Minimal state for standalone test
    test_state = {
        "pair": "AUD/USD",
        "macro_sentiment": {"sentiment": "dovish", "confidence": 0.85},
        "technical_setup": {"setup": "trend continuation", "direction": "BUY", "quality": 0.8},
        "user_patterns": {"mode": "personal_edge", "win_rate": 0.6, "pattern_notes": "50 trades"},
        "coach_advice": "Strong confluence. TRADE.",
    }
    result = run_signal_agent(test_state)
    print("Signal:", json.dumps(result.get("final_signal"), indent=2))
    if result.get("error"):
        print("Error:", result["error"])
