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
                       exit_timestamp INTEGER, r_multiple REAL, pnl REAL,
                       maker_fee REAL DEFAULT 0.0002,
                       taker_fee REAL DEFAULT 0.0005,
                       taker_slippage REAL DEFAULT 0.0003,
                       lockin_r REAL DEFAULT 0.5,
                       giveback_r REAL DEFAULT 0.25,
                       entry_risk_distance REAL DEFAULT 0.0,
                       initial_stop_loss REAL DEFAULT 0.0,
                       max_favorable_price REAL DEFAULT 0.0,
                       last_mtf_event_ts INTEGER DEFAULT 0,
                       trail_history TEXT DEFAULT '[]')"""
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('balance', ?)",
                (starting_balance,),
            )
        self._ensure_state_columns()

    # ------------------------------------------------------------------
    def balance(self) -> float:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='balance'").fetchone()
            return float(row[0]) if row else 0.0

    def _set_balance(self, value: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE meta SET value=? WHERE key='balance'", (value,))

    # ------------------------------------------------------------------
    def open_trade(self, candidate, symbol: str, set_id: str, timestamp: int,
                   maker_fee: float = 0.0002, taker_fee: float = 0.0005,
                   taker_slippage: float = 0.0003,
                   lockin_r: float = 0.5, giveback_r: float = 0.25) -> ManagedTrade:
        risk_dist = abs(float(candidate.entry_price) - float(candidate.stop_loss))
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
            maker_fee=maker_fee, taker_fee=taker_fee,
            taker_slippage=taker_slippage,
            lockin_r=lockin_r, giveback_r=giveback_r,
            entry_risk_distance=risk_dist,
            initial_stop_loss=float(candidate.stop_loss),
            max_favorable_price=float(candidate.entry_price),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO trades (trade_id, symbol, set_id, strategy, action,
                       entry_price, stop_loss, take_profit, position_size,
                       dollar_risk, entry_timestamp, status,
                       maker_fee, taker_fee, taker_slippage,
                       lockin_r, giveback_r, entry_risk_distance,
                       initial_stop_loss, max_favorable_price,
                       last_mtf_event_ts, trail_history)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trade.trade_id, trade.symbol, trade.set_id, trade.strategy,
                 trade.action, trade.entry_price, trade.stop_loss, trade.take_profit,
                 trade.position_size, trade.dollar_risk, trade.entry_timestamp,
                 TradeStatus.OPEN.value,
                 trade.maker_fee, trade.taker_fee, trade.taker_slippage,
                 trade.lockin_r, trade.giveback_r, trade.entry_risk_distance,
                 trade.initial_stop_loss, trade.max_favorable_price,
                 trade.last_mtf_event_ts, "[]"),
            )
        return trade

    def sync_open_trade(self, trade: ManagedTrade) -> None:
        """Persist mutated trailing state so restarts / re-reads don't reset it."""
        import json as _json
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE trades SET stop_loss=?, max_favorable_price=?,
                       last_mtf_event_ts=?, trail_history=? WHERE trade_id=?""",
                (trade.stop_loss, trade.max_favorable_price,
                 trade.last_mtf_event_ts,
                 _json.dumps(list(trade.trail_history or [])),
                 trade.trade_id),
            )

    def _ensure_state_columns(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
            adds = {
                "maker_fee": "REAL DEFAULT 0.0002",
                "taker_fee": "REAL DEFAULT 0.0005",
                "taker_slippage": "REAL DEFAULT 0.0003",
                "lockin_r": "REAL DEFAULT 0.5",
                "giveback_r": "REAL DEFAULT 0.25",
                "entry_risk_distance": "REAL DEFAULT 0.0",
                "initial_stop_loss": "REAL DEFAULT 0.0",
                "max_favorable_price": "REAL DEFAULT 0.0",
                "last_mtf_event_ts": "INTEGER DEFAULT 0",
                "trail_history": "TEXT DEFAULT '[]'",
            }
            for col, ddl in adds.items():
                if col not in cols:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {ddl}")

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
        self._ensure_state_columns()
        import json as _json
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT trade_id, symbol, set_id, strategy, action, entry_price, "
                "stop_loss, take_profit, position_size, dollar_risk, entry_timestamp, "
                "maker_fee, taker_fee, taker_slippage, lockin_r, giveback_r, "
                "entry_risk_distance, initial_stop_loss, max_favorable_price, "
                "last_mtf_event_ts, trail_history "
                "FROM trades WHERE status='OPEN'").fetchall()
        trades = []
        for r in rows:
            try:
                trail = _json.loads(r[20] or "[]")
            except Exception:
                trail = []
            t = ManagedTrade(
                trade_id=r[0], symbol=r[1], set_id=r[2], strategy=r[3], action=r[4],
                entry_price=r[5], stop_loss=r[6], take_profit=r[7],
                position_size=r[8], dollar_risk=r[9], entry_timestamp=r[10],
                maker_fee=(r[11] if r[11] is not None else 0.0002),
                taker_fee=(r[12] if r[12] is not None else 0.0005),
                taker_slippage=(r[13] if r[13] is not None else 0.0003),
                lockin_r=(r[14] if r[14] is not None else 0.5),
                giveback_r=(r[15] if r[15] is not None else 0.25),
                entry_risk_distance=(r[16] or 0.0),
                initial_stop_loss=(r[17] or r[6]),
                max_favorable_price=(r[18] or r[5]),
                last_mtf_event_ts=(r[19] or 0),
                trail_history=list(trail),
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

