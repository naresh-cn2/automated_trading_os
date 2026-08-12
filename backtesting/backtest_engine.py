"""
APEX Quant OS - Layer 5: Multi-Timeframe Walk-Forward Backtest Engine
Replays the warehouse candle history bar-by-bar across the HTF/MTF/LTF stack,
executes the Strategy A (Pullback Riding) & Strategy B (Continuation Riding)
pipeline through the StrategyOrchestrator, and manages every position with the
MTF structural trailing engine.

Risk model: risk a fixed fraction (default 1%) of the current account per trade;
each candidate must satisfy the minimum 1:4 reward-to-risk firewall set by the
risk engine. Trades compound into the running account balance.
"""

import bisect
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from market_language.market_structure import Candle
from market_language.timeframe_engine import TimeframeEngine

from strategy.strategy_orchestrator import StrategyOrchestrator
from trade_management.mtf_trailing_engine import (
    ExitReason,
    MTFTrailingEngine,
    ManagedTrade,
)


# ---------------------------------------------------------------------------
# Warehouse loader (reads candle history for one symbol + timeframe)
# ---------------------------------------------------------------------------

class WarehouseLoader:
    """Loads candles for a symbol/timeframe out of the shared price warehouse."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "price_warehouse.db")
        self.db_path = db_path

    def load(self, symbol: str, timeframe: str) -> List[Candle]:
        sym = symbol.replace("/", "")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT timestamp, open, high, low, close, volume FROM crypto_candles "
                "WHERE symbol = ? AND UPPER(timeframe) = ? ORDER BY timestamp ASC",
                (sym, str(timeframe).upper()),
            )
            rows = cursor.fetchall()
        return [
            Candle(timestamp=int(r[0]), open=float(r[1]), high=float(r[2]),
                   low=float(r[3]), close=float(r[4]),
                   volume=float(r[5]) if r[5] is not None else 0.0)
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Backtest configuration & result
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    initial_balance: float = 1000.0
    risk_pct: float = 0.01
    min_rr: float = 4.0
    ltf_warmup: int = 160
    htf_lookback: int = 120
    mtf_lookback: int = 160
    ltf_lookback: int = 160


@dataclass
class ComboResult:
    symbol: str
    set_id: str
    htf: str
    mtf: str
    ltf: str
    final_balance: float
    initial_balance: float = 1000.0
    max_drawdown_pct: float = 0.0
    trades: List[ManagedTrade] = field(default_factory=list)

    @property
    def stats(self) -> Dict[str, float]:
        trades = self.trades
        n = len(trades)
        if n == 0:
            return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                    "avg_r": 0.0, "tp_hits": 0, "trail_exits": 0, "sl_hits": 0,
                    "return_pct": 0.0, "max_dd_pct": 0.0, "net_pnl": 0.0,
                    "expectancy_r": 0.0}
        tp = sum(1 for t in trades if t.exit_reason == ExitReason.TP_HIT)
        trail = sum(1 for t in trades if t.exit_reason in
                    (ExitReason.MTF_TRAIL_HIT, ExitReason.MTF_CHOCH_EXIT))
        sl = sum(1 for t in trades if t.exit_reason == ExitReason.SL_HIT)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        pf = (gross_win / gross_loss) if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)
        avg_r = sum(t.r_multiple for t in trades) / n
        base = self.initial_balance if self.initial_balance else 1.0
        return {
            "trades": n,
            "win_rate": (len(wins) / n) * 100.0,
            "profit_factor": pf,
            "avg_r": avg_r,
            "tp_hits": tp,
            "trail_exits": trail,
            "sl_hits": sl,
            "return_pct": ((self.final_balance / base) - 1.0) * 100.0,
            "max_dd_pct": self.max_drawdown_pct,
            "net_pnl": self.final_balance - self.initial_balance,
            "expectancy_r": avg_r,
        }


class BacktestEngine:

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.loader = WarehouseLoader()
        self.tf_engine = TimeframeEngine()

    # ------------------------------------------------------------------
    def run(self, symbol: str, set_id: str,
            htf_tf: str, mtf_tf: str, ltf_tf: str) -> ComboResult:
        cfg = self.config
        c_htf = self.loader.load(symbol, htf_tf)
        c_mtf = self.loader.load(symbol, mtf_tf)
        c_ltf = self.loader.load(symbol, ltf_tf)

        if not c_htf or not c_mtf or not c_ltf:
            return ComboResult(
                symbol=symbol, set_id=set_id, htf=htf_tf, mtf=mtf_tf, ltf=ltf_tf,
                final_balance=cfg.initial_balance, initial_balance=cfg.initial_balance,
                trades=[],
            )

        htf_ts = [c.timestamp for c in c_htf]
        mtf_ts = [c.timestamp for c in c_mtf]

        balance = cfg.initial_balance
        active: Optional[ManagedTrade] = None
        trades: List[ManagedTrade] = []
        last_mtf_idx = 0
        equity_points = [cfg.initial_balance]

        for i in range(cfg.ltf_warmup, len(c_ltf)):
            bar = c_ltf[i]
            ts = bar.timestamp

            # ---- Manage any open position ----
            if active is not None:
                # a) Intrabar SL / TP check on this LTF bar
                hit = MTFTrailingEngine.check_intrabar_exit(active, bar)
                if hit is not None:
                    exit_price, reason = hit
                    active.mark_closed(exit_price, reason, ts)
                    balance += active.pnl
                    equity_points.append(balance)
                    trades.append(active)
                    active = None

                # b) New MTF bar closed -> MTF structural trailing / CHoCH exit
                else:
                    idx_mtf = bisect.bisect_right(mtf_ts, ts)
                    if idx_mtf > last_mtf_idx and idx_mtf >= 15:
                        mtf_slice = c_mtf[max(0, idx_mtf - cfg.mtf_lookback):idx_mtf]
                        try:
                            mtf_state = self.tf_engine.evaluate(mtf_slice, timeframe=mtf_tf)
                        except Exception:
                            mtf_state = None
                        exit_sig = MTFTrailingEngine.on_mtf_close(active, mtf_state) if mtf_state else None
                        if exit_sig is not None:
                            active.mark_closed(bar.close, exit_sig[1], ts)
                            balance += active.pnl
                            equity_points.append(balance)
                            trades.append(active)
                            active = None
                        last_mtf_idx = idx_mtf

            # ---- New entry (only when flat) ----
            if active is None:
                idx_mtf = bisect.bisect_right(mtf_ts, ts)
                idx_htf = bisect.bisect_right(htf_ts, ts)
                if idx_mtf < 15 or idx_htf < 10:
                    continue

                mtf_slice = c_mtf[max(0, idx_mtf - cfg.mtf_lookback):idx_mtf]
                htf_slice = c_htf[max(0, idx_htf - cfg.htf_lookback):idx_htf]
                ltf_slice = c_ltf[max(0, i - cfg.ltf_lookback):i + 1]

                try:
                    mtf_state = self.tf_engine.evaluate(mtf_slice, timeframe=mtf_tf)
                    htf_state = self.tf_engine.evaluate(htf_slice, timeframe=htf_tf)
                    ltf_state = self.tf_engine.evaluate(ltf_slice, timeframe=ltf_tf)
                except Exception:
                    continue

                candidate = StrategyOrchestrator.evaluate_bar(
                    set_id=set_id,
                    htf_state=htf_state, mtf_state=mtf_state, ltf_state=ltf_state,
                    htf_candles=htf_slice, mtf_candles=mtf_slice, ltf_candles=ltf_slice,
                    risk_pct=cfg.risk_pct, min_rr=cfg.min_rr,
                    account_balance=balance,
                )
                if candidate is not None:
                    active = ManagedTrade(
                        trade_id=candidate.trade_id,
                        symbol=symbol, set_id=set_id, strategy=candidate.strategy,
                        action=candidate.action,
                        entry_price=candidate.entry_price,
                        stop_loss=candidate.stop_loss,
                        take_profit=candidate.take_profit,
                        position_size=candidate.position_size,
                        dollar_risk=candidate.dollar_risk,
                        entry_timestamp=ts,
                    )
                    last_mtf_idx = idx_mtf

        # close any still-open position at last bar
        if active is not None:
            active.mark_closed(c_ltf[-1].close, ExitReason.MTF_CHOCH_EXIT, c_ltf[-1].timestamp)
            balance += active.pnl
            equity_points.append(balance)
            trades.append(active)

        # ---- drawdown from equity curve ----
        peak = -1e18
        max_dd = 0.0
        for eq in equity_points:
            peak = max(peak, eq)
            if peak > 0:
                max_dd = max(max_dd, (peak - eq) / peak * 100.0)

        if balance <= 0:
            balance = 0.0
        return ComboResult(
            symbol=symbol, set_id=set_id, htf=htf_tf, mtf=mtf_tf, ltf=ltf_tf,
            final_balance=balance, initial_balance=cfg.initial_balance,
            trades=trades, max_drawdown_pct=max_dd,
        )

