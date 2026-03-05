"""
LangGraph StateGraph: ForexMind pipeline orchestrator.

Flow: macro → technical → journal → coach → [gate] → signal → END
                                            ↘ log_rejection → END (if should_trade = False)
"""
import logging
import sys
from pathlib import Path
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

# Add backend to path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from agents.coach_agent import run_coach_agent
from agents.macro_agent import run_macro_agent
from agents.signal_agent import run_signal_agent
from agents.technical_agent import run_technical_agent, _technical_context_cache
from agents.journal_agent import run_journal_agent
from db.signal_rejections import log_signal_rejection

logger = logging.getLogger(__name__)

# Set to True to print state after each node (for verification)
PRINT_STATE_AFTER_NODE = True


class ForexState(TypedDict, total=False):
    pair: str
    macro_sentiment: Optional[dict]
    technical_setup: Optional[dict]
    technical_context: Optional[dict]
    user_patterns: Optional[dict]
    coach_advice: Optional[str]
    rejection_reason: Optional[str]
    final_signal: Optional[dict]
    should_trade: bool
    error: Optional[str]


def _log_state(node_name: str, state: ForexState) -> None:
    """Print state after each node for verification."""
    if PRINT_STATE_AFTER_NODE:
        logger.info("--- State after %s ---", node_name)
        for k, v in state.items():
            if v is not None:
                logger.info("  %s: %s", k, v)


def macro_node(state: ForexState) -> ForexState:
    """Run MacroAgent, update macro_sentiment."""
    pair = state.get("pair", "AUD/USD")
    result = run_macro_agent(pair)
    _log_state("macro", {**state, "macro_sentiment": result})
    return {"macro_sentiment": result}


def technical_node(state: ForexState) -> ForexState:
    """Run TechnicalAgent, update technical_setup and technical_context."""
    pair = state.get("pair", "AUD/USD")
    macro_sentiment = state.get("macro_sentiment")
    result = run_technical_agent(pair, macro_sentiment=macro_sentiment)
    ctx = _technical_context_cache.get(pair) or {}
    ctx = {**ctx, "setup": result.get("setup", "unknown")}
    _log_state("technical", {**state, "technical_setup": result, "technical_context": ctx})
    return {"technical_setup": result, "technical_context": ctx}


def journal_node(state: ForexState) -> ForexState:
    """Run JournalAgent, update user_patterns."""
    pair = state.get("pair", "AUD/USD")
    technical_setup = state.get("technical_setup") or {}
    setup_type = technical_setup.get("setup", "unknown")
    result = run_journal_agent(pair, setup_type=setup_type)
    _log_state("journal", {**state, "user_patterns": result})
    return {"user_patterns": result}


def coach_agent_node(state: ForexState) -> ForexState:
    """Run CoachAgent: 3-condition gate + Claude synthesis."""
    pair = state.get("pair", "AUD/USD")
    macro_sentiment = state.get("macro_sentiment")
    technical_setup = state.get("technical_setup")
    user_patterns = state.get("user_patterns")
    state_error = state.get("error")

    result = run_coach_agent(
        macro_sentiment=macro_sentiment,
        technical_setup=technical_setup,
        user_patterns=user_patterns,
        pair=pair,
        state_error=state_error,
    )
    coach_advice = result.get("coaching_note", "")
    should_trade = result.get("should_trade", False)
    rejection_reason = result.get("rejection_reason")
    _log_state("coach", {**state, "coach_advice": coach_advice, "should_trade": should_trade})
    return {
        "coach_advice": coach_advice,
        "should_trade": should_trade,
        "rejection_reason": rejection_reason,
    }


def signal_agent_node(state: ForexState) -> ForexState:
    """Run SignalAgent: generate structured signal, save to signal_outcomes."""
    result = run_signal_agent(dict(state))
    final_signal = result.get("final_signal")
    error = result.get("error")
    _log_state("signal", {**state, "final_signal": final_signal})
    return {"final_signal": final_signal, "error": error}


def log_rejection_node(state: ForexState) -> ForexState:
    """Log gate failure or Claude NO TRADE to signal_rejections for evaluation. No state change."""
    pair = state.get("pair", "AUD/USD")
    rejection_reason = state.get("rejection_reason")
    coach_advice = state.get("coach_advice")
    macro_sentiment = state.get("macro_sentiment") or {}
    technical_setup = state.get("technical_setup") or {}
    user_patterns = state.get("user_patterns") or {}
    technical_context = state.get("technical_context")

    # Fallback: gate passed but Claude said no → claude_no_trade (handles older deployments)
    if not rejection_reason:
        rejection_reason = "claude_no_trade"

    logger.info("log_rejection: pair=%s reason=%s", pair, rejection_reason)
    if rejection_reason:
        err_msg = (
            state.get("error")
            or macro_sentiment.get("error")
            or technical_setup.get("error")
            or user_patterns.get("error")
        )
        if err_msg is not None:
            err_msg = str(err_msg)
        log_signal_rejection(
            pair=pair,
            rejection_reason=rejection_reason,
            rejection_details=coach_advice,
            macro_sentiment=macro_sentiment,
            technical_setup=technical_setup,
            technical_context=technical_context,
            error_message=err_msg,
        )
    return {}


def _route_after_coach(state: ForexState) -> Literal["signal", "log_rejection"]:
    """Route to signal if should_trade, else log_rejection."""
    if state.get("should_trade"):
        return "signal"
    return "log_rejection"


def build_graph() -> CompiledStateGraph:
    """Build and compile the ForexMind pipeline graph."""
    graph = StateGraph(ForexState)

    graph.add_node("macro", macro_node)
    graph.add_node("technical", technical_node)
    graph.add_node("journal", journal_node)
    graph.add_node("coach", coach_agent_node)
    graph.add_node("signal", signal_agent_node)
    graph.add_node("log_rejection", log_rejection_node)

    graph.set_entry_point("macro")
    graph.add_edge("macro", "technical")
    graph.add_edge("technical", "journal")
    graph.add_edge("journal", "coach")
    graph.add_conditional_edges("coach", _route_after_coach, {"signal": "signal", "log_rejection": "log_rejection"})
    graph.add_edge("signal", END)
    graph.add_edge("log_rejection", END)

    return graph.compile()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    compiled = build_graph()
    initial: ForexState = {"pair": "AUD/USD"}
    result = compiled.invoke(initial)
    logger.info("=== Final state ===")
    for k, v in result.items():
        if v is not None:
            logger.info("  %s: %s", k, v)
