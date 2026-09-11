"""
APEX Product 01 — Engine 3: Liquidity Intelligence Engine

RESPONSIBILITY
--------------
Consumes confirmed SequenceSwings from Engine 2 and sequential Candle history.

Produces ONLY:
    - Equal Highs (EQH) & Equal Lows (EQL) liquidity pools (0.05% relative tolerance)
    - Buy-Side Liquidity (BSL) & Sell-Side Liquidity (SSL) pool anchors
    - Liquidity Sweeps (Wick pierces pool boundary, candle body closes inside)
    - Inducement Events (Internal liquidity swept in direction of trade before zone interaction)
    - Stateful pool lifecycle tracking (ACTIVE, SWEPT, CONSUMED)

STRICT BOUNDARY
---------------
This engine does NOT know about:
    - Order Blocks / Fair Value Gaps (Engine 4)
    - Market Phase (Engine 5)
    - Buy/Sell Signals or Strategy Logic
    - Risk / Position Sizing / Stop Loss
    - Execution Adapters / Broker APIs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set, Tuple

from market_intelligence.raw_swing_engine import Candle, SwingType
from market_intelligence.structure_builder_engine import SequenceSwing, SwingScope, TrendDirection


class LiquidityPoolType(Enum):
    EQH = "EQH"
    EQL = "EQL"
    BSL = "BSL"
    SSL = "SSL"


class PoolStatus(Enum):
    ACTIVE = "ACTIVE"
    SWEPT = "SWEPT"
    CONSUMED = "CONSUMED"


class LiquidityEventType(Enum):
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    INDUCEMENT = "INDUCEMENT"


@dataclass(frozen=True)
class LiquidityPool:
    pool_id: str
    pool_type: LiquidityPoolType
    price_level: float
    high_boundary: float
    low_boundary: float
    swings: List[SequenceSwing]
    creation_timestamp: int
    status: PoolStatus = PoolStatus.ACTIVE


@dataclass(frozen=True)
class LiquidityEvent:
    timestamp: int
    event_type: LiquidityEventType
    pool_id: str
    pool_type: LiquidityPoolType
    price_level: float
    direction: str
    candle_index: int
    swept_by_wick: bool = True
    body_closed_inside: bool = True


@dataclass
class LiquidityState:
    active_pools: List[LiquidityPool]
    swept_pools: List[LiquidityPool]
    events: List[LiquidityEvent]


class LiquidityEngine:
    """
    Deterministic, stateful Liquidity Intelligence Engine.
    Tracks liquidity pool lifecycles and identifies sweep/inducement events.
    """

    def __init__(self, eq_tolerance_pct: float = 0.0005) -> None:
        if eq_tolerance_pct < 0:
            raise ValueError("eq_tolerance_pct must be >= 0")
        self.eq_tolerance_pct = eq_tolerance_pct
        self._emitted_event_keys: Set[Tuple] = set()

    def reset(self) -> None:
        """Reset stateful event tracking memory."""
        self._emitted_event_keys.clear()

    def process(
        self,
        swings: List[SequenceSwing],
        candles: List[Candle],
        external_trend: TrendDirection = TrendDirection.NEUTRAL
    ) -> LiquidityState:
        """
        Main Engine 3 processing loop.
        Constructs liquidity pools and evaluates candle streams for sweep events.
        """
        if not swings:
            return LiquidityState(active_pools=[], swept_pools=[], events=[])

        # 1. Detect EQH / EQL Pools
        eq_pools = self._detect_eq_pools(swings)

        # 2. Detect BSL / SSL Structural Pools
        structural_pools = self._detect_structural_pools(swings)

        all_pools = eq_pools + structural_pools

        # 3. Evaluate Sweeps and Inducements across Candle Stream
        active_pools, swept_pools, events = self._evaluate_pool_sweeps(
            all_pools=all_pools,
            candles=candles,
            external_trend=external_trend
        )

        return LiquidityState(
            active_pools=active_pools,
            swept_pools=swept_pools,
            events=events
        )

    def _detect_eq_pools(self, swings: List[SequenceSwing]) -> List[LiquidityPool]:
        pools: List[LiquidityPool] = []
        highs = [s for s in swings if s.raw_swing.swing_type == SwingType.HIGH]
        lows = [s for s in swings if s.raw_swing.swing_type == SwingType.LOW]

        # Scan Highs for EQH
        for i in range(len(highs)):
            anchor = highs[i]
            cluster = [anchor]
            for j in range(i + 1, len(highs)):
                cand = highs[j]
                diff = abs(cand.raw_swing.price - anchor.raw_swing.price) / anchor.raw_swing.price
                if diff <= self.eq_tolerance_pct:
                    cluster.append(cand)

            if len(cluster) >= 2:
                avg_price = sum(s.raw_swing.price for s in cluster) / len(cluster)
                pool_id = f"EQH_{cluster[0].raw_swing.swing_id}_{cluster[-1].raw_swing.swing_id}"
                pools.append(LiquidityPool(
                    pool_id=pool_id,
                    pool_type=LiquidityPoolType.EQH,
                    price_level=avg_price,
                    high_boundary=max(s.raw_swing.price for s in cluster),
                    low_boundary=min(s.raw_swing.price for s in cluster),
                    swings=cluster,
                    creation_timestamp=cluster[-1].raw_swing.timestamp
                ))

        # Scan Lows for EQL
        for i in range(len(lows)):
            anchor = lows[i]
            cluster = [anchor]
            for j in range(i + 1, len(lows)):
                cand = lows[j]
                diff = abs(cand.raw_swing.price - anchor.raw_swing.price) / anchor.raw_swing.price
                if diff <= self.eq_tolerance_pct:
                    cluster.append(cand)

            if len(cluster) >= 2:
                avg_price = sum(s.raw_swing.price for s in cluster) / len(cluster)
                pool_id = f"EQL_{cluster[0].raw_swing.swing_id}_{cluster[-1].raw_swing.swing_id}"
                pools.append(LiquidityPool(
                    pool_id=pool_id,
                    pool_type=LiquidityPoolType.EQL,
                    price_level=avg_price,
                    high_boundary=max(s.raw_swing.price for s in cluster),
                    low_boundary=min(s.raw_swing.price for s in cluster),
                    swings=cluster,
                    creation_timestamp=cluster[-1].raw_swing.timestamp
                ))

        return pools

    def _detect_structural_pools(self, swings: List[SequenceSwing]) -> List[LiquidityPool]:
        pools: List[LiquidityPool] = []
        for s in swings:
            if s.scope == SwingScope.EXTERNAL:
                p_type = LiquidityPoolType.BSL if s.raw_swing.swing_type == SwingType.HIGH else LiquidityPoolType.SSL
                pool_id = f"{p_type.value}_{s.raw_swing.swing_id}"
                pools.append(LiquidityPool(
                    pool_id=pool_id,
                    pool_type=p_type,
                    price_level=s.raw_swing.price,
                    high_boundary=s.raw_swing.price,
                    low_boundary=s.raw_swing.price,
                    swings=[s],
                    creation_timestamp=s.raw_swing.timestamp
                ))
        return pools

    def _evaluate_pool_sweeps(
        self,
        all_pools: List[LiquidityPool],
        candles: List[Candle],
        external_trend: TrendDirection
    ) -> Tuple[List[LiquidityPool], List[LiquidityPool], List[LiquidityEvent]]:
        if not candles:
            return all_pools, [], []

        events: List[LiquidityEvent] = []
        active_pools: List[LiquidityPool] = []
        swept_pools: List[LiquidityPool] = []

        for pool in all_pools:
            latest_swing = max(pool.swings, key=lambda s: s.raw_swing.confirmation_index)
            start_index = latest_swing.raw_swing.confirmation_index

            is_swept = False
            for idx in range(start_index, len(candles)):
                candle = candles[idx]

                # High-Side Liquidity Sweep (BSL / EQH)
                if pool.pool_type in (LiquidityPoolType.BSL, LiquidityPoolType.EQH):
                    if candle.high > pool.high_boundary and candle.close <= pool.high_boundary:
                        is_swept = True
                        event_type = (
                            LiquidityEventType.INDUCEMENT
                            if external_trend == TrendDirection.BEARISH and any(s.scope == SwingScope.INTERNAL for s in pool.swings)
                            else LiquidityEventType.LIQUIDITY_SWEEP
                        )
                        self._emit_event(
                            events=events,
                            candle=candle,
                            pool=pool,
                            event_type=event_type,
                            direction="BEARISH_SWEEP",
                            candle_index=idx
                        )
                        break
                    elif candle.close > pool.high_boundary:
                        # Body closed above pool -> Pool Consumed / Broken (Not a sweep)
                        break

                # Low-Side Liquidity Sweep (SSL / EQL)
                elif pool.pool_type in (LiquidityPoolType.SSL, LiquidityPoolType.EQL):
                    if candle.low < pool.low_boundary and candle.close >= pool.low_boundary:
                        is_swept = True
                        event_type = (
                            LiquidityEventType.INDUCEMENT
                            if external_trend == TrendDirection.BULLISH and any(s.scope == SwingScope.INTERNAL for s in pool.swings)
                            else LiquidityEventType.LIQUIDITY_SWEEP
                        )
                        self._emit_event(
                            events=events,
                            candle=candle,
                            pool=pool,
                            event_type=event_type,
                            direction="BULLISH_SWEEP",
                            candle_index=idx
                        )
                        break
                    elif candle.close < pool.low_boundary:
                        # Body closed below pool -> Pool Consumed / Broken (Not a sweep)
                        break

            if is_swept:
                swept_pools.append(LiquidityPool(
                    pool_id=pool.pool_id,
                    pool_type=pool.pool_type,
                    price_level=pool.price_level,
                    high_boundary=pool.high_boundary,
                    low_boundary=pool.low_boundary,
                    swings=pool.swings,
                    creation_timestamp=pool.creation_timestamp,
                    status=PoolStatus.SWEPT
                ))
            else:
                active_pools.append(pool)

        return active_pools, swept_pools, events

    def _emit_event(
        self,
        events: List[LiquidityEvent],
        candle: Candle,
        pool: LiquidityPool,
        event_type: LiquidityEventType,
        direction: str,
        candle_index: int
    ) -> None:
        event_key = (event_type.value, pool.pool_id, candle_index)
        if event_key in self._emitted_event_keys:
            return

        self._emitted_event_keys.add(event_key)
        events.append(LiquidityEvent(
            timestamp=candle.timestamp,
            event_type=event_type,
            pool_id=pool.pool_id,
            pool_type=pool.pool_type,
            price_level=pool.price_level,
            direction=direction,
            candle_index=candle_index,
            swept_by_wick=True,
            body_closed_inside=True
        ))
