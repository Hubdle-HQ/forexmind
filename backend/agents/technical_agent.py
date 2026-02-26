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
from rag.sources.price_data import fetch_candles

logger = logging.getLogger(__name__)

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

    price_context = _format_price_context(candles, last_n=10)

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

    prompt = f"""You are a forex technical analyst. Given the last 10 H1 candles and market pattern descriptions, identify the setup forming and direction.

Pair: {pair}

Last 10 H1 candles (OHLCV):
{price_context}

Market pattern library:
{pattern_context}
{macro_hint}

Answer:
1. What setup is forming? (e.g. London breakout, mean reversion, trend continuation, range breakout, news spike fade, or none/unknown)
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
