"""
MacroAgent: Queries RAG for RBA context, classifies sentiment (hawkish/dovish/neutral).
Model: Gemini Flash 2.0 (primary), GPT-4o-mini (fallback for testing). Output: sentiment, confidence, source_docs.
"""
import json
import logging
import os
import sys
from pathlib import Path

import google.generativeai as genai
from langfuse import observe
from openai import OpenAI

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase
from rag.ingest import retrieve_documents

logger = logging.getLogger(__name__)

MODEL_GEMINI = "gemini-2.0-flash"
MODEL_FALLBACK = "gpt-4o-mini"
TOP_K = 5


def _log_health(source: str, status: str, error_msg: str | None = None) -> None:
    """Log to pipeline_health."""
    get_supabase().table("pipeline_health").insert(
        {"source": source, "status": status, "error_msg": error_msg}
    ).execute()


def _parse_sentiment_response(text: str) -> tuple[str, float]:
    """Parse JSON from model response. Returns (sentiment, confidence)."""
    if "```" in text:
        text = text.split("```")[1].replace("json", "").strip()
    result = json.loads(text)
    sentiment = result.get("sentiment", "neutral").lower()
    if sentiment not in ("hawkish", "dovish", "neutral"):
        sentiment = "neutral"
    confidence = float(result.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))
    return sentiment, confidence


def _classify_with_openai(prompt: str) -> tuple[str, float]:
    """Fallback: classify using GPT-4o-mini."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=MODEL_FALLBACK,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content or ""
    return _parse_sentiment_response(text.strip())


@observe(name="macro_agent")
def run_macro_agent(pair: str) -> dict:
    """
    Query RAG for RBA context, classify sentiment with Gemini Flash 2.0.
    Returns { sentiment, confidence, source_docs }.
    """
    # RAG retrieval — RBA context for AUD
    query = "RBA Reserve Bank Australia monetary policy interest rate inflation"
    if "AUD" in pair.upper() or "USD" in pair.upper():
        query = "RBA Australia monetary policy cash rate statement"
    docs = retrieve_documents(query, top_k=TOP_K)
    context = "\n\n---\n\n".join(d.get("content", "") for d in docs)
    source_docs = [{"content": d.get("content", "")[:200], "similarity": d.get("similarity")} for d in docs]

    if not context.strip():
        _log_health("macro_agent", "failed", "No RAG context retrieved")
        return {"sentiment": "neutral", "confidence": 0.0, "source_docs": [], "error": "No context"}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _log_health("macro_agent", "failed", "GEMINI_API_KEY not set")
        return {"sentiment": "neutral", "confidence": 0.0, "source_docs": source_docs, "error": "No API key"}

    prompt = f"""You are a central bank sentiment analyst. Classify the RBA (Reserve Bank of Australia) stance from the following documents.

Documents:
{context}

Classify the RBA's monetary policy sentiment as exactly one of: hawkish, dovish, neutral.
- hawkish: tightening bias, rate hikes, inflation concern
- dovish: easing bias, rate cuts, growth concern
- neutral: balanced, data-dependent, no clear bias

Respond with valid JSON only, no other text:
{{"sentiment": "hawkish|dovish|neutral", "confidence": <float 0-1>}}"""

    # Try Gemini first
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_GEMINI)
    used_model = MODEL_GEMINI

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        sentiment, confidence = _parse_sentiment_response(text)
        _log_health("macro_agent", "ok")
        return {
            "sentiment": sentiment,
            "confidence": confidence,
            "source_docs": source_docs,
            "model": used_model,
        }
    except Exception as e:
        logger.warning("MacroAgent Gemini failed (%s), trying fallback: %s", used_model, e)
        # Fallback to GPT-4o-mini for testing (e.g. 429 quota)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                sentiment, confidence = _classify_with_openai(prompt)
                used_model = MODEL_FALLBACK
                _log_health("macro_agent", "ok")
                return {
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "source_docs": source_docs,
                    "model": used_model,
                }
            except Exception as fallback_e:
                logger.exception("MacroAgent fallback failed: %s", fallback_e)
                _log_health("macro_agent", "failed", str(fallback_e))
                return {"sentiment": "neutral", "confidence": 0.0, "source_docs": source_docs, "error": str(fallback_e)}
        _log_health("macro_agent", "failed", str(e))
        return {"sentiment": "neutral", "confidence": 0.0, "source_docs": source_docs, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = run_macro_agent("AUD/USD")
    print("Result:", json.dumps(result, indent=2))
