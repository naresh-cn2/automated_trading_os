"""
APEX Quant OS - Master Relational Trade Database Engine (SQLite)
Persists trade execution logs cleanly without touching core strategy files.
"""

import os
import sqlite3
from typing import List, Dict, Any

DB_PATH = "database/apex_research_master.db"


class MasterTradeDatabase:

    @staticmethod
    def get_connection():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        return sqlite3.connect(DB_PATH)

    @staticmethod
    def initialize_schema():
        with MasterTradeDatabase.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS master_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    asset TEXT,
                    set_id TEXT,
                    strategy_name TEXT,
                    action TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    stop_loss REAL,
                    target_price REAL,
                    r_multiple REAL,
                    pnl_dollars REAL,
                    mfe_r REAL,
                    mae_r REAL,
                    duration_bars INTEGER,
                    exit_reason TEXT,
                    entry_timestamp_ms INTEGER,
                    entry_time_utc TEXT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_asset_set ON master_trades(asset, set_id, strategy_name);")
            conn.commit()

    @staticmethod
    def save_trades_batch(trade_records: List[Dict[str, Any]]):
        MasterTradeDatabase.initialize_schema()
        with MasterTradeDatabase.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM master_trades;")
            
            for t in trade_records:
                cursor.execute("""
                    INSERT INTO master_trades (
                        trade_id, asset, set_id, strategy_name, action, entry_price, exit_price,
                        stop_loss, target_price, r_multiple, pnl_dollars, mfe_r, mae_r,
                        duration_bars, exit_reason, entry_timestamp_ms, entry_time_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    t.get('trade_id', 0), t.get('asset', ''), t.get('set_id', ''), t.get('strategy_name', ''),
                    t.get('action', ''), t.get('entry_price', 0.0), t.get('exit_price', 0.0),
                    t.get('stop_loss', 0.0), t.get('target_price', 0.0), t.get('r_multiple', 0.0),
                    t.get('pnl_dollars', 0.0), t.get('mfe_r', 0.0), t.get('mae_r', 0.0),
                    t.get('duration_bars', 0), t.get('exit_reason', ''),
                    t.get('entry_timestamp_ms', 0), t.get('entry_time_utc', '')
                ))
            conn.commit()
        print(f"  💾 [Master Database Persisted] Saved {len(trade_records)} trades to {DB_PATH}")

    @staticmethod
    def fetch_all_trades() -> List[Dict[str, Any]]:
        MasterTradeDatabase.initialize_schema()
        with MasterTradeDatabase.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM master_trades ORDER BY entry_timestamp_ms ASC;")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
