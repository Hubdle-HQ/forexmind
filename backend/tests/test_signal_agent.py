"""
Tests for SignalAgent — market hours, JSON extraction, schema validation.
"""
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest

from agents.signal_agent import _extract_json, _is_market_open, run_signal_agent


class TestIsMarketOpen:
    """Forex: closed Fri 22:00 UTC through Sun 22:00 UTC."""

    @patch("agents.signal_agent.datetime")
    def test_monday_open(self, mock_dt: MagicMock) -> None:
        mock_dt.now.return_value = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)  # Monday 12:00 UTC
        assert _is_market_open() is True

    @patch("agents.signal_agent.datetime")
    def test_saturday_closed(self, mock_dt: MagicMock) -> None:
        mock_dt.now.return_value = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)  # Saturday
        assert _is_market_open() is False

    @patch("agents.signal_agent.datetime")
    def test_sunday_before_22_closed(self, mock_dt: MagicMock) -> None:
        mock_dt.now.return_value = datetime(2026, 2, 22, 10, 0, tzinfo=timezone.utc)  # Sunday 10:00 UTC
        assert _is_market_open() is False

    @patch("agents.signal_agent.datetime")
    def test_friday_22_utc_closed(self, mock_dt: MagicMock) -> None:
        mock_dt.now.return_value = datetime(2026, 2, 21, 22, 0, tzinfo=timezone.utc)  # Fri 22:00 UTC
        assert _is_market_open() is False


class TestExtractJson:
    """Extract JSON from model response."""

    def test_plain_json(self) -> None:
        text = '{"pair": "AUD/USD", "direction": "BUY"}'
        out = _extract_json(text)
        assert out is not None
        assert out["pair"] == "AUD/USD"
        assert out["direction"] == "BUY"

    def test_markdown_code_block(self) -> None:
        text = '```json\n{"pair": "AUD/USD", "direction": "SELL"}\n```'
        out = _extract_json(text)
        assert out is not None
        assert out["direction"] == "SELL"

    def test_invalid_returns_none(self) -> None:
        assert _extract_json("not json") is None


class TestSignalAgent:
    """Full agent with mocked OpenAI and OANDA."""

    @patch("agents.signal_agent._is_market_open", return_value=False)
    def test_market_closed_returns_no_signal(self, mock_open: MagicMock) -> None:
        result = run_signal_agent({"pair": "AUD/USD"})
        assert result.get("final_signal") is None
        assert "error" in result
        assert "Market closed" in str(result.get("error", ""))

    @patch("agents.signal_agent._is_market_open", return_value=True)
    @patch("agents.signal_agent.fetch_candles", return_value=[{"c": 0.65}])
    @patch("agents.signal_agent.OpenAI")
    def test_returns_structured_signal(
        self,
        mock_openai: MagicMock,
        mock_fetch: MagicMock,
        mock_open: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='''{"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.65, "take_profit": 0.66, "stop_loss": 0.64, "risk_reward_ratio": 2.0, "confidence_percentage": 75, "reasoning_summary": "Test", "mode": "market_patterns", "generated_at": "2026-02-25T12:00:00Z"}'''))]
        )
        mock_openai.return_value = mock_client

        with patch("agents.signal_agent.get_supabase"):
            result = run_signal_agent({
                "pair": "AUD/USD",
                "macro_sentiment": {"sentiment": "neutral", "confidence": 0.8},
                "technical_setup": {"setup": "trend", "direction": "BUY", "quality": 0.8},
                "user_patterns": {"mode": "market_patterns"},
                "coach_advice": "TRADE",
            })
        assert "final_signal" in result
        sig = result["final_signal"]
        assert sig["pair"] == "AUD/USD"
        assert sig["direction"] in ("BUY", "SELL")
        assert "entry_price" in sig
        assert "take_profit" in sig
        assert "stop_loss" in sig
