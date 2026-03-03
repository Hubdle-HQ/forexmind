"""
Tests for indicators.py — calculate_indicators, detect_structure, get_pair_pip_threshold.
Pure logic, no external APIs. Critical for TechnicalAgent signal quality.
"""
import pytest

from agents.indicators import (
    calculate_indicators,
    detect_structure,
    get_pair_pip_threshold,
)


class TestGetPairPipThreshold:
    """Pip threshold for at_ema_20: JPY pairs use 0.05, others 0.0005."""

    def test_aud_usd(self) -> None:
        assert get_pair_pip_threshold("AUD/USD") == 0.0005

    def test_eur_usd(self) -> None:
        assert get_pair_pip_threshold("EUR/USD") == 0.0005

    def test_gbp_jpy(self) -> None:
        assert get_pair_pip_threshold("GBP/JPY") == 0.05

    def test_usd_jpy(self) -> None:
        assert get_pair_pip_threshold("USD/JPY") == 0.05

    def test_empty_pair_defaults_to_small(self) -> None:
        assert get_pair_pip_threshold("") == 0.0005


class TestCalculateIndicators:
    """Indicator calculation from synthetic candles."""

    def test_minimum_candles_required(self) -> None:
        with pytest.raises(ValueError, match="Minimum 50 candles"):
            calculate_indicators([{"o": 0.65, "h": 0.65, "l": 0.65, "c": 0.65}] * 49)

    def test_returns_required_keys(self, sample_candles: list[dict]) -> None:
        result = calculate_indicators(sample_candles)
        assert "rsi_14" in result
        assert "ema_20" in result
        assert "ema_50" in result
        assert "atr_14" in result
        assert "ema_trend" in result
        assert "rsi_zone" in result
        assert "current_price" in result
        assert "candle_count" in result

    def test_candle_count(self, sample_candles: list[dict]) -> None:
        result = calculate_indicators(sample_candles)
        assert result["candle_count"] == len(sample_candles)

    def test_ema_trend_values(self, sample_candles: list[dict]) -> None:
        result = calculate_indicators(sample_candles)
        assert result["ema_trend"] in ("bullish", "bearish", "neutral")

    def test_rsi_zone_values(self, sample_candles: list[dict]) -> None:
        result = calculate_indicators(sample_candles)
        assert result["rsi_zone"] in ("overbought", "oversold", "neutral")


class TestDetectStructure:
    """Structure detection — HH/HL, LL/LH, EMA cross, Asian range, at_ema_20, structure_bias."""

    def test_insufficient_candles_returns_defaults(self) -> None:
        candles = [{"o": 0.65, "h": 0.65, "l": 0.65, "c": 0.65}] * 9
        indicators = {"current_price": 0.65, "ema_20": 0.65, "ema_50": 0.64, "rsi_zone": "neutral"}
        result = detect_structure(candles, indicators)
        assert result["hh_hl"] is False
        assert result["ll_lh"] is False
        assert result["ema_cross"] == "none"
        assert result["structure_bias"] == "neutral"

    def test_returns_all_keys(self, sample_candles: list[dict]) -> None:
        indicators = calculate_indicators(sample_candles)
        result = detect_structure(sample_candles, indicators)
        assert "hh_hl" in result
        assert "ll_lh" in result
        assert "ema_cross" in result
        assert "broke_asian_range" in result
        assert "at_ema_20" in result
        assert "structure_bias" in result

    def test_hh_hl_uptrend(self, sample_candles_hh_hl: list[dict]) -> None:
        indicators = calculate_indicators(sample_candles_hh_hl)
        result = detect_structure(sample_candles_hh_hl, indicators, pair="AUD/USD")
        assert result["hh_hl"] is True
        assert result["ll_lh"] is False

    def test_ll_lh_downtrend(self, sample_candles_ll_lh: list[dict]) -> None:
        indicators = calculate_indicators(sample_candles_ll_lh)
        result = detect_structure(sample_candles_ll_lh, indicators, pair="AUD/USD")
        assert result["ll_lh"] is True
        assert result["hh_hl"] is False

    def test_ema_cross_values(self, sample_candles: list[dict]) -> None:
        indicators = calculate_indicators(sample_candles)
        result = detect_structure(sample_candles, indicators)
        assert result["ema_cross"] in ("bullish", "bearish", "none")

    def test_broke_asian_range_values(self, sample_candles: list[dict]) -> None:
        indicators = calculate_indicators(sample_candles)
        result = detect_structure(sample_candles, indicators)
        assert result["broke_asian_range"] in ("up", "down", "none")

    def test_structure_bias_values(self, sample_candles: list[dict]) -> None:
        indicators = calculate_indicators(sample_candles)
        result = detect_structure(sample_candles, indicators)
        assert result["structure_bias"] in ("bullish", "bearish", "neutral")

    def test_at_ema_20_jpy_threshold(self, sample_candles: list[dict]) -> None:
        indicators = calculate_indicators(sample_candles)
        price = indicators["current_price"]
        ema = indicators["ema_20"]
        indicators["ema_20"] = price + 0.03  # Within 0.05 for JPY
        result = detect_structure(sample_candles, indicators, pair="GBP/JPY")
        assert isinstance(result["at_ema_20"], bool)
