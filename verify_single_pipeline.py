"""
APEX QUANT OS - DAY 15: SINGLE-PIPELINE DIAGNOSTIC HARNESS
Matches decoupled production contracts perfectly.
"""

import os
import sys
import sqlite3
import json
import bisect

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from market_language.market_structure import Candle
from market_language.timeframe_engine import TimeframeEngine
from strategy.strategy_orchestrator import StrategyOrchestrator
from configs.sets import TIMEFRAME_SETS

print("==========================================================================================================")
print("     APEX QUANT OS: SINGLE-PIPELINE DIAGNOSTIC ENGINE (TRUE SMC SPECIFICATION)")
print("==========================================================================================================\n")

def load_candles_from_warehouse(symbol: str, timeframe: str) -> list:
    clean_tf = timeframe.upper()
    sym_variants = [symbol, symbol.replace("/", ""), symbol.replace("/", "_")]
    
    db_paths = [
        os.path.join(ROOT_DIR, "price_warehouse.db"),
        os.path.join(ROOT_DIR, "market_data", "warehouse", "price_warehouse.db"),
        os.path.join(ROOT_DIR, "market_data", "price_warehouse.db")
    ]

    for db_path in db_paths:
        if not os.path.exists(db_path): continue
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [row[0] for row in cursor.fetchall()]

                for table in tables:
                    cursor.execute(f"PRAGMA table_info('{table}');")
                    cols = [c[1].lower() for c in cursor.fetchall()]
                    if not all(k in cols for k in ['open', 'high', 'low', 'close']): continue

                    has_sym = 'symbol' in cols
                    has_tf = 'timeframe' in cols

                    for s_var in sym_variants:
                        query = f"SELECT timestamp, open, high, low, close, volume FROM '{table}'"
                        conds, params = [], []
                        if has_sym: conds.append("symbol = ?"); params.append(s_var)
                        if has_tf: conds.append("UPPER(timeframe) = ?"); params.append(clean_tf)

                        if conds: query += " WHERE " + " AND ".join(conds)
                        query += " ORDER BY timestamp ASC;"

                        try:
                            cursor.execute(query, params)
                            rows = cursor.fetchall()
                            if rows:
                                return [Candle(timestamp=int(r[0]), open=float(r[1]), high=float(r[2]),
                                               low=float(r[3]), close=float(r[4]), volume=float(r[5]) if len(r) > 5 and r[5] else 0.0) for r in rows]
                        except Exception: continue
        except Exception: continue

    cache_dir = os.path.join(ROOT_DIR, "market_data", "cache")
    safe_sym = symbol.replace("/", "_")
    json_paths = [
        os.path.join(cache_dir, f"FULL_{safe_sym}_{timeframe}.json"),
        os.path.join(cache_dir, f"{safe_sym}_{timeframe}_1000.json"),
        os.path.join(cache_dir, f"{safe_sym}_{timeframe}.json")
    ]

    for jp in json_paths:
        if os.path.exists(jp):
            try:
                with open(jp, "r") as f: raw = json.load(f)
                res = []
                for bar in raw:
                    if isinstance(bar, (list, tuple)):
                        res.append(Candle(timestamp=int(bar[0]), open=float(bar[1]), high=float(bar[2]),
                                          low=float(bar[3]), close=float(bar[4]), volume=float(bar[5]) if len(bar) > 5 else 0.0))
                    elif isinstance(bar, dict):
                        res.append(Candle(timestamp=int(bar.get("timestamp", 0)), open=float(bar.get("open", 0.0)),
                                          high=float(bar.get("high", 0.0)), low=float(bar.get("low", 0.0)),
                                          close=float(bar.get("close", 0.0)), volume=float(bar.get("volume", 0.0))))
                if res: return res
            except Exception: continue
    return []

set_cfg = TIMEFRAME_SETS.get("SET_3_SWING")
print(f"📥 Target Set: SET_3_SWING | HTF={set_cfg.htf}, MTF={set_cfg.mtf}, LTF={set_cfg.ltf}")

c_htf = load_candles_from_warehouse("BTC/USDT", set_cfg.htf)
c_mtf = load_candles_from_warehouse("BTC/USDT", set_cfg.mtf)
c_ltf = load_candles_from_warehouse("BTC/USDT", set_cfg.ltf)

print(f"  • GATE 1 [Data Ingestion] -> HTF Candles: {len(c_htf):,} | MTF Candles: {len(c_mtf):,} | LTF Candles: {len(c_ltf):,}")

