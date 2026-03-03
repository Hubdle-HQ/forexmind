"""
Tests for TechnicalAgent — schema, error handling, structure integration.
Uses mocks for OANDA and OpenAI to avoid external calls.
"""
from unittest.mock import patch, MagicMock

import pytest

from agents.technical_agent import run_technical_agent


def _mock_candles() -> list[dict]:
    base = 0.6500
    return [
        {"time": f"2026-02-24T{i % 24:02d}:00:00.000000000Z", "o": base, "h": base + 0.001, "l": base - 0.001, "c": base}
        for i in range(100)
    ]


class TestTechnicalAgentSchema:
    """TechnicalAgent must return { setup, direction, quality }."""

    @patch("agents.technical_agent.fetch_candles", return_value=_mock_candles())
    @patch("agents.technical_agent.retrieve_documents", return_value=[{"content": "pattern", "similarity": 0.8}])
    @patch("agents.technical_agent.get_supabase")
    @patch("agents.technical_agent.OpenAI")
    def test_returns_required_schema(
        self,
        mock_openai: MagicMock,
        mock_supabase: MagicMock,
        mock_retrieve: MagicMock,
        mock_fetch: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"setup": "trend continuation", "direction": "BUY", "quality": 0.75}'))]
        )
        mock_openai.return_value = mock_client

        result = run_technical_agent("AUD/USD")

        assert "setup" in result
        assert "direction" in result
        assert "quality" in result
        assert result["direction"] in ("BUY", "SELL", "NEUTRAL")
        assert 0 <= result["quality"] <= 1

    @patch("agents.technical_agent.fetch_candles", return_value=[])
    @patch("agents.technical_agent.get_supabase")
    def test_no_candles_returns_error(self, mock_supabase: MagicMock, mock_fetch: MagicMock) -> None:
        result = run_technical_agent("AUD/USD")
        assert "error" in result
        assert result["direction"] == "NEUTRAL"
        assert result["quality"] == 0.0

    @patch("agents.technical_agent.fetch_candles", side_effect=Exception("OANDA error"))
    @patch("agents.technical_agent.get_supabase")
    def test_fetch_error_returns_error(self, mock_supabase: MagicMock, mock_fetch: MagicMock) -> None:
        result = run_technical_agent("AUD/USD")
        assert "error" in result
        assert result["direction"] == "NEUTRAL"
