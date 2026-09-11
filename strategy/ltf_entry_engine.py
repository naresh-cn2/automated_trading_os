"""
APEX Quant OS - Layer 3: LTF Entry Model & Invalidation Engine
Executes the final entry confirmation leg. Two entry models are supported in the
HTF-bias / MTF-setup direction:

  * LIQUIDITY_SWEEP : LTF wicks through a recent internal swing level then closes
                      back above/below it (sweep of resting liquidity) with a
                      reclaim / structural shift toward the bias.
  * STRUCTURE_SHIFT : LTF trend already aligned with a fresh CHoCH/BOS toward bias.

The stop loss is anchored at the LTF STRONG structural reversal point (the swept
extreme). If that point breaks, multi-timeframe alignment is considered lost and
the trade is invalidated -- exactly the "LTF SL / strong reversal point" rule.
"""

from dataclasses import dataclass
from typing import List, Optional

from market_language.market_structure import Candle
from market_language.timeframe_engine import TimeframeState

from strategy.engine_utils import average_range, latest_shift_event, swing_price


@dataclass
class LTFEntryResult:
    is_triggered: bool
    trigger_price: float
    stop_loss_price: float
    entry_model: str
    reason: str


class LTFEntryEngine:

    _SWEEP_LOOKBACK = 8
    _RECLAIM_WINDOW = 3

    @staticmethod
    def evaluate_ltf_entry(
        ltf_state: TimeframeState,
        ltf_candles: List[Candle],
        htf_bias: str,
    ) -> LTFEntryResult:
        if ltf_state is None or not ltf_candles or len(ltf_candles) < 20:
            return LTFEntryResult(False, 0.0, 0.0, "NONE", "Insufficient LTF context")

        last_close = float(ltf_candles[-1].close)
        buffer = max(average_range(ltf_candles, 14) * 0.25, last_close * 0.0005)

        if htf_bias == "BULLISH":
            levels = [
                swing_price(s) for s in ltf_state.internal_swings
                if str(getattr(s, "orientation", "")).endswith("LOW")
            ]
        else:
            levels = [
                swing_price(s) for s in ltf_state.internal_swings
                if str(getattr(s, "orientation", "")).endswith("HIGH")
            ]
        levels = [p for p in levels if p is not None]

        # --- Model 1: Liquidity Sweep ---
        sweep_info = None  # (swept_level, candle_index)
        start = max(len(ltf_candles) - 1 - LTFEntryEngine._SWEEP_LOOKBACK, 1)
        for j in range(len(ltf_candles) - 1, start - 1, -1):
            candle = ltf_candles[j]
            for lvl in levels:
                if htf_bias == "BULLISH" and candle.low < lvl and candle.close > lvl:
                    sweep_info = (lvl, j)
                    break
                if htf_bias == "BEARISH" and candle.high > lvl and candle.close < lvl:
                    sweep_info = (lvl, j)
                    break
            if sweep_info:
                break

        if sweep_info:
            swept_level, j = sweep_info
            recent = ltf_candles[max(0, j):]
            within_reclaim = len(recent) <= LTFEntryEngine._RECLAIM_WINDOW
            fresh_shift = latest_shift_event(ltf_state.recent_events, htf_bias) is not None
            trend_ok = str(ltf_state.trend_direction).upper() == htf_bias

            reclaimed = last_close > swept_level if htf_bias == "BULLISH" else last_close < swept_level
            if within_reclaim and (reclaimed or fresh_shift or trend_ok):
                if htf_bias == "BULLISH":
                    extreme = min(c.low for c in ltf_candles[-LTFEntryEngine._SWEEP_LOOKBACK:])
                    sl = extreme - buffer
                else:
                    extreme = max(c.high for c in ltf_candles[-LTFEntryEngine._SWEEP_LOOKBACK:])
                    sl = extreme + buffer

                if (htf_bias == "BULLISH" and sl < last_close) or \
                   (htf_bias == "BEARISH" and sl > last_close):
                    return LTFEntryResult(
                        True, last_close, sl, "LIQUIDITY_SWEEP",
                        reason=f"LTF sweep @{swept_level:.2f} reclaimed -> entry {last_close:.2f}, SL {sl:.2f}",
                    )

        # --- Model 2: Pure structure shift (trend aligned + fresh CHoCH/BOS) ---
        trend_ok = str(ltf_state.trend_direction).upper() == htf_bias
        shift = latest_shift_event(ltf_state.recent_events, htf_bias)
        if trend_ok and shift is not None:
            if htf_bias == "BULLISH":
                lowest = min(levels) if levels else None
                sl = (lowest - buffer) if lowest is not None else (last_close - buffer)
            else:
                highest = max(levels) if levels else None
                sl = (highest + buffer) if highest is not None else (last_close + buffer)

            if (htf_bias == "BULLISH" and sl < last_close) or \
               (htf_bias == "BEARISH" and sl > last_close):
                return LTFEntryResult(
                    True, last_close, sl, "STRUCTURE_SHIFT",
                    reason=f"LTF {htf_bias} structure shift -> entry {last_close:.2f}, SL {sl:.2f}",
                )

        return LTFEntryResult(False, 0.0, 0.0, "NONE",
                              "No LTF sweep/CHoCH entry trigger toward bias")