if not c_htf or not c_mtf or not c_ltf:
    print("\n❌ GATE 1 FAILED: Historical candles missing or empty in price_warehouse.db!")
    sys.exit(1)

print("  ✅ GATE 1 PASSED: Historical market arrays loaded successfully.\n")

tf_engine = TimeframeEngine()
htf_ts = [c.timestamp for c in c_htf]
mtf_ts = [c.timestamp for c in c_mtf]

gates = {
    "evaluated_ltf_bars": 0,
    "executed_trades": 0
}

balance = 1000.0
active_trade = None
trade_history = []

for i in range(120, len(c_ltf), 2):
    gates["evaluated_ltf_bars"] += 1
    curr_bar = c_ltf[i]
    ts = curr_bar.timestamp

    if active_trade is not None:
        closed = False
        exit_p = 0.0
        reason = ""

        if active_trade['action'] == "BUY":
            if curr_bar.low <= active_trade['sl']: closed, exit_p, reason = True, active_trade['sl'], "SL_HIT"
            elif curr_bar.high >= active_trade['tp']: closed, exit_p, reason = True, active_trade['tp'], "TP_HIT"
        else:
            if curr_bar.high >= active_trade['sl']: closed, exit_p, reason = True, active_trade['sl'], "SL_HIT"
            elif curr_bar.low <= active_trade['tp']: closed, exit_p, reason = True, active_trade['tp'], "TP_HIT"

        if closed:
            risk_dist = abs(active_trade['entry'] - active_trade['sl'])
            r_mult = (exit_p - active_trade['entry']) / risk_dist if active_trade['action'] == "BUY" else (active_trade['entry'] - exit_p) / risk_dist
            pnl = (balance * 0.01) * r_mult
            balance += pnl
            trade_history.append({"action": active_trade['action'], "pnl": pnl, "r": r_mult, "reason": reason})
            active_trade = None
            continue

    if active_trade is None:
        idx_mtf = bisect.bisect_right(mtf_ts, ts)
        if idx_mtf < 15: continue
        mtf_slice = mtf_candles = c_mtf[max(0, idx_mtf - 100):idx_mtf]
        mtf_st = tf_engine.evaluate(mtf_slice, timeframe=set_cfg.mtf)

        idx_htf = bisect.bisect_right(htf_ts, ts)
        if idx_htf < 10 or mtf_st is None: continue
        htf_slice = c_htf[max(0, idx_htf - 60):idx_htf]
        ltf_slice = c_ltf[max(0, i - 100):i + 1]

        htf_st = tf_engine.evaluate(htf_slice, timeframe=set_cfg.htf)
        ltf_st = tf_engine.evaluate(ltf_slice, timeframe=set_cfg.ltf)

        if htf_st is None or ltf_st is None: continue

        candidate = StrategyOrchestrator.evaluate_bar(
            set_id="SET_3_SWING",
            htf_state=htf_st,
            mtf_state=mtf_st,
            ltf_state=ltf_st,
            mtf_candles=mtf_slice,
            ltf_candles=ltf_slice,
            account_balance=balance
        )

        if candidate is not None:
            gates["executed_trades"] += 1
            active_trade = {
                "action": candidate.action,
                "entry": candidate.entry_price,
                "sl": candidate.stop_loss,
                "tp": candidate.target_price
            }

print("=" * 100)
print("📊 SINGLE-PIPELINE TELEMETRY (BTC / SET_3_SWING / Strategy B)")
print("=" * 100)
print(f"  • Evaluated LTF Bars    : {gates['evaluated_ltf_bars']:,}")
print(f"  • Executed SMC Trades   : {gates['executed_trades']:,}")

tot_tr = len(trade_history)
if tot_tr > 0:
    wins = [t for t in trade_history if t['pnl'] > 0]
    losses = [t for t in trade_history if t['pnl'] < 0]
    gp = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in losses))
    pf = (gp / gl) if gl > 0 else gp
    wr = (len(wins) / tot_tr) * 100.0

    print("\n📈 PERFORMANCE SUMMARY:")
    print(f"  • Total Trades Executed : {tot_tr:,}")
    print(f"  • Win Rate              : {wr:.1f}%")
    print(f"  • Profit Factor         : {pf:.2f}")
    print(f"  • Final Account Equity  : ${balance:,.2f}")
else:
    print("\n⚠️ ZERO TRADES EXECUTED: Check alignment metrics or R:R thresholds.")
print("=" * 100)
