"""
APEX Quant OS - Layer 6: Paper Execution Broker (24/7 Simulation Venue)
A persistent, disk-backed paper-trading venue so 24/7 automated operation can be
validated without risking capital. State is journaled to SQLite so restarts are
lossless. Real live execution plugs into the same open/close interface.
"""

import os
import sqlite3
from typing import List

from trade_management.mtf_trailing_engine import (
    ExitReason,
    ManagedTrade,
    TradeStatus,
)


class PaperBroker:

    def __init__(self, db_path: str = None, starting_balance: float = 1000.0):
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "live_journal.db",
            )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db(starting_balance)

    # ------------------------------------------------------------------
    def _init_db(self, starting_balance: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meta (
                       key TEXT PRIMARY KEY, value REAL)"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS trades (
                       trade_id TEXT PRIMARY KEY,
                       symbol TEXT, set_id TEXT, strategy TEXT, action TEXT,
                       entry_price REAL, stop_loss REAL, take_profit REAL,
                       position_size REAL, dollar_risk REAL, entry_timestamp INTEGER,
                       status TEXT, exit_price REAL, exit_reason TEXT,
                       exit_timestamp INTEGER, r_multiple REAL, pnl REAL)"""
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('balance', ?)",
                (starting_balance,),
            )

    # ------------------------------------------------------------------
    def balance(self) -> float:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='balance'").fetchone()
            return float(row[0]) if row else 0.0

    def _set_balance(self, value: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE meta SET value=? WHERE key='balance'", (value,))

    # ------------------------------------------------------------------
    def open_trade(self, candidate, symbol: str, set_id: str, timestamp: int) -> ManagedTrade:
        trade = ManagedTrade(
            trade_id=candidate.trade_id,
            symbol=symbol, set_id=set_id, strategy=candidate.strategy,
            action=candidate.action,
            entry_price=candidate.entry_price,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            position_size=candidate.position_size,
            dollar_risk=candidate.dollar_risk,
            entry_timestamp=timestamp,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO trades (trade_id, symbol, set_id, strategy, action,
                       entry_price, stop_loss, take_profit, position_size,
                       dollar_risk, entry_timestamp, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trade.trade_id, trade.symbol, trade.set_id, trade.strategy,
                 trade.action, trade.entry_price, trade.stop_loss, trade.take_profit,
                 trade.position_size, trade.dollar_risk, trade.entry_timestamp,
                 TradeStatus.OPEN.value),
            )
        return trade

    def close_trade(self, trade: ManagedTrade, exit_price: float,
                    reason: ExitReason, timestamp: int) -> None:
        trade.mark_closed(exit_price, reason, timestamp)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE trades SET status=?, exit_price=?, exit_reason=?,
                       exit_timestamp=?, r_multiple=?, pnl=? WHERE trade_id=?""",
                (TradeStatus.CLOSED.value, trade.exit_price,
                 trade.exit_reason.value if trade.exit_reason else None,
                 trade.exit_timestamp, trade.r_multiple, trade.pnl, trade.trade_id),
            )
            self._set_balance(self.balance() + trade.pnl)

    def open_positions(self) -> List[ManagedTrade]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT trade_id, symbol, set_id, strategy, action, entry_price, "
                "stop_loss, take_profit, position_size, dollar_risk, entry_timestamp "
                "FROM trades WHERE status='OPEN'").fetchall()
        trades = []
        for r in rows:
            t = ManagedTrade(
                trade_id=r[0], symbol=r[1], set_id=r[2], strategy=r[3], action=r[4],
                entry_price=r[5], stop_loss=r[6], take_profit=r[7],
                position_size=r[8], dollar_risk=r[9], entry_timestamp=r[10],
            )
            trades.append(t)
        return trades

    def trade_history(self, limit: int = 100) -> List[ManagedTrade]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT trade_id, symbol, set_id, strategy, action, entry_price, "
                "stop_loss, take_profit, position_size, dollar_risk, entry_timestamp, "
                "status, exit_price, exit_reason, exit_timestamp, r_multiple, pnl "
                "FROM trades ORDER BY entry_timestamp DESC LIMIT ?", (limit,)).fetchall()
        trades = []
        for r in rows:
            t = ManagedTrade(
                trade_id=r[0], symbol=r[1], set_id=r[2], strategy=r[3], action=r[4],
                entry_price=r[5], stop_loss=r[6], take_profit=r[7],
                position_size=r[8], dollar_risk=r[9], entry_timestamp=r[10],
            )
            t.status = TradeStatus(r[11])
            t.exit_price = r[12] or 0.0
            t.exit_reason = ExitReason(r[13]) if r[13] else None
            t.exit_timestamp = r[14] or 0
            t.r_multiple = r[15] or 0.0
            t.pnl = r[16] or 0.0
            trades.append(t)
        return trades

