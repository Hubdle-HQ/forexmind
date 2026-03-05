"""
CoachAgent: Synthesises macro, technical, and user patterns into a trade recommendation.
3-condition gate (all must pass): macro passes (strong macro OR neutral macro), technical quality > 0.55, no error.
Relaxed: neutral macro + strong technical is allowed (was: strong macro + strong technical only).
Model: Claude Sonnet.
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from langfuse import observe

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

logger = logging.getLogger(__name__)

MODEL = os.getenv("COACH_MODEL", "claude-sonnet-4-6")
MACRO_CONFIDENCE_THRESHOLD = 0.5
TECHNICAL_QUALITY_THRESHOLD = 0.55


def _build_prompt(
    pair: str,
    macro_sentiment: dict[str, Any],
    technical_setup: dict[str, Any],
    user_patterns: dict[str, Any],
) -> str:
    """Build structured prompt for Claude."""
    macro_sent = macro_sentiment.get("sentiment", "neutral")
    macro_conf = macro_sentiment.get("confidence", 0)
    tech_setup = technical_setup.get("setup", "unknown")
    tech_dir = technical_setup.get("direction", "NEUTRAL")
    tech_qual = technical_setup.get("quality", 0)
    mode = user_patterns.get("mode", "market_patterns")
    pattern_notes = user_patterns.get("pattern_notes", "")
    win_rate = user_patterns.get("win_rate", 0)
    trade_count = user_patterns.get("trade_count", 0)

    return f"""You are a forex trading coach. Given the following analysis for {pair}, provide a clear recommendation.

## Macro environment
- Sentiment: {macro_sent}
- Confidence: {macro_conf:.2f}
- Summary: What does the macro environment mean for this pair today? (1-2 sentences)

## Technical setup
- Setup: {tech_setup}
- Direction: {tech_dir}
- Quality: {tech_qual:.2f}
- Does the technical setup align with the macro view? Explain briefly.

## User pattern
- Mode: {mode}
- Notes: {pattern_notes}
- Win rate: {win_rate:.1%} ({trade_count} trades)
- Reference the user's personal pattern or market pattern depending on mode.

## Your task
1. Summarise what the macro environment means today.
2. Assess whether the technical setup aligns with the macro view.
3. Reference the user's pattern (personal_edge or market_patterns).
4. Make a clear recommendation: TRADE or NO TRADE, with a brief reason.

Respond with valid JSON only, no other text:
{{"coaching_note": "<your full coaching note as a string>", "should_trade": true or false}}"""


@observe(name="coach_agent")
def run_coach_agent(
    macro_sentiment: dict[str, Any] | None,
    technical_setup: dict[str, Any] | None,
    user_patterns: dict[str, Any] | None,
    pair: str = "AUD/USD",
    state_error: str | None = None,
) -> dict[str, Any]:
    """
    Apply 3-condition gate, then call Claude for synthesis.
    Returns { coaching_note, should_trade }.
    """
    macro_sentiment = macro_sentiment or {}
    technical_setup = technical_setup or {}
    user_patterns = user_patterns or {}

    # 3-condition gate
    macro_conf = float(macro_sentiment.get("confidence", 0))
    tech_qual = float(technical_setup.get("quality", 0))

    # Condition 3: no error in state or agent outputs
    has_error = (
        bool(state_error)
        or bool(macro_sentiment.get("error"))
        or bool(technical_setup.get("error"))
        or bool(user_patterns.get("error"))
    )
    if has_error:
        err_src = state_error or macro_sentiment.get("error") or technical_setup.get("error") or user_patterns.get("error")
        note = f"Gate failed: error in pipeline ({err_src}). Do not trade."
        return {"coaching_note": note, "should_trade": False, "rejection_reason": "error_gate"}
    macro_sent = str(macro_sentiment.get("sentiment", "neutral")).lower()
    macro_passes = macro_conf > MACRO_CONFIDENCE_THRESHOLD or macro_sent == "neutral"
    if not macro_passes:
        note = f"Gate failed: macro confidence {macro_conf:.2f} is not above {MACRO_CONFIDENCE_THRESHOLD} and macro is not neutral. Do not trade."
        return {"coaching_note": note, "should_trade": False, "rejection_reason": "macro_gate"}
    if tech_qual <= TECHNICAL_QUALITY_THRESHOLD:
        note = f"Gate failed: technical quality {tech_qual:.2f} is not above {TECHNICAL_QUALITY_THRESHOLD}. Do not trade."
        return {"coaching_note": note, "should_trade": False, "rejection_reason": "technical_quality_gate"}

    # All conditions pass — call Claude
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"coaching_note": "ANTHROPIC_API_KEY not set. Cannot generate recommendation.", "should_trade": False, "rejection_reason": "error_gate"}

    try:
        prompt = _build_prompt(pair, macro_sentiment, technical_setup, user_patterns)
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        result = json.loads(text)
        note = result.get("coaching_note", "")
        should_trade = bool(result.get("should_trade", False))
        out = {"coaching_note": note, "should_trade": should_trade}
        if not should_trade:
            out["rejection_reason"] = "claude_no_trade"  # Track LLM reasoning for evaluation
        return out
    except json.JSONDecodeError as e:
        logger.warning("CoachAgent: failed to parse Claude response: %s", e)
        return {"coaching_note": f"Could not parse recommendation: {e}", "should_trade": False, "rejection_reason": "error_gate"}
    except Exception as e:
        logger.exception("CoachAgent failed: %s", e)
        return {"coaching_note": f"Coach error: {e}", "should_trade": False, "rejection_reason": "error_gate"}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--test-pass", action="store_true", help="Test: all conditions pass")
    parser.add_argument("--test-fail-macro", action="store_true", help="Test: macro confidence 0.3")
    args = parser.parse_args()

    if args.test_fail_macro:
        # Macro confidence 0.3 — should fail gate
        result = run_coach_agent(
            macro_sentiment={"sentiment": "dovish", "confidence": 0.3},
            technical_setup={"setup": "trend continuation", "direction": "BUY", "quality": 0.8},
            user_patterns={"mode": "market_patterns", "win_rate": 0.6, "pattern_notes": "OK", "trade_count": 50},
            pair="AUD/USD",
            state_error=None,
        )
        print("Result (macro 0.3):", result)
        assert result["should_trade"] is False, "Expected should_trade=False"
        assert "0.30" in result["coaching_note"] or "0.3" in result["coaching_note"]
        print("OK: should_trade=False with note")
    elif args.test_pass:
        # All conditions pass
        result = run_coach_agent(
            macro_sentiment={"sentiment": "dovish", "confidence": 0.85},
            technical_setup={"setup": "trend continuation", "direction": "BUY", "quality": 0.8},
            user_patterns={"mode": "personal_edge", "win_rate": 0.6, "pattern_notes": "50 trades", "trade_count": 50},
            pair="AUD/USD",
            state_error=None,
        )
        print("Result (all pass):", result)
        assert result["should_trade"] is True, "Expected should_trade=True"
        print("OK: should_trade=True")
    else:
        print("Use --test-pass or --test-fail-macro")
