"""
APEX Quant OS - Full Multi-Asset / Multi-Set Backtest Runner
Runs the complete HTF Bias -> MTF Setup -> LTF Entry pipeline (both Pullback
Riding and Continuation Riding) across BTC / ETH / SOL and all four timeframe
sets (trading styles), with full MTF structural trailing management.

Usage:  venv/bin/python run_full_backtest.py [--balance 1000]
"""

import argparse
import csv
import sys
import os

ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from configs.sets import TIMEFRAME_SETS, TimeframeSetID
from backtesting.backtest_engine import BacktestEngine, BacktestConfig
from trade_management.mtf_trailing_engine import ExitReason


ALL_ASSETS = ["BTC", "ETH", "SOL"]
SET_LABELS = {s.value: s for s in TimeframeSetID}


def parse_args():
    p = argparse.ArgumentParser(description="APEX full multi-asset/multi-set backtest")
    p.add_argument("--assets", default="BTC,ETH,SOL",
                   help="comma-separated assets, e.g. BTC,ETH")
    p.add_argument("--sets", default="all",
                   help="comma-separated set ids, e.g. SET_3_SWING,SET_4_INTRADAY; or 'all'")
    p.add_argument("--balance", type=float, default=1000.0)
    p.add_argument("--risk", type=float, default=0.01, help="fraction risked per trade (default 0.01)")
    p.add_argument("--minrr", type=float, default=4.0, help="minimum reward:risk (default 4.0)")
    p.add_argument("--maker-fee", type=float, default=0.0002,
                   help="post-only limit fill fee fraction (entry + TP), default 0.0002")
    p.add_argument("--taker-fee", type=float, default=0.0005,
                   help="market fill fee fraction (SL + trailing exits), default 0.0005")
    p.add_argument("--taker-slip", type=float, default=0.0003,
                   help="adverse slippage fraction on market exits, default 0.0003")
    p.add_argument("--costbudget", type=float, default=0.25,
                   help="skip trades whose est. round-trip cost exceeds this fraction of risk, default 0.25")
    p.add_argument("--minvol", type=float, default=0.0,
                   help="LTF ATR%% floor filter (0 disables); skip dead low-vol chop")
    p.add_argument("--rrpullback", type=float, default=1.5,
                   help="premium R:R multiplier for pullback (Strategy A) entries, default 1.5")
    p.add_argument("--lockin", type=float, default=0.5,
                   help="start profit-lock after this many R favorable excursion, default 0.5")
    p.add_argument("--giveback", type=float, default=0.25,
                   help="max R giveback from the peak allowed before locking, default 0.25")
    p.add_argument("--export", default=None, help="optional path to write all trades to CSV")
    return p.parse_args()


def export_csv(results, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "set_id", "strategy", "action",
                    "entry_price", "initial_stop_loss", "stop_loss", "take_profit",
                    "position_size", "dollar_risk",
                    "exit_price", "exit_reason", "r_multiple", "pnl"])
        for _sym, _set, _cfg, res in results:
            for t in res.trades:
                w.writerow([t.symbol, t.set_id, t.strategy, t.action,
                            round(t.entry_price, 6),
                            round(getattr(t, "initial_stop_loss", 0.0) or t.stop_loss, 6),
                            round(t.stop_loss, 6),
                            round(t.take_profit, 6), round(t.position_size, 8),
                            round(t.dollar_risk, 4), round(t.exit_price, 6),
                            t.exit_reason.value if t.exit_reason else "",
                            round(t.r_multiple, 4), round(t.pnl, 4)])
    print(f"\n  📄 Exported {sum(len(r.trades) for _,_,_,r in results)} trades -> {path}")


