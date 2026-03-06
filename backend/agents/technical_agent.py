"""
TechnicalAgent: Fetches OANDA H1 candles, queries RAG for market pattern library,
classifies setup (breakout/mean-reversion/trend) and direction with GPT-4o Mini.
Output: setup, direction, quality.
"""
import json
import logging
import os
import sys
from pathlib import Path

from langfuse import observe
from openai import OpenAI

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase
from rag.ingest import ingest_document, retrieve_documents
from rag.sources.price_data import fetch_candles, fetch_d1_candles, fetch_h4_candles

from agents.indicators import (
    analyse_timeframes,
    calculate_indicators,
    calculate_levels,
    detect_patterns,
    detect_structure,
)

logger = logging.getLogger(__name__)

# Module-level cache for pre-calculated levels (keyed by pair)
_level_cache: dict[str, dict] = {}

# Module-level cache for technical context (indicators, structure, mtf, levels)
# Used by graph to pass technical_context to state for pattern storage (Week 5A)
_technical_context_cache: dict[str, dict] = {}

MODEL = "gpt-4o-mini"
TOP_K = 5
PATTERN_SOURCE = "market_pattern_library"

# 5 pattern descriptions for RAG (embed if not present)
PATTERN_DESCRIPTIONS: list[tuple[str, str]] = [
    (
        "London breakout: Price breaks above or below the Asian session range during London open (08:00-10:00 GMT). "
        "Strong momentum, high volume. Entry on break of range high/low. Stop beyond opposite side of range. "
        "Works best on GBP pairs, EUR/USD. Risk: false breakouts if range too tight.",
        "london_breakout",
    ),
    (
        "Mean reversion: Price extends beyond 2 standard deviations from a moving average (e.g. 20-period) "
        "then reverts. Fade the extreme. Entry when RSI oversold/overbought or price touches Bollinger bands. "
        "Works in ranging markets. Risk: strong trends can run further.",
        "mean_reversion",
    ),
    (
        "Trend continuation: Price in established trend (higher highs/higher lows or lower highs/lower lows). "
        "Entry on pullback to key level (EMA, fib, structure). Follow the trend direction. "
        "Works on H1/H4. Risk: trend exhaustion, reversal.",
        "trend_continuation",
    ),
    (
        "Range breakout: Price consolidates in a horizontal range (support/resistance). "
        "Entry on break of range with confirmation. Stop inside range. "
        "Works when volatility compresses before expansion. Risk: fake breakouts.",
        "range_breakout",
    ),
    (
        "News spike fade: High-impact news causes sharp spike. Fade the initial move after 15-30 minutes "
        "when price often retraces. Entry when momentum stalls. Stop beyond spike extreme. "
        "Works on NFP, CPI, central bank decisions. Risk: trend continuation after news.",
        "news_spike_fade",
    ),
]


def _log_health(source: str, status: str, error_msg: str | None = None) -> None:
    """Log to pipeline_health."""
    get_supabase().table("pipeline_health").insert(
        {"source": source, "status": status, "error_msg": error_msg}
    ).execute()


def _ensure_pattern_library() -> None:
    """Embed 5 market pattern descriptions if not already in RAG."""
    results = retrieve_documents("London breakout mean reversion trend continuation range breakout", top_k=5)
    pattern_sources = [r for r in results if r.get("source") == PATTERN_SOURCE]
    if len(pattern_sources) >= 3:
        return
    for text, name in PATTERN_DESCRIPTIONS:
        try:
            ingest_document(text, source=PATTERN_SOURCE)
            logger.info("Embedded pattern: %s", name)
        except Exception as e:
            logger.warning("Could not embed %s: %s", name, e)


def _format_price_context(candles: list[dict], last_n: int = 10) -> str:
    """Format last N candles as readable context for the LLM."""
    subset = candles[-last_n:] if len(candles) >= last_n else candles
    lines: list[str] = []
    for c in subset:
        lines.append(
            f"  {c.get('time', '')} | O={c['o']:.5f} H={c['h']:.5f} L={c['l']:.5f} C={c['c']:.5f} V={c.get('volume', 0)}"
        )
    return "\n".join(lines) if lines else "No candle data"


