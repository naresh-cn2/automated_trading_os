"""
APEX Quant OS - Layer 3: MTF Setup, Realignment & Structural Anchor Engine
Confirms the medium timeframe has SHIFTED its structure back into the HTF bias
direction (CHoCH/BOS realignment after its own counter-trend pullback), exposes
the MTF keyzone (OB/FVG) for the entry leg, and surfaces the protected structural
anchor used by the MTF trailing engine. This is the alignment gate that separates
"trend is still against us" from "setup is ready".
"""

from dataclasses import dataclass
from typing import List, Optional

from market_language.market_structure import Candle
from market_language.key_zones import PriceZone
from market_language.timeframe_engine import TimeframeState

from strategy.engine_utils import latest_shift_event, select_keyzone, swing_price


@dataclass
class MTFSetupResult:
    is_aligned: bool
    mtf_trend: str
    structure_shift: bool
    keyzone: Optional[PriceZone]
    trailing_anchor: float
    reason: str


class MTFSetupEngine:

    @staticmethod
    def evaluate_mtf_setup(
        mtf_state: TimeframeState,
        mtf_candles: List[Candle],
        htf_bias: str,
    ) -> MTFSetupResult:
        if mtf_state is None or not mtf_candles:
            return MTFSetupResult(False, "NEUTRAL", False, None, 0.0, "Empty MTF context")

        mtf_trend = str(mtf_state.trend_direction).upper()
        last_close = float(mtf_candles[-1].close)

        # 1. MTF trend must align with HTF bias
        trend_aligned = mtf_trend == htf_bias

        # 2. MTF structure shift toward bias (CHoCH/BOS) = realignment confirmation
        shift_evt = None
        if trend_aligned:
            shift_evt = latest_shift_event(mtf_state.recent_events, htf_bias)
        structure_shift = shift_evt is not None

        # 3. MTF keyzone (entry leg origin)
        keyzone = None
        if structure_shift:
            keyzone = select_keyzone(
                list(mtf_state.order_blocks) + list(mtf_state.fair_value_gaps),
                mtf_candles, htf_bias, reference_price=last_close,
            )

        # 4. Trailing anchor: MTF protected structural swing
        trailing_anchor = (
            swing_price(mtf_state.protected_low) if htf_bias == "BULLISH"
            else swing_price(mtf_state.protected_high)
        )
        if trailing_anchor is None:
            ext = list(mtf_state.external_swings)
            if ext:
                trailing_anchor = swing_price(ext[-1])
        if trailing_anchor is None:
            trailing_anchor = 0.0

        is_aligned = trend_aligned and structure_shift
        if is_aligned:
            reason = (
                f"MTF setup ready ({mtf_trend}) shift={getattr(shift_evt, 'event_type', '')} "
                f"anchor={trailing_anchor:.2f}"
            )
        elif trend_aligned and not structure_shift:
            reason = f"MTF trend {mtf_trend} aligned but no fresh structure shift toward bias"
        else:
            reason = f"MTF rejected: MTF({mtf_trend}) != HTF({htf_bias})"

        return MTFSetupResult(
            is_aligned=is_aligned, mtf_trend=mtf_trend,
            structure_shift=structure_shift,
            keyzone=keyzone, trailing_anchor=float(trailing_anchor or 0.0),
            reason=reason,
        )
