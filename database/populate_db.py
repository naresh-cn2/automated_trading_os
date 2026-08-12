"""
APEX Quant OS - Producer Engine: Database Populator
Executes tracked core strategy engine and saves trade records into SQLite.
"""

import os
import sys
import datetime
import bisect

# Inject project root directory into sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from market_data.warehouse_loader import FullWarehouseLoader
from database.trade_db import MasterTradeDatabase
from configs.sets import TIMEFRAME_SETS
from market_language.timeframe_engine import TimeframeEngine
from risk.risk_engine import RiskEngine


def tf_str_to_ccxt(tf: str) -> str:
    tf_map = {"1M": "1M", "1W": "1w", "1D": "1d", "4H": "4h", "1H": "1h", "15M": "15m"}
    return tf_map.get(tf.upper(), tf)


def run_cell_and_collect_trades(asset: str, set_cfg, strategy_name: str):
    set_key = set_cfg.set_id.value
    c_htf = FullWarehouseLoader.load_full_history(asset, tf_str_to_ccxt(set_cfg.htf))
    c_mtf = FullWarehouseLoader.load_full_history(asset, tf_str_to_ccxt(set_cfg.mtf))
    c_ltf = FullWarehouseLoader.load_full_history(asset, tf_str_to_ccxt(set_cfg.ltf))

    if not c_htf or not c_mtf or not c_ltf:
        return []

    tf_engine = TimeframeEngine()
    htf_ts = [c.timestamp for c in c_htf]
    mtf_ts = [c.timestamp for c in c_mtf]

    balance = 1000.0
    active_trade = None
    trade_counter = 0
    trade_logs = []

    for i in range(120, len(c_ltf), 2):
        current_bar = c_ltf[i]
        ts = current_bar.timestamp

        idx_mtf = bisect.bisect_right(mtf_ts, ts)
        if idx_mtf < 15: continue
        mtf_slice = c_mtf[max(0, idx_mtf - 100):idx_mtf]
        mtf_st = tf_engine.evaluate(mtf_slice, timeframe=set_cfg.mtf)

        # 1. Trade Management
        if active_trade is not None:
            closed = False
            exit_price = 0.0
            reason = ""

            if active_trade['action'] == "BUY":
                if current_bar.low <= active_trade['stop_loss']:
                    closed = True
                    exit_price = active_trade['stop_loss']
                    reason = "SL_HIT"
                elif current_bar.high >= active_trade['target_price']:
                    closed = True
                    exit_price = active_trade['target_price']
                    reason = "TP_HIT"
            else:
                if current_bar.high >= active_trade['stop_loss']:
                    closed = True
                    exit_price = active_trade['stop_loss']
                    reason = "SL_HIT"
                elif current_bar.low <= active_trade['target_price']:
                    closed = True
                    exit_price = active_trade['target_price']
                    reason = "TP_HIT"

            if closed:
                trade_counter += 1
                risk_dist = abs(active_trade['entry_price'] - active_trade['stop_loss'])
                r_mult = (exit_price - active_trade['entry_price']) / risk_dist if active_trade['action'] == "BUY" else (active_trade['entry_price'] - exit_price) / risk_dist
                
                dollar_risk = balance * 0.01
                pnl = dollar_risk * r_mult
                balance += pnl

                dt_str = datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M') if ts > 0 else "N/A"

                trade_logs.append({
                    "trade_id": trade_counter, "asset": asset, "set_id": set_key,
                    "strategy_name": strategy_name, "action": active_trade['action'],
                    "entry_price": active_trade['entry_price'], "exit_price": exit_price,
                    "stop_loss": active_trade['stop_loss'], "target_price": active_trade['target_price'],
                    "r_multiple": r_mult, "pnl_dollars": pnl, "mfe_r": 0.0, "mae_r": 0.0,
                    "duration_bars": 0, "exit_reason": reason,
                    "entry_timestamp_ms": ts, "entry_time_utc": dt_str
                })
                active_trade = None

        # 2. Entry Evaluation
        if active_trade is None:
            idx_htf = bisect.bisect_right(htf_ts, ts)
            if idx_htf < 10 or mtf_st is None: continue
            htf_slice = c_htf[max(0, idx_htf - 60):idx_htf]
            ltf_slice = c_ltf[max(0, i-100):i+1]

            htf_st = tf_engine.evaluate(htf_slice, timeframe=set_cfg.htf)
            ltf_st = tf_engine.evaluate(ltf_slice, timeframe=set_cfg.ltf)

            if htf_st is None or ltf_st is None: continue

            htf_bias = getattr(htf_st, 'trend_direction', getattr(htf_st, 'trend', 'NEUTRAL'))
            if isinstance(htf_bias, object) and hasattr(htf_bias, 'value'):
                htf_bias = htf_bias.value

            if htf_bias in ["BULLISH", "BEARISH"]:
                entry_p = current_bar.close
                sl_p = ltf_slice[-1].low if htf_bias == "BULLISH" else ltf_slice[-1].high
                risk_dist = abs(entry_p - sl_p)

                if risk_dist > 0:
                    tp_p = entry_p + (risk_dist * 4.0) if htf_bias == "BULLISH" else entry_p - (risk_dist * 4.0)
                    risk_res = RiskEngine.calculate_risk(balance, entry_p, sl_p, tp_p, 0.01, 4.0)

                    if risk_res.is_trade_allowed:
                        active_trade = {
                            "action": "BUY" if htf_bias == "BULLISH" else "SELL",
                            "entry_price": entry_p,
                            "stop_loss": sl_p,
                            "target_price": tp_p
                        }

    return trade_logs


def run_and_populate():
    assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    strategies = ["StrategyA_PullbackRiding", "StrategyB_ContinuationRiding"]
    sets = list(TIMEFRAME_SETS.values())

    print("==========================================================================================================")
    print("      APEX QUANT OS: PRODUCER ENGINE - POPULATING SQLITE DATABASE (CLEAN BASELINE)")
    print("==========================================================================================================\n")

    all_trades = []
    total_cells = len(assets) * len(sets) * len(strategies)
    cell_idx = 0

    for asset in assets:
        print(f"📥 Processing Asset Universe: {asset}...")
        for set_cfg in sets:
            for strat_name in strategies:
                cell_idx += 1
                print(f"  ⚡ [{cell_idx}/{total_cells}] Running {asset} | {set_cfg.set_id.value} | {strat_name}...")
                cell_trades = run_cell_and_collect_trades(asset, set_cfg, strat_name)
                all_trades.extend(cell_trades)

    MasterTradeDatabase.save_trades_batch(all_trades)
    print("\n  ✅ Producer Run Complete! Database populated cleanly.")


if __name__ == "__main__":
    run_and_populate()
