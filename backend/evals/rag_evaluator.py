"""
RAGAS Evaluation — Fetch agent observations from Langfuse, run RAGAS, store in eval_results.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

OBSERVATION_LIMIT = 20
MAX_RAGAS_SAMPLES = 5  # Cap samples for evaluation speed (increase for production)
RAG_AGENT_NAMES = ("macro_agent",)  # macro_agent has source_docs; technical_agent does not


def _fetch_observations_from_langfuse(limit: int = OBSERVATION_LIMIT) -> list[dict[str, Any]]:
    """
    Fetch the last N agent observations from Langfuse.
    Returns list of dicts with keys: query, response, contexts, observation_id, trace_id.
    """
    try:
        from langfuse import get_client

        langfuse = get_client()
    except Exception as e:
        logger.exception("Langfuse client failed: %s", e)
        return []

    observations: list[dict[str, Any]] = []

    try:
        for agent_name in RAG_AGENT_NAMES:
            if len(observations) >= limit:
                break
            obs_resp = langfuse.api.observations.get_many(name=agent_name, limit=limit)
            obs_data = getattr(obs_resp, "data", None) or []
            if not obs_data and hasattr(obs_resp, "data"):
                obs_data = list(obs_resp.data) if obs_resp.data else []
            else:
                obs_data = list(obs_data) if obs_data else []

            for obs in obs_data:
                if len(observations) >= limit:
                    break
                inp = getattr(obs, "input", None) or (obs.get("input") if isinstance(obs, dict) else None)
                out = getattr(obs, "output", None) or (obs.get("output") if isinstance(obs, dict) else None)
                if not out or not isinstance(out, dict):
                    continue
                source_docs = out.get("source_docs") or []
                contexts = [d.get("content", "") for d in source_docs if isinstance(d, dict) and d.get("content")]
                if not contexts:
                    continue
                pair = (inp.get("pair") if isinstance(inp, dict) else None) or "AUD/USD"
                query = "RBA Australia monetary policy cash rate statement" if "AUD" in str(pair).upper() or "USD" in str(pair).upper() else "RBA Reserve Bank Australia monetary policy interest rate inflation"
                response = f"Sentiment: {out.get('sentiment', 'neutral')}, confidence: {out.get('confidence', 0)}"
                obs_id = getattr(obs, "id", None) or (obs.get("id") if isinstance(obs, dict) else None)
                trace_id = getattr(obs, "trace_id", None) or (obs.get("trace_id") or obs.get("traceId") if isinstance(obs, dict) else None)
                observations.append({
                    "query": query,
                    "response": response,
                    "contexts": contexts,
                    "observation_id": obs_id,
                    "trace_id": trace_id,
                })

    except Exception as e:
        logger.exception("Langfuse fetch failed: %s", e)

    return observations[:limit]


def _build_ragas_dataset(observations: list[dict[str, Any]], max_samples: int = MAX_RAGAS_SAMPLES):
    """Build RAGAS EvaluationDataset from observations."""
    from ragas.dataset_schema import SingleTurnSample, EvaluationDataset

    samples = []
    for obs in observations[:max_samples]:
        samples.append(
            SingleTurnSample(
                user_input=obs["query"],
                retrieved_contexts=obs["contexts"],
                response=obs["response"],
            )
        )
    return EvaluationDataset(samples=samples)


def _send_ragas_scores_to_langfuse(
    scores: dict[str, float],
    result: Any,
    observations: list[dict[str, Any]],
) -> None:
    """Create a RAGAS evaluation trace in Langfuse with aggregated scores, and attach per-sample scores to source observations."""
    try:
        from langfuse import get_client

        langfuse = get_client()
    except Exception as e:
        logger.exception("Langfuse client failed for score ingestion: %s", e)
        return

    # Create a RAGAS evaluation trace with aggregated scores
    with langfuse.start_as_current_span(name="ragas-evaluation") as span:
        langfuse.score_current_trace(
            name="context_relevancy",
            value=float(scores.get("context_relevancy", 0)),
            data_type="NUMERIC",
            comment="RAGAS context relevancy (aggregated)",
        )
        langfuse.score_current_trace(
            name="faithfulness",
            value=float(scores.get("faithfulness", 0)),
            data_type="NUMERIC",
            comment="RAGAS faithfulness (aggregated)",
        )
        langfuse.score_current_trace(
            name="answer_relevancy",
            value=float(scores.get("answer_relevancy", 0)),
            data_type="NUMERIC",
            comment="RAGAS answer relevancy (aggregated)",
        )

    # Attach per-sample scores to each source observation
    per_sample_scores = getattr(result, "scores", None) or []
    metric_map = {
        "llm_context_precision_without_reference": "context_relevancy",
        "faithfulness": "faithfulness",
        "answer_relevancy": "answer_relevancy",
    }
    for i, obs in enumerate(observations):
        if i >= len(per_sample_scores):
            break
        obs_id = obs.get("observation_id")
        trace_id = obs.get("trace_id")
        if not obs_id or not trace_id:
            continue
        sample = per_sample_scores[i]
        if not isinstance(sample, dict):
            continue
        for metric_key, out_name in metric_map.items():
            val = sample.get(metric_key)
            if val is not None and isinstance(val, (int, float)):
                try:
                    langfuse.create_score(
                        name=f"ragas_{out_name}",
                        value=float(val),
                        trace_id=trace_id,
                        observation_id=obs_id,
                        data_type="NUMERIC",
                        comment=f"RAGAS {out_name} (per-sample)",
                    )
                except Exception as e:
                    logger.debug("Failed to score observation %s: %s", obs_id, e)
    langfuse.flush()


def run_ragas_evaluation() -> dict[str, float]:
    """
    Fetch observations from Langfuse, run RAGAS evaluation, store in eval_results.
    Returns dict with context_relevancy, faithfulness, answer_relevancy.
    """
    observations = _fetch_observations_from_langfuse()
    if len(observations) < 1:
        logger.warning("No RAG observations found in Langfuse — skipping RAGAS")
        return {}

    n = min(len(observations), MAX_RAGAS_SAMPLES)
    logger.info("Running RAGAS on %d observations", n)

    try:
        from langchain_openai import OpenAIEmbeddings
        from openai import OpenAI
        from ragas import evaluate
        from ragas.llms import llm_factory
        from ragas.metrics._context_precision import LLMContextPrecisionWithoutReference
        from ragas.metrics._faithfulness import Faithfulness
        from ragas.metrics._answer_relevance import AnswerRelevancy

        client = OpenAI()
        llm = llm_factory("gpt-4o-mini", client=client)
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        metrics = [
            LLMContextPrecisionWithoutReference(llm=llm),
            Faithfulness(llm=llm),
            AnswerRelevancy(llm=llm, embeddings=embeddings),
        ]
        dataset = _build_ragas_dataset(observations)
        result = evaluate(dataset, metrics=metrics)
    except Exception as e:
        logger.exception("RAGAS evaluation failed: %s", e)
        return {}

    scores: dict[str, float] = {}
    # RAGAS returns EvaluationResult with _repr_dict holding aggregated scores
    key_map = {
        "llm_context_precision_without_reference": "context_relevancy",
        "context_precision": "context_relevancy",
        "context_relevance": "context_relevancy",
        "context_relevancy": "context_relevancy",
        "faithfulness": "faithfulness",
        "answer_relevancy": "answer_relevancy",
    }
    result_dict = getattr(result, "_repr_dict", None) or (result if isinstance(result, dict) else {})
    for metric_key, out_key in key_map.items():
        try:
            val = result_dict.get(metric_key)
            if val is not None and not (isinstance(val, float) and (val != val)):
                scores[out_key] = float(val)
        except (KeyError, TypeError):
            pass

    if not scores:
        logger.warning("No scores extracted from RAGAS result: %s", result)
        return {}

    # Send RAGAS scores to Langfuse for dashboard visibility
    _send_ragas_scores_to_langfuse(
        scores=scores,
        result=result,
        observations=observations[:n],
    )

    now = datetime.now(timezone.utc)
    week_str = now.strftime("%Y-W%W")

    try:
        get_supabase().table("eval_results").insert(
            {
                "week": week_str,
                "context_relevancy": scores.get("context_relevancy"),
                "faithfulness": scores.get("faithfulness"),
                "answer_relevancy": scores.get("answer_relevancy"),
            }
        ).execute()
        logger.info("Stored RAGAS scores: %s", scores)
    except Exception as e:
        logger.exception("Failed to store eval_results: %s", e)

    return scores


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    scores = run_ragas_evaluation()
    if scores:
        logger.info("RAGAS scores: context_relevancy=%.4f faithfulness=%.4f answer_relevancy=%.4f",
                    scores.get("context_relevancy", 0), scores.get("faithfulness", 0), scores.get("answer_relevancy", 0))
        if scores.get("faithfulness", 1) < 0.70:
            logger.warning("Faithfulness below 0.70 — requires prompt improvement in Week 5")
    else:
        logger.warning("No RAGAS scores (no observations or evaluation failed)")