@observe(name="technical_agent")
def run_technical_agent(pair: str, macro_sentiment: dict | None = None) -> dict:
    """
    Fetch OANDA H1 candles, query RAG for pattern library, classify setup with GPT-4o Mini.
    Returns { setup, direction, quality }.
    """
    # Clear level cache at start of each run (in-memory, per process)
    _level_cache.clear()

    # Ensure pattern library exists
    _ensure_pattern_library()

    # Fetch price data
    try:
        candles = fetch_candles(pair, count=100, granularity="H1")
    except Exception as e:
        logger.exception("TechnicalAgent: price fetch failed: %s", e)
        _log_health("technical_agent", "failed", str(e))
        return {"setup": "unknown", "direction": "NEUTRAL", "quality": 0.0, "error": str(e)}

    if not candles:
        _log_health("technical_agent", "failed", "No candle data")
        return {"setup": "unknown", "direction": "NEUTRAL", "quality": 0.0, "error": "No candles"}

    try:
        indicators = calculate_indicators(candles)
    except ValueError as e:
        logger.error("TechnicalAgent: %s", e)
        _log_health("technical_agent", "failed", str(e))
        return {"setup": "unknown", "direction": "NEUTRAL", "quality": 0.0, "error": str(e)}

    if not indicators:
        _log_health("technical_agent", "failed", "Indicator calculation failed")
        return {"setup": "unknown", "direction": "NEUTRAL", "quality": 0.0, "error": "Indicator calculation failed"}

    # Build technical facts block for LLM
    rsi = indicators.get("rsi_14")
    rsi_str = f"{rsi}" if rsi is not None else "N/A"
    ema20 = indicators.get("ema_20")
    ema50 = indicators.get("ema_50")
    ema20_str = f"{ema20:.5f}" if ema20 is not None else "N/A"
    ema50_str = f"{ema50:.5f}" if ema50 is not None else "N/A"
    atr = indicators.get("atr_14")
    atr_str = f"{atr:.5f}" if atr is not None else "N/A"
    technical_facts = f"""--- TECHNICAL FACTS (calculated, not estimated) ---
Current Price: {indicators.get("current_price", 0):.5f}
RSI(14): {rsi_str} → Zone: {indicators.get("rsi_zone", "neutral")}
EMA20: {ema20_str} | EMA50: {ema50_str} → Trend: {indicators.get("ema_trend", "neutral")}
ATR(14): {atr_str}
Candles analysed: {indicators.get("candle_count", 0)} H1 candles
----------------------------------------------------"""

    structure = detect_structure(candles, indicators, pair=pair)
    structure_facts = f"""--- STRUCTURE DETECTION (coded rules, not estimated) ---
Higher Highs/Higher Lows: {structure.get("hh_hl", False)}
Lower Lows/Lower Highs: {structure.get("ll_lh", False)}
EMA Cross: {structure.get("ema_cross", "none")}
Broke Asian Range: {structure.get("broke_asian_range", "none")}
Price at EMA20 (pullback zone): {structure.get("at_ema_20", False)}
Structure Bias: {structure.get("structure_bias", "neutral")}
--------------------------------------------------------"""

    # Fetch H4 and D1 for multi-timeframe analysis
    h4_candles: list[dict] = []
    d1_candles: list[dict] = []
    try:
        h4_candles = fetch_h4_candles(pair, count=30)
    except Exception as e:
        logger.warning("TechnicalAgent: H4 fetch failed: %s — using empty", e)
    try:
        d1_candles = fetch_d1_candles(pair, count=30)
    except Exception as e:
        logger.warning("TechnicalAgent: D1 fetch failed: %s — using empty", e)

    mtf = analyse_timeframes(candles, h4_candles, d1_candles, pair)

    # HARD GATE — MTF conflict: no LLM call
    if mtf.get("conflict_detected") is True:
        logger.warning(
            "MTF conflict for %s: %s — returning NEUTRAL, no LLM call",
            pair,
            mtf.get("conflict_reason", "unknown"),
        )
        _technical_context_cache[pair] = {
            "indicators": indicators,
            "structure": structure,
            "mtf": mtf,
            "levels": _level_cache.get(pair) or {},
            "patterns": {
                "pattern_detected": False,
                "pattern_name": "no_pattern",
                "pattern_direction": "NEUTRAL",
                "quality_floor": 0.0,
                "quality_ceiling": 1.0,
                "conditions_met": [],
            },
        }
        _log_health("technical_agent", "ok")
        return {
            "setup": "no_setup",
            "direction": "NEUTRAL",
            "quality": 0.0,
        }

    mtf_facts = f"""--- MULTI-TIMEFRAME CONTEXT (coded, not estimated) ---
D1 Bias (big trend):    {mtf.get("d1_bias", "neutral")} | EMA Trend: {mtf.get("d1_ema_trend", "neutral")}
H4 Structure (setup):   {mtf.get("h4_structure", "neutral")} | EMA Trend: {mtf.get("h4_ema_trend", "neutral")}
H1 Direction (entry):   {mtf.get("h1_direction", "neutral")}
Timeframe Alignment:    {mtf.get("timeframe_alignment", "partial")}
------------------------------------------------------"""

    # ATR-based levels (only when structure_bias is bullish or bearish)
    levels_facts = ""
    structure_bias = structure.get("structure_bias", "neutral")
    current_price = indicators.get("current_price") or 0.0
    atr_val = indicators.get("atr_14")

    if structure_bias in ("bullish", "bearish") and atr_val and float(atr_val) > 0:
        direction_for_levels = "BUY" if structure_bias == "bullish" else "SELL"
        try:
            calculated_levels = calculate_levels(
                entry_price=float(current_price),
                direction=direction_for_levels,
                atr=float(atr_val),
                pair=pair,
            )
            _level_cache[pair] = calculated_levels
            levels_facts = f"""--- PRE-CALCULATED LEVELS (mathematical, fixed R:R) ---
Entry:       {calculated_levels["entry_price"]}
Stop Loss:   {calculated_levels["stop_loss"]}  ({calculated_levels["pip_value"]:.1f} pips)
Take Profit: {calculated_levels["take_profit"]}
R:R Ratio:   1:{int(calculated_levels["risk_reward_ratio"])}
ATR Used:    {calculated_levels["atr_used"]}
--------------------------------------------------------"""
        except (ValueError, TypeError) as e:
            logger.warning("calculate_levels failed: %s", e)

    # Week 6: detect_patterns after MTF gate and calculate_levels
    patterns = detect_patterns(
        candles=candles,
        indicators=indicators,
        structure=structure,
        mtf=mtf,
        pair=pair,
    )

    # Build pattern block (only when pattern detected)
    pattern_facts = ""
    if patterns.get("pattern_detected") is True:
        pattern_facts = f"""--- PATTERN DETECTION (coded rules, not estimated) ---
Pattern Identified:  {patterns.get("pattern_name", "unknown")}
Direction Signal:    {patterns.get("pattern_direction", "NEUTRAL")}
Quality Range:       {patterns.get("quality_floor", 0)} — {patterns.get("quality_ceiling", 1)}
Conditions Met:      {", ".join(patterns.get("conditions_met", []))}
------------------------------------------------------

"""

    # Fallback: structure_follow when no coded pattern but structure_bias is clear
    # Safeguard: never allow when structure_bias = neutral (avoids random trades)
    structure_bias = structure.get("structure_bias", "neutral")
    if not patterns.get("pattern_detected") and structure_bias in ("bullish", "bearish"):
        direction = "BUY" if structure_bias == "bullish" else "SELL"
        quality = 0.67  # midpoint of 0.60–0.75 range
        _technical_context_cache[pair] = {
            "indicators": indicators,
            "structure": structure,
            "mtf": mtf,
            "levels": _level_cache.get(pair) or {},
            "patterns": {
                "pattern_detected": True,
                "pattern_name": "structure_follow",
                "pattern_direction": direction,
                "quality_floor": 0.60,
                "quality_ceiling": 0.75,
                "conditions_met": [
                    f"structure_bias {structure_bias}",
                    "no coded pattern",
                    "direction aligned",
                ],
            },
        }
        _log_health("technical_agent", "ok")
        logger.info("TechnicalAgent: structure_follow fallback for %s %s", pair, direction)
        return {
            "setup": "structure_follow",
            "direction": direction,
            "quality": quality,
        }

    # Query RAG for pattern descriptions
    query = "London breakout mean reversion trend continuation range breakout news spike fade"
    docs = retrieve_documents(query, top_k=TOP_K)
    pattern_context = "\n\n---\n\n".join(d.get("content", "") for d in docs)

    if not pattern_context.strip():
        pattern_context = "\n".join(
            f"- {name}: {text[:200]}..." for text, name in PATTERN_DESCRIPTIONS
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _log_health("technical_agent", "failed", "OPENAI_API_KEY not set")
        return {"setup": "unknown", "direction": "NEUTRAL", "quality": 0.0, "error": "No API key"}

    macro_hint = ""
    if macro_sentiment:
        macro_hint = f"\nMacro context: {macro_sentiment.get('sentiment', '')} (confidence {macro_sentiment.get('confidence', 0):.2f}). Use only as context, not as trading signal."

    levels_instruction = ""
    if levels_facts:
        levels_instruction = """
The SL and TP levels above are mathematically calculated using ATR. You must use these exact values in your output.
Do not recalculate, adjust, or estimate SL/TP yourself.
The R:R ratio is fixed at 1:2 — do not change it.
Your job is setup name, direction, and quality score only.
"""

    pattern_instruction = ""
    if pattern_facts:
        pattern_instruction = """
If and only if the PATTERN DETECTION block is present:
Direction law:
- pattern_direction is determined by coded rules
- If pattern_direction = BUY you must output BUY
- If pattern_direction = SELL you must output SELL
- You cannot override coded pattern direction

Quality law:
- Your quality score must be >= quality_floor
- Your quality score must be <= quality_ceiling
- You cannot score outside this range for any reason

Setup name law:
- Use pattern_name exactly as provided
- Do not rename, generalise, or modify it

If no PATTERN DETECTION block is present:
- Determine setup name and direction from other blocks
- Use full quality range as before
- System works exactly as Weeks 1-5
"""

    prompt = f"""You are a forex technical analyst. Given the calculated technical indicators and market pattern descriptions, identify the setup forming and direction.

Pair: {pair}

{technical_facts}

{structure_facts}

{mtf_facts}
{pattern_facts}
{levels_facts}

Market pattern library:
{pattern_context}
{macro_hint}

You are receiving pre-calculated technical facts and coded structure detection results. Do NOT second-guess these numbers — they are mathematically calculated. Your job is to synthesise them into a setup name, direction, and quality score.

Timeframe alignment is pre-calculated using coded rules. You cannot override it.

Direction law — you must follow these without exception:
- If d1_bias = bullish → you may only generate BUY or NEUTRAL
- If d1_bias = bearish → you may only generate SELL or NEUTRAL
- If d1_bias = neutral → either direction allowed

Quality rules:
- timeframe_alignment = full → quality floor is 0.70
- timeframe_alignment = partial → quality ceiling is 0.75
- timeframe_alignment = conflict → this block will never reach you
{levels_instruction}
{pattern_instruction}
Rules you must follow:
- If structure_bias = bullish → direction should be BUY unless RSI is overbought
- If structure_bias = bearish → direction should be SELL unless RSI is oversold
- If structure_bias = neutral → quality score must be below 0.65
- If broke_asian_range = up → this is a breakout setup, name it 'asian range breakout'
- If at_ema_20 = True AND hh_hl = True → this is a 'trend continuation pullback'
- If ema_cross = bullish → this is an 'ema crossover' setup
- Quality score must reflect how many signals align:
  1 signal aligns = 0.55-0.65
  2 signals align = 0.65-0.75
  3+ signals align = 0.75-0.90

Answer:
1. What setup is forming? (e.g. London breakout, mean reversion, trend continuation, range breakout, news spike fade, asian range breakout, trend continuation pullback, ema crossover, or none/unknown)
2. What direction? BUY or SELL (or NEUTRAL if no clear bias)
3. Confidence score 0 to 1 (how confident are you in this setup?)

Respond with valid JSON only, no other text:
{{"setup": "<setup name>", "direction": "BUY|SELL|NEUTRAL", "quality": <float 0-1>}}"""

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content or "").strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        result = json.loads(text)
        setup = result.get("setup", "unknown")
        direction = result.get("direction", "NEUTRAL").upper()
        if direction not in ("BUY", "SELL", "NEUTRAL"):
            direction = "NEUTRAL"
        quality = float(result.get("quality", 0.5))
        quality = max(0.0, min(1.0, quality))

        _technical_context_cache[pair] = {
            "indicators": indicators,
            "structure": structure,
            "mtf": mtf,
            "levels": _level_cache.get(pair) or {},
            "patterns": patterns,
        }
        _log_health("technical_agent", "ok")
        return {
            "setup": setup,
            "direction": direction,
            "quality": quality,
        }
    except Exception as e:
        logger.exception("TechnicalAgent failed: %s", e)
        _log_health("technical_agent", "failed", str(e))
        return {"setup": "unknown", "direction": "NEUTRAL", "quality": 0.0, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    for pair in ["AUD/USD", "EUR/USD", "GBP/USD"]:
        result = run_technical_agent(pair)
        print(f"{pair}: {json.dumps(result, indent=2)}")
