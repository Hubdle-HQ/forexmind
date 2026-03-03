"""
Tests for signal_evaluator — outcome resolution, pip calculation, win rate.
Critical for monitoring signal quality and 55% win-rate target.
"""
from datetime import datetime, timezone

import pytest

# Import internal functions for unit testing
from evals.signal_evaluator import (
    _pip_size,
    _pips_result,
    _resolve_single,
)


class TestPipSize:
    """Pip size: JPY pairs 0.01, others 0.0001."""

    def test_aud_usd(self) -> None:
        assert _pip_size("AUD/USD") == 0.0001

    def test_gbp_jpy(self) -> None:
        assert _pip_size("GBP/JPY") == 0.01

    def test_usd_jpy(self) -> None:
        assert _pip_size("USD/JPY") == 0.01


class TestPipsResult:
    """Pips result: positive for win (TP hit), negative for loss (SL hit)."""

    def test_buy_tp_hit(self) -> None:
        # BUY: entry 0.65, TP 0.66, SL 0.64. TP hit = win
        pips = _pips_result("AUD/USD", "BUY", 0.65, hit_tp=True, tp=0.66, sl=0.64)
        assert pips > 0

    def test_buy_sl_hit(self) -> None:
        pips = _pips_result("AUD/USD", "BUY", 0.65, hit_tp=False, tp=0.66, sl=0.64)
        assert pips < 0

    def test_sell_tp_hit(self) -> None:
        # SELL: entry 0.66, TP 0.64, SL 0.68. TP hit = win
        pips = _pips_result("AUD/USD", "SELL", 0.66, hit_tp=True, tp=0.64, sl=0.68)
        assert pips > 0

    def test_sell_sl_hit(self) -> None:
        pips = _pips_result("AUD/USD", "SELL", 0.66, hit_tp=False, tp=0.64, sl=0.68)
        assert pips < 0


class TestResolveSingle:
    """TP/SL resolution from candle data."""

    def _candle(self, time_iso: str, o: float, h: float, l: float, c: float) -> dict:
        return {"time": time_iso, "o": o, "h": h, "l": l, "c": c}

    def test_buy_tp_hit_first(self) -> None:
        gen_at = datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc)
        row = {"pair": "AUD/USD", "direction": "BUY", "entry": 0.65, "tp": 0.66, "sl": 0.64}
        # Candle 1h after gen: high reaches TP
        candles = [
            self._candle("2026-02-24T13:00:00+00:00", 0.65, 0.66, 0.649, 0.655),
        ]
        result = _resolve_single(row, candles, gen_at)
        assert result is not None
        hit_tp, hit_sl, pips = result
        assert hit_tp is True
        assert hit_sl is False
        assert pips > 0

    def test_buy_sl_hit_first(self) -> None:
        gen_at = datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc)
        row = {"pair": "AUD/USD", "direction": "BUY", "entry": 0.65, "tp": 0.66, "sl": 0.64}
        candles = [
            self._candle("2026-02-24T13:00:00+00:00", 0.65, 0.651, 0.639, 0.64),
        ]
        result = _resolve_single(row, candles, gen_at)
        assert result is not None
        hit_tp, hit_sl, pips = result
        assert hit_tp is False
        assert hit_sl is True
        assert pips < 0

    def test_no_tp_sl_hit_returns_none(self) -> None:
        gen_at = datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc)
        row = {"pair": "AUD/USD", "direction": "BUY", "entry": 0.65, "tp": 0.66, "sl": 0.64}
        # Candle stays in range
        candles = [
            self._candle("2026-02-24T13:00:00+00:00", 0.65, 0.655, 0.645, 0.652),
        ]
        result = _resolve_single(row, candles, gen_at)
        assert result is None
