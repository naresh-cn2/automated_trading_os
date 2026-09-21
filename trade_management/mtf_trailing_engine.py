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
    maker_fee: float = 0.0002     # post-only limit fills: entry & TP (0.02%)
    taker_fee: float = 0.0005     # market fills: SL & trailing exits (0.05%)
    entry_slippage: float = 0.0   # limit entry -> typically zero (post-only)
    taker_slippage: float = 0.0003  # adverse slippage on market exits (3bps)
    lockin_r: float = 0.5         # start profit-lock after +0.5R favorable excursion
    giveback_r: float = 0.25      # allow at most 0.25R giveback from the peak before locking
    entry_risk_distance: float = 0.0  # risk at entry (unchanged by the ratchet)
    initial_stop_loss: float = 0.0  # immutable entry stop (audit trail; stop_loss mutates)
    max_favorable_price: float = 0.0  # peak favorable excursion price
    status: TradeStatus = TradeStatus.OPEN
    exit_price: float = 0.0
    exit_reason: Optional[ExitReason] = None
    exit_timestamp: int = 0
    r_multiple: float = 0.0
    pnl: float = 0.0
    last_mtf_event_ts: int = 0
    trail_history: List[tuple] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Freeze the entry stop for auditability; `stop_loss` is mutated by
        # the MTF ratchet / profit-lock. 0.0 means "not yet frozen" (legacy
        # rows) -> fall back to the current stop.
        if not self.initial_stop_loss:
            object.__setattr__(self, "initial_stop_loss", self.stop_loss)


    @property
    def risk_distance(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    def mark_closed(self, exit_price: float, reason: ExitReason, timestamp: int) -> None:
        self.exit_price = exit_price
        self.exit_reason = reason
        self.exit_timestamp = timestamp
        self.status = TradeStatus.CLOSED

        # Institutional execution model:
        #   - Entry and TP are RESTING LIMIT orders at the keyzone -> maker fee, no slippage.
        #   - SL and the MTF trailing / CHoCH exits are MARKET orders -> taker fee + adverse slip.
        is_limit_exit = reason == ExitReason.TP_HIT
        exit_fee = self.maker_fee if is_limit_exit else self.taker_fee
        exit_slip = 0.0 if is_limit_exit else self.taker_slippage

        if self.action == "BUY":
            eff_entry = self.entry_price * (1.0 + self.entry_slippage)
            eff_exit = exit_price * (1.0 - exit_slip)
            gross = (eff_exit - eff_entry) * self.position_size
        else:
            eff_entry = self.entry_price * (1.0 - self.entry_slippage)
            eff_exit = exit_price * (1.0 + exit_slip)
            gross = (eff_entry - eff_exit) * self.position_size

        # Fees charged on the notional of each executed leg
        fees = (self.maker_fee * eff_entry + exit_fee * eff_exit) * self.position_size
        self.pnl = gross - fees
        self.r_multiple = (self.pnl / self.dollar_risk) if self.dollar_risk > 0 else 0.0


class MTFTrailingEngine:

    @staticmethod
    def check_intrabar_exit(trade: ManagedTrade, candle: Candle) -> Optional[tuple]:
        """
        Checks an LTF bar for SL/TP fills (conservative: stop-loss is evaluated
        first when both are touched in the same bar). Returns (exit_price, reason)
        or None if still open.

        Also applies the profit-lock ratchet: once the trade reaches +lockin_r
        favorable excursion, the stop is raised (lowered for shorts) so the worst
        case is a small giveback_r giveback from the peak instead of a full -1R loss.
        """
        base_risk = trade.entry_risk_distance if trade.entry_risk_distance > 0 else trade.risk_distance

        def _stop_reason(t: ManagedTrade) -> ExitReason:
            """Profit-locked / structurally-trailed stops are wins, not raw SLs.

            Once the stop has ratcheted past breakeven (into profit), hitting it
            is a successful structural-trail exit, so report MTF_TRAIL_HIT
            instead of SL_HIT. True initial-stop losses stay SL_HIT.
            """
            if t.action == "BUY" and t.stop_loss > t.entry_price:
                return ExitReason.MTF_TRAIL_HIT
            if t.action == "SELL" and 0 < t.stop_loss < t.entry_price:
                return ExitReason.MTF_TRAIL_HIT
            return ExitReason.SL_HIT

        if trade.action == "BUY":
            # track peak favorable excursion & apply profit-lock
            trade.max_favorable_price = max(trade.max_favorable_price, candle.high)
            if base_risk > 0 and trade.lockin_r > 0:
                fav_r = (trade.max_favorable_price - trade.entry_price) / base_risk
                if fav_r >= trade.lockin_r:
                    floor_stop = trade.max_favorable_price - trade.giveback_r * base_risk
                    if floor_stop > trade.stop_loss:
                        trade.stop_loss = floor_stop

            if candle.low <= trade.stop_loss:
                return trade.stop_loss, _stop_reason(trade)
            if candle.high >= trade.take_profit:
                return trade.take_profit, ExitReason.TP_HIT
        else:
            trade.max_favorable_price = (
                min(trade.max_favorable_price, candle.low)
                if trade.max_favorable_price > 0 else candle.low
            )
            if base_risk > 0 and trade.lockin_r > 0:
                fav_r = (trade.entry_price - trade.max_favorable_price) / base_risk
                if fav_r >= trade.lockin_r:
                    floor_stop = trade.max_favorable_price + trade.giveback_r * base_risk
                    if floor_stop < trade.stop_loss:
                        trade.stop_loss = floor_stop

            if candle.high >= trade.stop_loss:
                return trade.stop_loss, _stop_reason(trade)
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
