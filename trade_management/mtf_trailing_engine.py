"""
APEX Quant OS - Layer 4: MTF Structural Trailing & Trade Management Engine
THE core edge-preservation layer of the concept.

The fixed HTF target harvests trend extensions (take-profit), while MTF
structural trailing converts uncertain individual outcomes into high-probability
exits:

  * Trail the stop-loss behind the MTF protected structural swing (ratchet only
    in the direction of the trade, never backwards).
  * Exit at market the moment MTF structure SHIFTS against the position (CHoCH
    in the opposing direction = high probability of a deeper reversal).

Because the MTF is the timeframe whose trend is aligned with the HTF bias, any
MTF structural shift against us is treated as the strongest invalidation signal.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from market_language.market_structure import Candle
from market_language.timeframe_engine import TimeframeState

from strategy.engine_utils import has_opposing_shift, swing_price, swing_timestamp


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(str, Enum):
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    MTF_TRAIL_HIT = "MTF_TRAIL_HIT"
    MTF_CHOCH_EXIT = "MTF_CHOCH_EXIT"


@dataclass
class ManagedTrade:
    trade_id: str
    symbol: str
    set_id: str
    strategy: str
    action: str                       # "BUY" / "SELL"
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    dollar_risk: float
    entry_timestamp: int
    status: TradeStatus = TradeStatus.OPEN
    exit_price: float = 0.0
    exit_reason: Optional[ExitReason] = None
    exit_timestamp: int = 0
    r_multiple: float = 0.0
    pnl: float = 0.0
    last_mtf_event_ts: int = 0
    trail_history: List[tuple] = field(default_factory=list)

    @property
    def risk_distance(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    def mark_closed(self, exit_price: float, reason: ExitReason, timestamp: int) -> None:
        self.exit_price = exit_price
        self.exit_reason = reason
        self.exit_timestamp = timestamp
        self.status = TradeStatus.CLOSED
        risk = self.risk_distance
        if risk <= 0:
            self.r_multiple = 0.0
        elif self.action == "BUY":
            self.r_multiple = (exit_price - self.entry_price) / risk
        else:
            self.r_multiple = (self.entry_price - exit_price) / risk
        self.pnl = self.dollar_risk * self.r_multiple


class MTFTrailingEngine:

    @staticmethod
    def check_intrabar_exit(trade: ManagedTrade, candle: Candle) -> Optional[tuple]:
        """
        Checks an LTF bar for SL/TP fills (conservative: stop-loss is evaluated
        first when both are touched in the same bar). Returns (exit_price, reason)
        or None if still open.
        """
        if trade.action == "BUY":
            if candle.low <= trade.stop_loss:
                return trade.stop_loss, ExitReason.SL_HIT
            if candle.high >= trade.take_profit:
                return trade.take_profit, ExitReason.TP_HIT
        else:
            if candle.high >= trade.stop_loss:
                return trade.stop_loss, ExitReason.SL_HIT
            if candle.low <= trade.take_profit:
                return trade.take_profit, ExitReason.TP_HIT
        return None

    @staticmethod
    def on_mtf_close(trade: ManagedTrade, mtf_state: TimeframeState) -> Optional[tuple]:
        """
        Called each time a NEW MTF bar closes while the trade is open.

        1. If MTF structure shifted AGAINST the position -> signal market exit.
        2. Otherwise ratchet the trailing stop behind MTF protected structure.

        Returns (exit_market, ExitReason.MTF_CHOCH_EXIT) or None.
        """
        if mtf_state is None:
            return None

        direction = "BUY" if trade.action == "BUY" else "SELL"
        bias = "BULLISH" if trade.action == "BUY" else "BEARISH"

        # 1. Opposing MTF structure shift = exit signal
        if has_opposing_shift(mtf_state.recent_events, bias, since_timestamp=trade.last_mtf_event_ts):
            return "MARKET", ExitReason.MTF_CHOCH_EXIT

        # update last processed event timestamp
        for evt in mtf_state.recent_events:
            ts = int(getattr(evt, "trigger_timestamp", 0))
            if ts > trade.last_mtf_event_ts:
                trade.last_mtf_event_ts = ts

        # 2. Ratchet trailing stop behind MTF protected structure
        anchor = (
            swing_price(mtf_state.protected_low) if trade.action == "BUY"
            else swing_price(mtf_state.protected_high)
        )
        if anchor is None:
            ext = list(mtf_state.external_swings)
            if ext:
                anchor = swing_price(ext[-1])
        if anchor is None:
            return None

        last_close = float(getattr(mtf_state, "last_close", 0.0))
        if trade.action == "BUY" and anchor > trade.stop_loss and anchor < last_close:
            trade.trail_history.append((mtf_state.last_timestamp, round(anchor, 6)))
            trade.stop_loss = anchor
        elif trade.action == "SELL" and anchor < trade.stop_loss and anchor > last_close:
            trade.trail_history.append((mtf_state.last_timestamp, round(anchor, 6)))
            trade.stop_loss = anchor

        return None
