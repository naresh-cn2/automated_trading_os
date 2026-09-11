"""
APEX Quant OS - Master Unified Research Laboratory Cockpit
Queries SQLite Database directly in <50ms without re-executing backtests.
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import sqlite3
import random
import numpy as np
from typing import List, Dict, Any

from database.trade_db import MasterTradeDatabase

OOS_SPLIT_TIMESTAMP_MS = 1704067200000  # Jan 1, 2024 Split Window


def calculate_metrics(trades: List[Dict[str, Any]], starting_balance: float = 1000.0) -> Dict[str, Any]:
    tot = len(trades)
    if tot == 0:
        return {"total_trades": 0, "win_rate_pct": 0.0, "profit_factor": 1.0, "net_pnl": 0.0, "max_dd_pct": 0.0, "final_equity": starting_balance}

    wins = [t for t in trades if t['pnl_dollars'] > 0]
    losses = [t for t in trades if t['pnl_dollars'] < 0]

    gp = sum(t['pnl_dollars'] for t in wins)
    gl = abs(sum(t['pnl_dollars'] for t in losses))
    pf = (gp / gl) if gl > 0 else gp

    bal = starting_balance
    peak = starting_balance
    max_dd = 0.0

    for t in trades:
        bal += t['pnl_dollars']
        if bal > peak: peak = bal
        dd = (peak - bal) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd: max_dd = dd

    return {
        "total_trades": tot,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / tot) * 100.0,
        "gross_profit": gp,
        "gross_loss": gl,
        "net_pnl": bal - starting_balance,
        "final_equity": bal,
        "profit_factor": pf,
        "max_dd_pct": max_dd
    }


def execute_master_lab_suite():
    print("==========================================================================================================")
    print("     APEX QUANT OS: MASTER UNIFIED RESEARCH LABORATORY COCKPIT")
    print("==========================================================================================================\n")

    all_trades = MasterTradeDatabase.fetch_all_trades()
    if not all_trades:
        print("⚠️ Master SQLite Database empty! Run populate_db.py first.")
        return

    print(f"📊 Processing {len(all_trades):,} historical trade execution records natively...\n")

    # 1. 24-Matrix Summary Table
    print("📈 [PART 1: THE PORTFOLIO RETURN EXTRACTION MATRIX]")
    print("=" * 122)
    print(f"{'ASSET':<10} | {'SET ID':<18} | {'STRATEGY NAME':<28} | {'TRADES':<6} | {'WIN %':<6} | {'P.FACTOR':<8} | {'FINAL EQUITY':<12}")
    print("=" * 122)
    
    assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    sets = ["SET_1_INVESTING", "SET_2_POSITIONAL", "SET_3_SWING", "SET_4_INTRADAY"]
    strats = ["StrategyA_PullbackRiding", "StrategyB_ContinuationRiding"]

    for a in assets:
        for s in sets:
            for st in strats:
                subset = [t for t in all_trades if t['asset'] == a and t['set_id'] == s and t['strategy_name'] == st]
                res = calculate_metrics(subset)
                if res['total_trades'] > 0:
                    print(f"{a:<10} | {s:<18} | {st:<28} | {res['total_trades']:<6} | {res['win_rate_pct']:<5.1f}% | {res['profit_factor']:<8.2f} | ${res['final_equity']:<11.2f}")
    print("=" * 122)

    # 2. Walk-Forward Stability Check
    print("\n⚡ [PART 2: STABILITY VERIFICATION (OUT-OF-SAMPLE VALIDATION)]")
    btc_swing = [t for t in all_trades if t['asset'] == "BTC/USDT" and t['set_id'] == "SET_3_SWING" and t['strategy_name'] == "StrategyB_ContinuationRiding"]
    is_metrics = calculate_metrics([t for t in btc_swing if t['entry_timestamp_ms'] < OOS_SPLIT_TIMESTAMP_MS])
    oos_metrics = calculate_metrics([t for t in btc_swing if t['entry_timestamp_ms'] >= OOS_SPLIT_TIMESTAMP_MS])
    
    print(f"  • In-Sample Training (2017-2023) : {is_metrics['total_trades']} Trades | Win Rate: {is_metrics['win_rate_pct']:.1f}% | PF: {is_metrics['profit_factor']:.2f}")
    print(f"  • Out-of-Sample Testing (2024-2026): {oos_metrics['total_trades']} Trades | Win Rate: {oos_metrics['win_rate_pct']:.1f}% | PF: {oos_metrics['profit_factor']:.2f}")

    # 3. Path-Dependent Compounded Monte Carlo Simulation
    print("\n🎲 [PART 3: MONTE CARLO RISK SIMULATION (1,000 PERMUTATIONS + NOISE)]")
    if btc_swing:
        r_multiples = [t['r_multiple'] for t in btc_swing]
        sim_final_equities = []
        sim_max_drawdowns = []

        for _ in range(1000):
            shuffled_r = r_multiples.copy()
            random.shuffle(shuffled_r)
            bal = 1000.0
            peak = 1000.0
            max_dd = 0.0

            for r in shuffled_r:
                noise = random.uniform(0.95, 1.05)
                risk_amt = bal * 0.01
                pnl = (risk_amt * r * noise) - (risk_amt * 0.001)
                bal += pnl
                if bal > peak: peak = bal
                dd = (peak - bal) / peak * 100.0 if peak > 0 else 0.0
                if dd > max_dd: max_dd = dd

            sim_final_equities.append(bal)
            sim_max_drawdowns.append(max_dd)

        p5_eq = np.percentile(sim_final_equities, 5)
        p50_eq = np.percentile(sim_final_equities, 50)
        p95_eq = np.percentile(sim_final_equities, 95)
        p95_dd = np.percentile(sim_max_drawdowns, 95)
        p50_dd = np.percentile(sim_max_drawdowns, 50)

        print(f"  • 5th Percentile Worst-Case Equity Outcome : ${p5_eq:,.2f}")
        print(f"  • Median Expected Equity Outcome           : ${p50_eq:,.2f}")
        print(f"  • 95th Percentile Best-Case Equity Outcome  : ${p95_eq:,.2f}")
        print(f"  • Median Expected Max Drawdown            : {p50_dd:.2f}%")
        print(f"  • 95th Percentile Max Drawdown (Worst Risk): {p95_dd:.2f}%")

    print("\n==========================================================================================================")
    print("  ✅ PASS: Unified Research Cockpit Execution Completed!")


if __name__ == "__main__":
    execute_master_lab_suite()
