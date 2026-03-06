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

    @patch("agents.technical_agent.detect_patterns", return_value={"pattern_detected": False})
    @patch("agents.technical_agent.fetch_h4_candles", return_value=[])
    @patch("agents.technical_agent.fetch_d1_candles", return_value=[])
    @patch("agents.technical_agent.fetch_candles", return_value=_mock_candles())
    @patch("agents.technical_agent.get_supabase")
    def test_structure_follow_fallback_when_no_pattern_and_bullish_structure(
        self,
        mock_supabase: MagicMock,
        mock_fetch: MagicMock,
        mock_h4: MagicMock,
        mock_d1: MagicMock,
        mock_detect: MagicMock,
    ) -> None:
        """structure_follow fallback when no coded pattern but structure_bias is bullish."""
        with patch("agents.technical_agent.calculate_indicators") as mock_ind:
            mock_ind.return_value = {
                "rsi_14": 50,
                "ema_20": 0.65,
                "ema_50": 0.64,
                "atr_14": 0.001,
                "current_price": 0.65,
                "ema_trend": "bullish",
                "rsi_zone": "neutral",
                "candle_count": 100,
            }
            with patch("agents.technical_agent.detect_structure") as mock_struct:
                mock_struct.return_value = {
                    "hh_hl": True,
                    "ll_lh": False,
                    "ema_cross": "none",
                    "broke_asian_range": "none",
                    "at_ema_20": False,
                    "structure_bias": "bullish",
                }
                with patch("agents.technical_agent.analyse_timeframes") as mock_mtf:
                    mock_mtf.return_value = {
                        "d1_bias": "bullish",
                        "h4_structure": "bullish",
                        "h1_direction": "bullish",
                        "conflict_detected": False,
                        "timeframe_alignment": "partial",
                    }
                    with patch("agents.technical_agent.retrieve_documents", return_value=[]):
                        result = run_technical_agent("AUD/USD")
        assert result["setup"] == "structure_follow"
        assert result["direction"] == "BUY"
        assert 0.60 <= result["quality"] <= 0.75

    @patch("agents.technical_agent.detect_patterns", return_value={"pattern_detected": False})
    @patch("agents.technical_agent.fetch_h4_candles", return_value=[])
    @patch("agents.technical_agent.fetch_d1_candles", return_value=[])
    @patch("agents.technical_agent.fetch_candles", return_value=_mock_candles())
    @patch("agents.technical_agent.get_supabase")
    def test_no_structure_follow_when_structure_bias_neutral(
        self,
        mock_supabase: MagicMock,
        mock_fetch: MagicMock,
        mock_h4: MagicMock,
        mock_d1: MagicMock,
        mock_detect: MagicMock,
    ) -> None:
        """Safeguard: structure_follow NOT applied when structure_bias = neutral."""
        with patch("agents.technical_agent.calculate_indicators") as mock_ind:
            mock_ind.return_value = {
                "rsi_14": 50,
                "ema_20": 0.65,
                "ema_50": 0.65,
                "atr_14": 0.001,
                "current_price": 0.65,
                "ema_trend": "neutral",
                "rsi_zone": "neutral",
                "candle_count": 100,
            }
            with patch("agents.technical_agent.detect_structure") as mock_struct:
                mock_struct.return_value = {
                    "hh_hl": False,
                    "ll_lh": False,
                    "ema_cross": "none",
                    "broke_asian_range": "none",
                    "at_ema_20": False,
                    "structure_bias": "neutral",
                }
                with patch("agents.technical_agent.analyse_timeframes") as mock_mtf:
                    mock_mtf.return_value = {
                        "d1_bias": "neutral",
                        "h4_structure": "neutral",
                        "h1_direction": "neutral",
                        "conflict_detected": False,
                        "timeframe_alignment": "partial",
                    }
                    with patch("agents.technical_agent.retrieve_documents", return_value=[{"content": "x"}]):
                        with patch("agents.technical_agent.OpenAI") as mock_openai:
                            mock_client = MagicMock()
                            mock_client.chat.completions.create.return_value = MagicMock(
                                choices=[MagicMock(message=MagicMock(content='{"setup": "none/unknown", "direction": "NEUTRAL", "quality": 0.5}'))]
                            )
                            mock_openai.return_value = mock_client
                            result = run_technical_agent("AUD/USD")
        assert result["setup"] != "structure_follow"
