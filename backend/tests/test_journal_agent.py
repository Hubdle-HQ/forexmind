"""
Tests for JournalAgent — trade parsing, win-rate gate, mode logic.
"""
from unittest.mock import patch, MagicMock

import pytest

from agents.journal_agent import (
    _parse_trade_outcome,
    _parse_trade_user_id,
    _trades_match_pair_setup,
    run_journal_agent,
    MIN_TRADES_FOR_PERSONAL_EDGE,
    WIN_RATE_THRESHOLD,
)


class TestParseTradeOutcome:
    """Extract win/loss from trade content."""

    def test_win(self) -> None:
        assert _parse_trade_outcome("outcome: win") == "win"

    def test_loss(self) -> None:
        assert _parse_trade_outcome("outcome: loss") == "loss"

    def test_case_insensitive(self) -> None:
        assert _parse_trade_outcome("Outcome: WIN") == "win"

    def test_no_match(self) -> None:
        assert _parse_trade_outcome("no outcome here") is None


class TestParseTradeUserId:
    """Extract user_id from trade content."""

    def test_found(self) -> None:
        assert _parse_trade_user_id("user_id: abc123") == "abc123"

    def test_not_found(self) -> None:
        assert _parse_trade_user_id("no user") == ""


class TestTradesMatchPairSetup:
    """Match trade to pair, setup, user."""

    def test_matches(self) -> None:
        content = "AUD/USD trend_continuation user_id: default outcome: win"
        assert _trades_match_pair_setup(content, "AUD/USD", "trend_continuation", "default") is True

    def test_wrong_pair(self) -> None:
        content = "EUR/USD trend_continuation user_id: default outcome: win"
        assert _trades_match_pair_setup(content, "AUD/USD", "trend_continuation", "default") is False

    def test_empty_user_matches_any(self) -> None:
        content = "AUD/USD trend_continuation outcome: win"
        assert _trades_match_pair_setup(content, "AUD/USD", "trend_continuation", "") is True


class TestJournalAgent:
    """Full agent with mocked RAG."""

    @patch("agents.journal_agent.retrieve_documents", return_value=[])
    @patch("agents.journal_agent.get_supabase")
    def test_fewer_than_30_trades_uses_market_patterns(
        self,
        mock_supabase: MagicMock,
        mock_retrieve: MagicMock,
    ) -> None:
        result = run_journal_agent("AUD/USD", "trend_continuation")
        assert result["mode"] == "market_patterns"
        assert result["trade_count"] == 0
        assert "Fewer than" in result["pattern_notes"]

    @patch("agents.journal_agent.retrieve_documents")
    @patch("agents.journal_agent.get_supabase")
    def test_30_plus_trades_high_win_rate_personal_edge(
        self,
        mock_supabase: MagicMock,
        mock_retrieve: MagicMock,
    ) -> None:
        trades = [
            {"content": f"AUD/USD trend_continuation user_id: default outcome: win", "source": "user_trade"},
        ] * 20 + [
            {"content": f"AUD/USD trend_continuation user_id: default outcome: loss", "source": "user_trade"},
        ] * 15
        mock_retrieve.return_value = trades

        result = run_journal_agent("AUD/USD", "trend_continuation")
        assert result["mode"] == "personal_edge"
        assert result["trade_count"] == 35
        assert result["win_rate"] == pytest.approx(20 / 35, rel=0.01)
