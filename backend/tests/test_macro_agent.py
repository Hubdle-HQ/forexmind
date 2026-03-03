"""
Tests for MacroAgent — sentiment parsing, schema, error handling.
"""
import json
from unittest.mock import patch, MagicMock

import pytest

from agents.macro_agent import _parse_sentiment_response, run_macro_agent


class TestParseSentimentResponse:
    """Parse JSON from LLM response."""

    def test_valid_json(self) -> None:
        text = '{"sentiment": "dovish", "confidence": 0.85}'
        sent, conf = _parse_sentiment_response(text)
        assert sent == "dovish"
        assert conf == 0.85

    def test_markdown_code_block(self) -> None:
        text = '```json\n{"sentiment": "hawkish", "confidence": 0.7}\n```'
        sent, conf = _parse_sentiment_response(text)
        assert sent == "hawkish"
        assert conf == 0.7

    def test_invalid_sentiment_defaults_to_neutral(self) -> None:
        text = '{"sentiment": "invalid", "confidence": 0.5}'
        sent, _ = _parse_sentiment_response(text)
        assert sent == "neutral"

    def test_confidence_clamped(self) -> None:
        text = '{"sentiment": "neutral", "confidence": 1.5}'
        _, conf = _parse_sentiment_response(text)
        assert conf == 1.0
        text = '{"sentiment": "neutral", "confidence": -0.2}'
        _, conf = _parse_sentiment_response(text)
        assert conf == 0.0


class TestMacroAgent:
    """Full agent with mocked RAG and LLM."""

    @patch("agents.macro_agent.retrieve_documents")
    @patch("agents.macro_agent.get_supabase")
    @patch("agents.macro_agent.genai")
    def test_returns_schema_with_context(
        self,
        mock_genai: MagicMock,
        mock_supabase: MagicMock,
        mock_retrieve: MagicMock,
    ) -> None:
        mock_retrieve.return_value = [
            {"content": "RBA left rates unchanged. Inflation moderating.", "similarity": 0.8}
        ]
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(
            text='{"sentiment": "dovish", "confidence": 0.82}'
        )
        mock_genai.GenerativeModel.return_value = mock_model

        result = run_macro_agent("AUD/USD")

        assert "sentiment" in result
        assert "confidence" in result
        assert "source_docs" in result
        assert result["sentiment"] in ("hawkish", "dovish", "neutral")
        assert 0 <= result["confidence"] <= 1

    @patch("agents.macro_agent.retrieve_documents", return_value=[])
    @patch("agents.macro_agent.get_supabase")
    def test_no_context_returns_error(self, mock_supabase: MagicMock, mock_retrieve: MagicMock) -> None:
        result = run_macro_agent("AUD/USD")
        assert "error" in result
        assert result["sentiment"] == "neutral"
        assert result["confidence"] == 0.0
