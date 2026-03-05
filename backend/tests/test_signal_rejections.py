"""
Tests for signal_rejections logging — gate failure tracking.
"""
from unittest.mock import patch, MagicMock

import pytest

from agents.graph import _route_after_coach
from db.signal_rejections import log_signal_rejection


class TestLogSignalRejection:
    """Log gate failures to signal_rejections table."""

    @patch("db.signal_rejections.get_supabase")
    def test_logs_with_all_fields(self, mock_get_supabase: MagicMock) -> None:
        mock_table = MagicMock()
        mock_get_supabase.return_value.table.return_value = mock_table

        log_signal_rejection(
            pair="AUD/USD",
            rejection_reason="technical_quality_gate",
            rejection_details="Gate failed: technical quality 0.52 is not above 0.55.",
            macro_sentiment={"sentiment": "dovish", "confidence": 0.85},
            technical_setup={"setup": "trend continuation", "direction": "BUY", "quality": 0.52},
            technical_context={"indicators": {"rsi_14": 45}, "pattern_name": "trend_continuation_ema_pullback"},
        )

        mock_table.insert.assert_called_once()
        call_args = mock_table.insert.call_args[0][0]
        assert call_args["pair"] == "AUD/USD"
        assert call_args["rejection_reason"] == "technical_quality_gate"
        assert "0.52" in str(call_args["rejection_details"])
        assert call_args["macro_sentiment"] == "dovish"
        assert call_args["macro_confidence"] == 0.85
        assert call_args["technical_quality"] == 0.52
        assert call_args["technical_setup"] == "trend continuation"
        assert call_args["technical_direction"] == "BUY"
        assert call_args["technical_context"]["pattern_name"] == "trend_continuation_ema_pullback"

    @patch("db.signal_rejections.get_supabase")
    def test_logs_claude_no_trade_with_reasoning(self, mock_get_supabase: MagicMock) -> None:
        """claude_no_trade stores full coaching note (LLM reasoning) in rejection_details."""
        mock_table = MagicMock()
        mock_get_supabase.return_value.table.return_value = mock_table

        note = "Neutral macro, no clear setup. NO TRADE. Wait for confluence."
        log_signal_rejection(
            pair="AUD/USD",
            rejection_reason="claude_no_trade",
            rejection_details=note,
            macro_sentiment={"sentiment": "neutral", "confidence": 0.85},
            technical_setup={"setup": "unknown", "direction": "NEUTRAL", "quality": 0.60},
        )

        call_args = mock_table.insert.call_args[0][0]
        assert call_args["rejection_reason"] == "claude_no_trade"
        assert call_args["rejection_details"] == note
        assert call_args["macro_sentiment"] == "neutral"
        assert call_args["technical_quality"] == 0.60

    @patch("db.signal_rejections.get_supabase")
    def test_logs_error_gate(self, mock_get_supabase: MagicMock) -> None:
        mock_table = MagicMock()
        mock_get_supabase.return_value.table.return_value = mock_table

        log_signal_rejection(
            pair="GBP/JPY",
            rejection_reason="error_gate",
            rejection_details="Gate failed: error in pipeline (OANDA timeout).",
            error_message="OANDA timeout",
        )

        call_args = mock_table.insert.call_args[0][0]
        assert call_args["rejection_reason"] == "error_gate"
        assert call_args["error_message"] == "OANDA timeout"

    @patch("db.signal_rejections.get_supabase")
    def test_fails_gracefully_on_supabase_error(self, mock_get_supabase: MagicMock) -> None:
        mock_insert = MagicMock()
        mock_insert.execute.side_effect = Exception("Connection refused")
        mock_get_supabase.return_value.table.return_value.insert.return_value = mock_insert

        # Should not raise — logs warning and continues
        log_signal_rejection(
            pair="AUD/USD",
            rejection_reason="macro_gate",
            rejection_details="Gate failed.",
        )


class TestGraphRejectionRouting:
    """Graph routes to log_rejection when should_trade=False."""

    def test_routes_to_log_rejection_when_should_trade_false(self) -> None:
        state = {"should_trade": False, "rejection_reason": "technical_quality_gate"}
        assert _route_after_coach(state) == "log_rejection"

    def test_routes_to_signal_when_should_trade_true(self) -> None:
        state = {"should_trade": True}
        assert _route_after_coach(state) == "signal"
