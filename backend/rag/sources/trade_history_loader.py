"""
Trade history loader: read CSV (MT4/MT5 or custom format), parse trades,
embed each as text description into forex_documents with source=user_trade.
"""
import csv
import logging
import re
import sys
from pathlib import Path

# Add backend to path for db imports
_backend = Path(__file__).resolve().parent.parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend.parent / ".env")

from rag.ingest import ingest_document

logger = logging.getLogger(__name__)

TRADE_SOURCE = "user_trade"

# Sample CSV with 20 fake trades for testing (pair, direction, setup_type, outcome, pips, session)
SAMPLE_CSV_HEADER = "pair,direction,entry_price,exit_price,pips_result,outcome,session,setup_type,traded_at,notes"
SAMPLE_TRADES: list[dict] = [
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6520, "exit_price": 0.6545, "pips_result": 25, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "SELL", "entry_price": 0.6560, "exit_price": 0.6530, "pips_result": 30, "outcome": "win", "session": "New York", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6510, "exit_price": 0.6495, "pips_result": -15, "outcome": "loss", "session": "London", "setup_type": "range_breakout", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6480, "exit_price": 0.6505, "pips_result": 25, "outcome": "win", "session": "Sydney", "setup_type": "london_breakout", "notes": ""},
    {"pair": "AUD/USD", "direction": "SELL", "entry_price": 0.6550, "exit_price": 0.6575, "pips_result": -25, "outcome": "loss", "session": "London", "setup_type": "mean_reversion", "notes": ""},
    {"pair": "EUR/USD", "direction": "BUY", "entry_price": 1.0850, "exit_price": 1.0875, "pips_result": 25, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "EUR/USD", "direction": "SELL", "entry_price": 1.0900, "exit_price": 1.0870, "pips_result": 30, "outcome": "win", "session": "New York", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "EUR/USD", "direction": "BUY", "entry_price": 1.0820, "exit_price": 1.0800, "pips_result": -20, "outcome": "loss", "session": "London", "setup_type": "range_breakout", "notes": ""},
    {"pair": "GBP/USD", "direction": "BUY", "entry_price": 1.2650, "exit_price": 1.2680, "pips_result": 30, "outcome": "win", "session": "London", "setup_type": "london_breakout", "notes": ""},
    {"pair": "GBP/USD", "direction": "SELL", "entry_price": 1.2700, "exit_price": 1.2670, "pips_result": 30, "outcome": "win", "session": "New York", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6500, "exit_price": 0.6520, "pips_result": 20, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "SELL", "entry_price": 0.6540, "exit_price": 0.6510, "pips_result": 30, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6490, "exit_price": 0.6470, "pips_result": -20, "outcome": "loss", "session": "Sydney", "setup_type": "mean_reversion", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6480, "exit_price": 0.6505, "pips_result": 25, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "SELL", "entry_price": 0.6530, "exit_price": 0.6555, "pips_result": -25, "outcome": "loss", "session": "New York", "setup_type": "range_breakout", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6470, "exit_price": 0.6495, "pips_result": 25, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6460, "exit_price": 0.6440, "pips_result": -20, "outcome": "loss", "session": "London", "setup_type": "london_breakout", "notes": ""},
    {"pair": "AUD/USD", "direction": "SELL", "entry_price": 0.6520, "exit_price": 0.6495, "pips_result": 25, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6510, "exit_price": 0.6535, "pips_result": 25, "outcome": "win", "session": "New York", "setup_type": "trend_continuation", "notes": ""},
    {"pair": "AUD/USD", "direction": "BUY", "entry_price": 0.6500, "exit_price": 0.6525, "pips_result": 25, "outcome": "win", "session": "London", "setup_type": "trend_continuation", "notes": ""},
]

# Extended sample: 35 AUD/USD trend_continuation trades (20 wins, 15 losses = 57% -> personal_edge)
SAMPLE_TRADES_EXTENDED: list[dict] = list(SAMPLE_TRADES)
for i in range(15):
    SAMPLE_TRADES_EXTENDED.append({
        "pair": "AUD/USD", "direction": "BUY", "entry_price": 0.65 + i * 0.001, "exit_price": 0.652 + i * 0.001,
        "pips_result": -20 if i % 3 == 0 else 25, "outcome": "loss" if i % 3 == 0 else "win",
        "session": "London", "setup_type": "trend_continuation", "notes": "",
    })
