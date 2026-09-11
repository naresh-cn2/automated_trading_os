"""
APEX Quant OS - Core Warehouse Data Loader
Reads historical candle data directly from price_warehouse.db (SQLite) and JSON caches.
"""

import os
import sys
import json
import sqlite3
from typing import List

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from market_language.market_structure import Candle

DB_PATHS = [
    os.path.join(ROOT_DIR, "price_warehouse.db"),
    os.path.join(ROOT_DIR, "market_data", "warehouse", "price_warehouse.db")
]
CACHE_DIR = os.path.join(ROOT_DIR, "market_data", "cache")


class FullWarehouseLoader:

    @staticmethod
    def load_full_history(symbol: str, timeframe: str) -> List[Candle]:
        candles = FullWarehouseLoader._load_from_sqlite(symbol, timeframe)
        if candles:
            return candles
        return FullWarehouseLoader._load_from_json(symbol, timeframe)

    @staticmethod
    def _load_from_sqlite(symbol: str, timeframe: str) -> List[Candle]:
        clean_tf = timeframe.upper()
        sym_variants = [symbol, symbol.replace("/", ""), symbol.replace("/", "_")]

        for db_path in DB_PATHS:
            if not os.path.exists(db_path):
                continue
            try:
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    tables = [row[0] for row in cursor.fetchall()]

                    for table in tables:
                        cursor.execute(f"PRAGMA table_info('{table}');")
                        cols = [c[1].lower() for c in cursor.fetchall()]
                        
                        # Verify table has price data columns
                        if not all(k in cols for c in ['open', 'high', 'low', 'close']):
                            continue

                        # Check matching symbol & timeframe
                        has_sym = 'symbol' in cols
                        has_tf = 'timeframe' in cols

                        for s_var in sym_variants:
                            query = f"SELECT timestamp, open, high, low, close, volume FROM '{table}'"
                            conditions = []
                            params = []

                            if has_sym:
                                conditions.append("symbol = ?")
                                params.append(s_var)
                            if has_tf:
                                conditions.append("UPPER(timeframe) = ?")
                                params.append(clean_tf)

                            if conditions:
                                query += " WHERE " + " AND ".join(conditions)
                            query += " ORDER BY timestamp ASC;"

                            try:
                                cursor.execute(query, params)
                                rows = cursor.fetchall()
                                if rows:
                                    res = []
                                    for r in rows:
                                        res.append(Candle(
                                            timestamp=int(r[0]),
                                            open=float(r[1]),
                                            high=float(r[2]),
                                            low=float(r[3]),
                                            close=float(r[4]),
                                            volume=float(r[5]) if len(r) > 5 and r[5] is not None else 0.0
                                        ))
                                    return res
                            except Exception:
                                continue
            except Exception as e:
                continue

        return []

    @staticmethod
    def _load_from_json(symbol: str, timeframe: str) -> List[Candle]:
        if not os.path.exists(CACHE_DIR):
            return []

        safe_symbol = symbol.replace("/", "_")
        possible_filenames = [
            os.path.join(CACHE_DIR, f"FULL_{safe_symbol}_{timeframe}.json"),
            os.path.join(CACHE_DIR, f"{safe_symbol}_{timeframe}_5000.json"),
            os.path.join(CACHE_DIR, f"{safe_symbol}_{timeframe}_1000.json"),
            os.path.join(CACHE_DIR, f"{safe_symbol}_{timeframe}.json")
        ]

        for cache_filename in possible_filenames:
            if os.path.exists(cache_filename):
                try:
                    with open(cache_filename, "r") as f:
                        raw_data = json.load(f)
                    
                    candles = []
                    for bar in raw_data:
                        if isinstance(bar, (list, tuple)):
                            candles.append(Candle(
                                timestamp=int(bar[0]), open=float(bar[1]), high=float(bar[2]),
                                low=float(bar[3]), close=float(bar[4]),
                                volume=float(bar[5]) if len(bar) > 5 else 0.0
                            ))
                        elif isinstance(bar, dict):
                            candles.append(Candle(
                                timestamp=int(bar.get("timestamp", bar.get("time", 0))),
                                open=float(bar.get("open", 0.0)), high=float(bar.get("high", 0.0)),
                                low=float(bar.get("low", 0.0)), close=float(bar.get("close", 0.0)),
                                volume=float(bar.get("volume", 0.0))
                            ))
                    return candles
                except Exception:
                    continue

        return []
