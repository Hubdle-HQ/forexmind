"""
Tests for CoachAgent — 3-condition gate, schema, error handling.
Gate logic is pure; no LLM needed for gate failures.
"""
from unittest.mock import patch, MagicMock

import pytest

from agents.coach_agent import run_coach_agent


class TestCoachAgentGate:
    """3-condition gate: macro confidence > 0.5, technical quality > 0.6, no error."""

    def test_gate_fail_macro_confidence(self) -> None:
        result = run_coach_agent(
            macro_sentiment={"sentiment": "dovish", "confidence": 0.3},
            technical_setup={"setup": "trend", "direction": "BUY", "quality": 0.8},
            user_patterns={"mode": "market_patterns", "win_rate": 0.6, "pattern_notes": "OK", "trade_count": 50},
            pair="AUD/USD",
        )
        assert result["should_trade"] is False
        assert "0.3" in result["coaching_note"] or "0.30" in result["coaching_note"]

    def test_gate_fail_technical_quality(self) -> None:
        result = run_coach_agent(
            macro_sentiment={"sentiment": "dovish", "confidence": 0.85},
            technical_setup={"setup": "trend", "direction": "BUY", "quality": 0.5},
            user_patterns={"mode": "market_patterns", "win_rate": 0.6, "pattern_notes": "OK", "trade_count": 50},
            pair="AUD/USD",
        )
        assert result["should_trade"] is False
        assert "0.6" in result["coaching_note"] or "quality" in result["coaching_note"].lower()

    def test_gate_fail_state_error(self) -> None:
        result = run_coach_agent(
            macro_sentiment={"sentiment": "dovish", "confidence": 0.85},
            technical_setup={"setup": "trend", "direction": "BUY", "quality": 0.8},
            user_patterns={"mode": "market_patterns", "win_rate": 0.6, "pattern_notes": "OK", "trade_count": 50},
            pair="AUD/USD",
            state_error="RAG failed",
        )
        assert result["should_trade"] is False
        assert "error" in result["coaching_note"].lower() or "RAG" in result["coaching_note"]

    def test_gate_fail_technical_error(self) -> None:
        result = run_coach_agent(
            macro_sentiment={"sentiment": "dovish", "confidence": 0.85},
            technical_setup={"setup": "trend", "direction": "BUY", "quality": 0.8, "error": "OANDA timeout"},
            user_patterns={"mode": "market_patterns", "win_rate": 0.6, "pattern_notes": "OK", "trade_count": 50},
            pair="AUD/USD",
        )
        assert result["should_trade"] is False

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("agents.coach_agent.Anthropic")
    def test_gate_pass_calls_claude(
        self,
        mock_anthropic: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text='{"coaching_note": "Strong confluence. TRADE.", "should_trade": true}')]
        )
        mock_anthropic.return_value = mock_client

        result = run_coach_agent(
            macro_sentiment={"sentiment": "dovish", "confidence": 0.85},
            technical_setup={"setup": "trend continuation", "direction": "BUY", "quality": 0.8},
            user_patterns={"mode": "personal_edge", "win_rate": 0.6, "pattern_notes": "50 trades", "trade_count": 50},
            pair="AUD/USD",
        )
        assert result["should_trade"] is True
        assert "coaching_note" in result