# 20 wins, 15 losses in extended = 57% win rate
for i in range(15):
    SAMPLE_TRADES_EXTENDED.append({
        "pair": "AUD/USD", "direction": "SELL", "entry_price": 0.655 - i * 0.001, "exit_price": 0.653 - i * 0.001,
        "pips_result": 25 if i % 2 == 0 else -20, "outcome": "win" if i % 2 == 0 else "loss",
        "session": "New York", "setup_type": "trend_continuation", "notes": "",
    })
# Underperforming: 35 trades with 15 wins = 43%
SAMPLE_TRADES_UNDERPERFORMING: list[dict] = []
for i in range(35):
    SAMPLE_TRADES_UNDERPERFORMING.append({
        "pair": "EUR/USD", "direction": "BUY", "entry_price": 1.08 + i * 0.0001, "exit_price": 1.082 + i * 0.0001,
        "pips_result": -15 if i < 20 else 20, "outcome": "loss" if i < 20 else "win",
        "session": "London", "setup_type": "range_breakout", "notes": "",
    })
# 15 wins, 20 losses = 43%


def _trade_to_text(trade: dict, user_id: str = "default") -> str:
    """Format trade as text for embedding. Includes pair, setup_type, outcome for RAG retrieval."""
    pair = trade.get("pair", "").replace("/", " ")
    direction = trade.get("direction", "")
    setup_type = trade.get("setup_type", "unknown")
    outcome = trade.get("outcome", "unknown")
    pips = trade.get("pips_result", 0)
    session = trade.get("session", "")
    entry = trade.get("entry_price", "")
    exit_p = trade.get("exit_price", "")
    return (
        f"User trade | user_id: {user_id} | pair: {pair} | direction: {direction} | "
        f"setup_type: {setup_type} | outcome: {outcome} | pips: {pips} | "
        f"session: {session} | entry: {entry} | exit: {exit_p}"
    )


def _parse_custom_row(row: dict) -> dict | None:
    """Parse row from custom format (pair, direction, setup_type, outcome, etc.)."""
    pair = (row.get("pair") or row.get("symbol") or "").strip()
    if not pair:
        return None
    direction = (row.get("direction") or row.get("type") or "BUY").strip().upper()
    if direction not in ("BUY", "SELL"):
        direction = "BUY" if "buy" in direction.lower() else "SELL"
    profit = row.get("pips_result") or row.get("profit") or row.get("Profit") or 0
    try:
        profit_val = float(profit)
    except (TypeError, ValueError):
        profit_val = 0
    outcome = (row.get("outcome") or "").strip().lower()
    if not outcome and profit_val != 0:
        outcome = "win" if profit_val > 0 else "loss"
    if outcome not in ("win", "loss"):
        outcome = "win" if profit_val > 0 else "loss"
    return {
        "pair": pair.replace("_", "/") if "_" in pair and "/" not in pair else pair,
        "direction": direction,
        "entry_price": _safe_float(row.get("entry_price") or row.get("Entry") or 0),
        "exit_price": _safe_float(row.get("exit_price") or row.get("Exit") or 0),
        "pips_result": int(profit_val) if profit_val == int(profit_val) else profit_val,
        "outcome": outcome,
        "session": (row.get("session") or row.get("Session") or "").strip(),
        "setup_type": (row.get("setup_type") or row.get("Setup") or "unknown").strip().lower().replace(" ", "_"),
        "traded_at": row.get("traded_at") or row.get("Time") or row.get("time") or "",
        "notes": (row.get("notes") or row.get("Comment") or "").strip(),
    }


