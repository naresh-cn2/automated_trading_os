"""
APEX Quant OS - Layer 3: HTF Bias, Keyzone & Objective Engine
Derives the directional bias from the most recent EXTERNAL structural event
(BOS/CHoCH), maps the institutional keyzone (OB/FVG) created by the impulse leg,
classifies the expected HTF phase into Pullback Riding (Strategy A) or
Continuation Riding (Strategy B), and projects the fixed HTF take-profit
objective (weak/strong swing) used by the risk engine.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from market_language.market_structure import Candle
from market_language.key_zones import PriceZone
from market_language.timeframe_engine import TimeframeState

from strategy.engine_utils import (
    latest_external_bias_event,
    select_keyzone,
    swing_price,
    zone_tapped,
)


class HTFExpectation(str, Enum):
    PULLBACK_EXPECTED = "PULLBACK_EXPECTED"          # Strategy A: Pullback Riding
    CONTINUATION_EXPECTED = "CONTINUATION_EXPECTED"  # Strategy B: Continuation Riding


@dataclass
class HTFBiasResult:
    bias: str
    is_valid: bool
    expectation: HTFExpectation
    keyzone: Optional[PriceZone]
    target_price: float
    invalidation_price: float
    source_event: str
    reason: str


class HTFBiasEngine:

    @staticmethod
    def evaluate_htf(htf_state: TimeframeState, htf_candles: List[Candle]) -> HTFBiasResult:
        def invalid(reason: str) -> HTFBiasResult:
            return HTFBiasResult(
                bias="NEUTRAL", is_valid=False,
                expectation=HTFExpectation.PULLBACK_EXPECTED,
                keyzone=None, target_price=0.0, invalidation_price=0.0,
                source_event="NONE", reason=reason,
            )

        if htf_state is None or not htf_candles:
            return invalid("Empty HTF context")

        # 1. Directional bias from the newest external BOS/CHoCH
        bias, source, _ = latest_external_bias_event(htf_state.recent_events)
        if bias == "NEUTRAL":
            trend = str(htf_state.trend_direction).upper()
            if trend in ("BULLISH", "BEARISH"):
                bias, source = trend, f"TREND_{trend}"
            else:
                return invalid("No external BOS/CHoCH -> HTF bias neutral")

        last_close = float(htf_candles[-1].close)
        all_zones = list(htf_state.order_blocks) + list(htf_state.fair_value_gaps)

        # 2. Institutional keyzone: newest unmitigated bias-aligned zone below/above price
        keyzone = select_keyzone(
            all_zones, htf_candles, bias, reference_price=last_close
        )

        # 3. Expected phase: has price pulled back INTO the HTF keyzone?
        expectation = HTFExpectation.PULLBACK_EXPECTED
        if keyzone is not None and zone_tapped(keyzone, htf_candles, bias):
            expectation = HTFExpectation.CONTINUATION_EXPECTED

        # 4. Fixed HTF take-profit objective (weak swing / recent external swing)
        target_price: Optional[float] = None
        if bias == "BULLISH":
            target_price = swing_price(getattr(htf_state, "weak_high", None))
            if target_price is None or target_price <= last_close:
                highs = [
                    swing_price(s) for s in htf_state.external_swings
                    if str(getattr(s, "orientation", "")).endswith("HIGH")
                ]
                available = [p for p in highs if p is not None and p > last_close]
                target_price = max(available) if available else None
            if target_price is None:
                return invalid("BULLISH bias but no HTF upside objective (weak high) mapped")
        else:
            target_price = swing_price(getattr(htf_state, "weak_low", None))
            if target_price is None or target_price >= last_close:
                lows = [
                    swing_price(s) for s in htf_state.external_swings
                    if str(getattr(s, "orientation", "")).endswith("LOW")
                ]
                available = [p for p in lows if p is not None and p < last_close]
                target_price = min(available) if available else None
            if target_price is None:
                return invalid("BEARISH bias but no HTF downside objective (weak low) mapped")

        # 5. Invalidation anchor: protected structural swing
        invalidation = (
            swing_price(htf_state.protected_low) if bias == "BULLISH"
            else swing_price(htf_state.protected_high)
        )
        if invalidation is None:
            return invalid(f"{bias} bias but no protected structural invalidation anchor")

        reason = (
            f"HTF {bias} ({source}) | {expectation.value} | "
            f"Target={target_price:.2f} Invalidation={invalidation:.2f}"
        )
        return HTFBiasResult(
            bias=bias, is_valid=True, expectation=expectation,
            keyzone=keyzone, target_price=float(target_price),
            invalidation_price=float(invalidation),
            source_event=source, reason=reason,
        )
