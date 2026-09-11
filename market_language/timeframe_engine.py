from dataclasses import dataclass
from typing import Any, List, Tuple

from market_language.market_structure import Candle, MarketStructurePolicy, StructureCompiler
from market_language.key_levels import KeyLevelsEngine, KeyLevel
from market_language.key_zones import KeyZonesEngine, PriceZone
from market_language.market_structure.phase_engine import MarketPhase, PhaseEngine

@dataclass(frozen=True)
class TimeframeState:
    timeframe: str
    last_timestamp: int
    last_close: float
    trend_direction: str
    internal_swings: Tuple[Any, ...]
    external_swings: Tuple[Any, ...]
    recent_events: Tuple[Any, ...]
    protected_low: Any
    protected_high: Any
    weak_low: Any
    weak_high: Any
    equal_levels: Tuple[KeyLevel, ...]
    fair_value_gaps: Tuple[PriceZone, ...]
    order_blocks: Tuple[PriceZone, ...]
    phase: MarketPhase
    is_premium: bool
    is_discount: bool

class TimeframeEngine:
    def __init__(self, policy: Any = None):
        self.policy = policy or MarketStructurePolicy(fractal_left_bars=1, fractal_right_bars=1)
        self.structure_compiler = StructureCompiler(policy=self.policy)

    def evaluate(self, candles: List[Candle], timeframe: str = "1H") -> TimeframeState:
        if not candles:
            raise ValueError("Cannot evaluate empty candle list.")
        last_candle = candles[-1]
        struct_state = self.structure_compiler.compile(candles, symbol="ASSET", timeframe=timeframe)
        equal_levels = tuple(KeyLevelsEngine.detect_equal_levels(list(struct_state.internal_swings)))
        fvgs = tuple(KeyZonesEngine.detect_fair_value_gaps(candles))
        obs = tuple(KeyZonesEngine.detect_order_blocks(candles, list(struct_state.recent_events)))
        current_phase = PhaseEngine.classify_phase(
            events=list(struct_state.recent_events),
            trend=struct_state.trend,
            anchors=struct_state.anchors,
            latest_price=last_candle.close
        )
        is_premium = False
        is_discount = False
        if struct_state.dealing_range:
            is_premium = last_candle.close > struct_state.dealing_range.equilibrium_price
            is_discount = last_candle.close < struct_state.dealing_range.equilibrium_price

        return TimeframeState(
            timeframe=timeframe,
            last_timestamp=last_candle.timestamp,
            last_close=last_candle.close,
            trend_direction=struct_state.trend.direction.value,
            internal_swings=tuple(struct_state.internal_swings),
            external_swings=tuple(struct_state.external_swings),
            recent_events=tuple(struct_state.recent_events),
            protected_low=struct_state.anchors.protected_low,
            protected_high=struct_state.anchors.protected_high,
            weak_low=struct_state.anchors.weak_low,
            weak_high=struct_state.anchors.weak_high,
            equal_levels=equal_levels,
            fair_value_gaps=fvgs,
            order_blocks=obs,
            phase=current_phase,
            is_premium=is_premium,
            is_discount=is_discount
        )