def main():
    args = parse_args()
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    if args.sets.strip().lower() == "all":
        set_ids = list(TimeframeSetID)
    else:
        set_ids = [SET_LABELS[s.strip().upper()] for s in args.sets.split(",") if s.strip()]

    engine = BacktestEngine(BacktestConfig(
        initial_balance=args.balance, risk_pct=args.risk, min_rr=args.minrr,
        maker_fee=args.maker_fee, taker_fee=args.taker_fee,
        taker_slippage=args.taker_slip,
        cost_budget_pct=args.costbudget, min_vol_pct=args.minvol,
        rr_pullback_mult=args.rrpullback,
        lockin_r=args.lockin, giveback_r=args.giveback,
    ))
    all_results = []

    print("=" * 96)
    print("  APEX QUANT OS - FULL BACKTEST (HTF Bias -> MTF Setup -> LTF Entry)")
    print(f"  Assets: {', '.join(assets)}   |   Sets: {', '.join(s.value for s in set_ids)}")
    print(f"  Risk: {args.risk*100:.1f}%/trade  |  Min R:R 1:{args.minrr:.0f}  |  "
          f"Management: MTF structural trailing")
    print(f"  Execution: maker={args.maker_fee*100:.2f}%/entry&TP  taker={args.taker_fee*100:.2f}%/SL&trail  "
          f"taker-slip={args.taker_slip*10000:.1f}bps  |  cost-filter budget={args.costbudget*100:.0f}% of risk"
          + (f"  |  minvol={args.minvol:.2f}%" if args.minvol > 0 else ""))
    print(f"  Profit-lock: lock after +{args.lockin:.1f}R, max {args.giveback:.2f}R giveback  |  "
          f"pullback premium R:R x{args.rrpullback:.1f}")
    print("=" * 96)

    header = (f"{'Combination':<28}{'TF':<15}{'Trd':>5}{'WR%':>7}{'PF':>7}"
              f"{'avgR':>7}{'TP':>5}{'Trl':>6}{'SL':>5}{'NetP&L':>10}{'MaxDD%':>8}{'Ret%':>8}")
    print(header)
    print("-" * 96)

    for asset in assets:
        symbol = f"{asset}USDT"
        for set_id in set_ids:
            cfg = TIMEFRAME_SETS[set_id]
            res = engine.run(symbol, set_id.value, cfg.htf, cfg.mtf, cfg.ltf)
            s = res.stats
            all_results.append((symbol, set_id.value, cfg, res))
            print(f"{symbol+'/'+set_id.value:<28}{cfg.htf+' '+cfg.mtf+' '+cfg.ltf:<15}"
                  f"{s['trades']:>5}{s['win_rate']:>7.1f}{s['profit_factor']:>7.2f}"
                  f"{s['avg_r']:>7.2f}{s['tp_hits']:>5}{s['trail_exits']:>6}"
                  f"{s['sl_hits']:>5}{s['net_pnl']:>10.2f}{s['max_dd_pct']:>8.1f}"
                  f"{s['return_pct']:>8.1f}")

    print("-" * 96)
    _summarize("BY SET", all_results, key=lambda r: r[1])
    _summarize("BY SYMBOL", all_results, key=lambda r: r[0])
    _summarize_by_strategy(all_results)

    # Combined bottom line
    all_trades = [t for _, _, _, res in all_results for t in res.trades]
    n = len(all_trades)
    if n:
        tp = sum(1 for t in all_trades if t.exit_reason == ExitReason.TP_HIT)
        trail = sum(1 for t in all_trades if t.exit_reason in
                    (ExitReason.MTF_TRAIL_HIT, ExitReason.MTF_CHOCH_EXIT))
        sl = sum(1 for t in all_trades if t.exit_reason == ExitReason.SL_HIT)
        wins = [t for t in all_trades if t.pnl > 0]
        gw = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in all_trades if t.pnl < 0))
        pf = (gw / gl) if gl > 0 else 0.0
        print("=" * 96)
        print(f"  COMBINED: trades={n}  wins={len(wins)} ({len(wins)/n*100:.1f}%)  "
              f"PF={pf:.2f}  TP={tp}  Trail={trail}  SL={sl}")
        print(f"  Exit mix: TP {tp/n*100:.1f}% | MTF-Trail {trail/n*100:.1f}% | SL {sl/n*100:.1f}%")
        total_pnl = sum(res.final_balance - res.initial_balance
                        for _, _, _, res in all_results)
        avg_ret = sum(res.stats["return_pct"] for _, _, _, res in all_results) / len(all_results)
        print(f"  Aggregate Net P&L: ${total_pnl:,.2f}  |  Avg combo return: {avg_ret:.1f}%")
        print(f"  Note: equity/capital is treated as separate ${args.balance:,.0f} per combo "
              f"({len(all_results)} independent accounts).")
    print("=" * 96)

    if args.export:
        export_csv(all_results, args.export)


def _summarize_by_strategy(results):
    groups = {"A_PULLBACK_RIDING": [], "B_CONTINUATION_RIDING": []}
    for _sym, _set, _cfg, res in results:
        for t in res.trades:
            groups.setdefault(t.strategy, []).append(t)
    print("\n--- BY STRATEGY ---")
    for tag, trades in groups.items():
        n = len(trades)
        if not n:
            print(f"  {tag:<20} 0 trades")
            continue
        wins = [t for t in trades if t.pnl > 0]
        gw = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in trades if t.pnl < 0))
        pf = (gw / gl) if gl > 0 else 0.0
        avg_r = sum(t.r_multiple for t in trades) / n
        print(f"  {tag:<20} trades={n:>4}  WR={len(wins)/n*100:>6.1f}%  PF={pf:>6.2f}  avgR={avg_r:>6.2f}")


def _summarize(title, results, key):
    groups = {}
    for symbol, set_id, cfg, res in results:
        tag = key((symbol, set_id, cfg, res))
        groups.setdefault(tag, []).append(res)
    print(f"\n--- {title} ---")
    for tag, reslist in groups.items():
        trades = [t for r in reslist for t in r.trades]
        n = len(trades)
        if not n:
            print(f"  {tag:<10} 0 trades")
            continue
        wins = [t for t in trades if t.pnl > 0]
        gw = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in trades if t.pnl < 0))
        pf = (gw / gl) if gl > 0 else 0.0
        avg_r = sum(t.r_multiple for t in trades) / n
        print(f"  {tag:<10} trades={n:>4}  WR={len(wins)/n*100:>6.1f}%  PF={pf:>6.2f}  avgR={avg_r:>6.2f}")


if __name__ == "__main__":
    main()
