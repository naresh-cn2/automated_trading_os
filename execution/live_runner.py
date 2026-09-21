"""
APEX Quant OS - Layer 6: 24/7 Live Orchestration Runner

Runs the full HTF Bias -> MTF Setup -> LTF Entry pipeline continuously on fresh
market data for BTC / ETH / SOL across all four timeframe sets, executing through
the disk-persistent PaperBroker (paper mode by default). Open positions are
managed by the MTF structural trailing engine on every new MTF bar.

Two candle sources are supported:
  * ccxt      -> live Binance public market data (requires network)
  * warehouse -> replay from the local price warehouse (offline testing)

CLI:
  venv/bin/python execution/live_runner.py --source warehouse --once
  venv/bin/python execution/live_runner.py --source ccxt            # 24/7 paper
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from market_language.market_structure import Candle
from market_language.timeframe_engine import TimeframeEngine

from configs.sets import TIMEFRAME_SETS, TimeframeSetID
from strategy.strategy_orchestrator import StrategyOrchestrator
from trade_management.mtf_trailing_engine import MTFTrailingEngine, ManagedTrade
from execution.paper_broker import PaperBroker


# ccxt timeframe label mapping (our label -> ccxt)
_CCXT_TF = {"15M": "15m", "1H": "1h", "4H": "4h", "1D": "1d", "1W": "1w", "1M": "1M"}


class CcxtProvider:
    """Live candle source via the Binance public API (ccxt)."""

    def __init__(self):
        import ccxt
        self.exchange = ccxt.binance({"enableRateLimit": True})

    def fetch(self, symbol_label: str, timeframe: str, limit: int = 500) -> list:
        symbol = f"{symbol_label}/USDT"
        ohlcv = self.exchange.fetch_ohlcv(symbol, _CCXT_TF[timeframe], limit=limit)
        return [
            Candle(timestamp=int(o[0]), open=float(o[1]), high=float(o[2]),
                   low=float(o[3]), close=float(o[4]),
                   volume=float(o[5]) if len(o) > 5 else 0.0)
            for o in ohlcv
        ]


class WarehouseProvider:
    """Offline candle source that replays the local price warehouse."""

    def __init__(self, db_path: str = None):
        from backtesting.backtest_engine import WarehouseLoader
        self.loader = WarehouseLoader(db_path)

    def fetch(self, symbol_label: str, timeframe: str, limit: int = 500) -> list:
        candles = self.loader.load(f"{symbol_label}USDT", timeframe)
        return candles[-limit:]


class LiveRunner:

    # Certified backtest defaults — live/paper MUST match the backtest, or the
    # "profitable" claim does not transfer. Keep in sync with BacktestConfig.
    RISK_PCT = 0.01
    MIN_RR = 4.0
    MAKER_FEE = 0.0002
    TAKER_FEE = 0.0005
    TAKER_SLIPPAGE = 0.0003
    COST_BUDGET_PCT = 0.25
    MIN_VOL_PCT = 0.0
    RR_PULLBACK_MULT = 1.5
    LOCKIN_R = 0.5
    GIVEBACK_R = 0.25

    def __init__(self, provider, broker: PaperBroker,
                 assets=None, sets=None, lookbacks=(120, 160, 160)):
        self.provider = provider
        self.broker = broker
        self.assets = assets or ["BTC", "ETH", "SOL"]
        self.set_ids = sets or list(TimeframeSetID)
        self.htf_lookback, self.mtf_lookback, self.ltf_lookback = lookbacks
        self.tf_engine = TimeframeEngine()
        self._last_processed = {}   # (asset, set) -> last LTF ts
        self._last_mtf_idx = {}     # (asset, set) -> last processed MTF ts

    # ------------------------------------------------------------------
    def step(self) -> int:
        """One evaluation cycle over all assets/sets. Returns new signals issued."""
        signals = 0
        for asset in self.assets:
            for set_id in self.set_ids:
                cfg = TIMEFRAME_SETS[set_id]
                key = (asset, set_id.value)

                ltf_candles = self.provider.fetch(asset, cfg.ltf, self.ltf_lookback)
                if not ltf_candles:
                    continue
                last_ts = ltf_candles[-1].timestamp
                if self._last_processed.get(key) == last_ts:
                    continue  # no new LTF bar yet
                self._last_processed[key] = last_ts

                htf_candles = self.provider.fetch(asset, cfg.htf, self.htf_lookback)
                mtf_candles = self.provider.fetch(asset, cfg.mtf, self.mtf_lookback)

                try:
                    htf_state = self.tf_engine.evaluate(htf_candles, timeframe=cfg.htf)
                    mtf_state = self.tf_engine.evaluate(mtf_candles, timeframe=cfg.mtf)
                    ltf_state = self.tf_engine.evaluate(ltf_candles, timeframe=cfg.ltf)
                except Exception:
                    continue

                combo_positions = [
                    p for p in self.broker.open_positions()
                    if p.set_id == set_id.value and p.symbol == f"{asset}USDT"
                ]

                # ----- manage existing positions -----
                for trade in combo_positions:
                    bar = ltf_candles[-1]
                    hit = MTFTrailingEngine.check_intrabar_exit(trade, bar)
                    if hit is not None:
                        self.broker.close_trade(trade, hit[0], hit[1], bar.timestamp)
                    else:
                        if self._last_mtf_idx.get(key, 0) < mtf_candles[-1].timestamp:
                            sig = MTFTrailingEngine.on_mtf_close(trade, mtf_state)
                            if sig is not None:
                                self.broker.close_trade(trade, bar.close, sig[1], bar.timestamp)
                            else:
                                # persist ratcheted stop / peak / event cursor
                                try:
                                    self.broker.sync_open_trade(trade)
                                except AttributeError:
                                    pass
                            self._last_mtf_idx[key] = mtf_candles[-1].timestamp
                        else:
                            # intrabar profit-lock may have moved the stop: persist it
                            try:
                                self.broker.sync_open_trade(trade)
                            except AttributeError:
                                pass

                # ----- new entry (only if combo is flat) -----
                combo_positions = [
                    p for p in self.broker.open_positions()
                    if p.set_id == set_id.value and p.symbol == f"{asset}USDT"
                ]
                if combo_positions:
                    continue

                candidate = StrategyOrchestrator.evaluate_bar(
                    set_id=set_id.value,
                    htf_state=htf_state, mtf_state=mtf_state, ltf_state=ltf_state,
                    htf_candles=htf_candles, mtf_candles=mtf_candles,
                    ltf_candles=ltf_candles,
                    risk_pct=self.RISK_PCT, min_rr=self.MIN_RR,
                    account_balance=self.broker.balance(),
                    maker_fee=self.MAKER_FEE, taker_fee=self.TAKER_FEE,
                    taker_slippage=self.TAKER_SLIPPAGE,
                    cost_budget_pct=self.COST_BUDGET_PCT,
                    min_vol_pct=self.MIN_VOL_PCT,
                    rr_pullback_mult=self.RR_PULLBACK_MULT,
                )
                if candidate is not None:
                    self.broker.open_trade(candidate, f"{asset}USDT",
                                           set_id.value, ltf_candles[-1].timestamp,
                                           maker_fee=self.MAKER_FEE,
                                           taker_fee=self.TAKER_FEE,
                                           taker_slippage=self.TAKER_SLIPPAGE,
                                           lockin_r=self.LOCKIN_R,
                                           giveback_r=self.GIVEBACK_R)
                    signals += 1
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] SIGNAL {candidate.strategy} "
                          f"{asset} {set_id.value} {candidate.action} @{candidate.entry_price:.2f} "
                          f"SL {candidate.stop_loss:.2f} TP {candidate.take_profit:.2f}")
        return signals

    # ------------------------------------------------------------------
    def run_forever(self, sleep_seconds: float = 20.0):
        print(f"[LIVE] 24/7 paper mode | assets={self.assets} "
              f"sets={[s.value for s in self.set_ids]}")
        print(f"[LIVE] balance=${self.broker.balance():,.2f} | open={len(self.broker.open_positions())}")
        while True:
            try:
                n = self.step()
                if n:
                    print(f"[LIVE] {n} new signal(s) | balance=${self.broker.balance():,.2f}")
            except Exception as exc:  # resilient: never crash the 24/7 loop
                print(f"[LIVE] cycle error: {exc}")
            time.sleep(sleep_seconds)


def main():
    parser = argparse.ArgumentParser(description="APEX 24/7 live (paper) runner")
    parser.add_argument("--source", choices=["ccxt", "warehouse"], default="warehouse")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--assets", default="BTC,ETH,SOL")
    parser.add_argument("--balance", type=float, default=1000.0)
    parser.add_argument("--sleep", type=float, default=20.0)
    args = parser.parse_args()

    provider = CcxtProvider() if args.source == "ccxt" else WarehouseProvider()
    broker = PaperBroker(starting_balance=args.balance)
    runner = LiveRunner(provider, broker, assets=args.assets.split(","))

    print("=" * 80)
    print("  APEX QUANT OS - LIVE ORCHESTRATION RUNNER")
    print(f"  Source : {args.source}")
    print(f"  Broker : PAPER (persisted to data/live_journal.db)")
    print(f"  Balance: ${broker.balance():,.2f}")
    print("=" * 80)

    if args.once:
        n = runner.step()
        print(f"[ONCE] {n} signal(s) | open={len(broker.open_positions())} | "
              f"balance=${broker.balance():,.2f}")
    else:
        runner.run_forever(sleep_seconds=args.sleep)


if __name__ == "__main__":
    main()