def _parse_mt4_row(row: dict) -> dict | None:
    """Parse row from MT4-style export (Symbol, Type, Profit, etc.)."""
    symbol = (row.get("Symbol") or row.get("symbol") or row.get("Pair") or "").strip()
    if not symbol:
        return None
    trade_type = (row.get("Type") or row.get("type") or "buy").strip().lower()
    direction = "BUY" if trade_type in ("buy", "0", "buy limit", "buy stop") else "SELL"
    profit = row.get("Profit") or row.get("profit") or row.get("Profit/Loss") or 0
    try:
        profit_val = float(profit)
    except (TypeError, ValueError):
        profit_val = 0
    outcome = "win" if profit_val > 0 else "loss"
    pair = symbol.replace("_", "/") if "_" in symbol and "/" not in symbol else symbol
    return {
        "pair": pair,
        "direction": direction,
        "entry_price": _safe_float(row.get("Price") or row.get("Open") or 0),
        "exit_price": _safe_float(row.get("Close") or row.get("Exit") or 0),
        "pips_result": int(profit_val) if profit_val == int(profit_val) else profit_val,
        "outcome": outcome,
        "session": (row.get("Session") or "").strip(),
        "setup_type": (row.get("Comment") or row.get("setup_type") or "unknown").strip().lower().replace(" ", "_") or "unknown",
        "traded_at": row.get("Time") or row.get("time") or "",
        "notes": (row.get("Comment") or "").strip(),
    }


def _safe_float(val: str | float) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def parse_trade_csv(csv_path: str | Path) -> list[dict]:
    """
    Read CSV and parse each row into structured trade format.
    Supports custom format (pair, direction, setup_type, outcome) and MT4-style (Symbol, Type, Profit).
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    trades: list[dict] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            return trades

        first = rows[0]
        has_custom = "pair" in first or "setup_type" in first or "outcome" in first
        has_mt4 = "Symbol" in first or "symbol" in first or "Profit" in first

        for row in rows:
            row = {k.strip(): v for k, v in row.items() if k}
            if has_custom:
                t = _parse_custom_row(row)
            elif has_mt4:
                t = _parse_mt4_row(row)
            else:
                t = _parse_custom_row(row)
            if t:
                trades.append(t)
    return trades


def load_trades_from_csv(
    csv_path: str | Path,
    user_id: str = "default",
) -> int:
    """
    Read CSV, parse trades, embed each into forex_documents with source=user_trade.
    Returns number of trades embedded.
    """
    trades = parse_trade_csv(csv_path)
    count = 0
    for trade in trades:
        text = _trade_to_text(trade, user_id=user_id)
        try:
            ingest_document(text, source=TRADE_SOURCE)
            count += 1
        except Exception as e:
            logger.warning("Failed to embed trade: %s", e)
    logger.info("Embedded %d trades from %s (user_id=%s)", count, csv_path, user_id)
    return count


def create_sample_csv(
    path: str | Path | None = None,
    trades: list[dict] | None = None,
) -> Path:
    """Create sample CSV. Returns path to file. Use trades= for extended/underperforming tests."""
    p = Path(path) if path else Path(__file__).resolve().parent / "sample_trades.csv"
    trade_list = trades if trades is not None else SAMPLE_TRADES
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_CSV_HEADER.split(","))
        writer.writeheader()
        for t in trade_list:
            writer.writerow({**t, "traded_at": t.get("traded_at", "2025-02-01 08:00:00")})
    logger.info("Created sample CSV: %s (%d trades)", p, len(trade_list))
    return p


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", nargs="?", help="Path to trade CSV (or omit to create sample)")
    parser.add_argument("--user-id", default="default", help="User ID for embedding")
    parser.add_argument("--create-sample", action="store_true", help="Create sample_trades.csv only")
    parser.add_argument("--extended", action="store_true", help="Create extended sample (35 trades, 57%% win rate)")
    parser.add_argument("--underperforming", action="store_true", help="Create underperforming sample (35 trades, 43%% win rate)")
    args = parser.parse_args()

    trades_to_use = None
    if args.extended:
        trades_to_use = SAMPLE_TRADES_EXTENDED
    elif args.underperforming:
        trades_to_use = SAMPLE_TRADES_UNDERPERFORMING

    if args.create_sample or not args.csv:
        sample_path = create_sample_csv(trades=trades_to_use)
        if not args.csv:
            args.csv = str(sample_path)
    if args.csv:
        n = load_trades_from_csv(args.csv, user_id=args.user_id)
        logger.info("Loaded %d trades", n)
