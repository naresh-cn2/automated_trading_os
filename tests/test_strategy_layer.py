"""
APEX Quant OS - Unit Tests: HTF Bias / MTF Setup / LTF Entry / MTF Trailing /
Orchestrator pipeline. Uses fabricated, deterministic structural states so the
tests are independent of market data.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from market_language.market_structure import Candle
from market_language.market_structure.models import (
    EventType, PricePoint, StructuralEvent, Swing, SwingOrientation,
)
from market_language.key_zones import PriceZone, ZoneType
from market_language.timeframe_engine import TimeframeState
from market_language.market_structure.phase_engine import MarketPhase

from strategy.htf_bias_engine import HTFBiasEngine, HTFExpectation
from strategy.mtf_setup_engine import MTFSetupEngine
from strategy.ltf_entry_engine import LTFEntryEngine
from trade_management.mtf_trailing_engine import (
    ExitReason, MTFTrailingEngine, ManagedTrade,
)
from strategy.strategy_orchestrator import StrategyOrchestrator


def _swing(orientation, price, ts, is_strong=False):
    return Swing(orientation=orientation, price_point=PricePoint(ts, price),
                 is_strong=is_strong)


def _state(bias="BULLISH", events=None, external=None, internal=None,
           protected_low=None, protected_high=None, weak_low=None, weak_high=None,
           obs=None, fvgs=None, close=100.0, trend=None):
    return TimeframeState(
        timeframe="1H", last_timestamp=2000, last_close=close,
        trend_direction=(trend or bias),
        internal_swings=tuple(internal or ()),
        external_swings=tuple(external or ()),
        recent_events=tuple(events or ()),
        protected_low=protected_low, protected_high=protected_high,
        weak_low=weak_low, weak_high=weak_high,
        equal_levels=(), fair_value_gaps=tuple(fvgs or ()),
        order_blocks=tuple(obs or ()), phase=MarketPhase.EXPANSION,
        is_premium=False, is_discount=True,
    )


def test_htf_bias_engine():
    obs = [PriceZone(ZoneType.BULLISH_OB, high_price=104.0, low_price=102.0,
                     creation_timestamp=900)]
    st = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_BOS_BULLISH,
                                trigger_timestamp=1000, trigger_price=105.0)],
        external=[
            _swing(SwingOrientation.HIGH, 110.0, 1000),
            _swing(SwingOrientation.LOW, 98.0, 950),
        ],
        protected_low=_swing(SwingOrientation.LOW, 95.0, 850),
        weak_high=_swing(SwingOrientation.HIGH, 118.0, 1010),
        obs=obs, close=106.0,
    )
    candles = [
        Candle(900, 102, 104, 101, 103, 100),
        Candle(901, 104, 106, 104.5, 105, 100),
        Candle(950, 105, 107, 104.5, 106, 100),
    ]
    res = HTFBiasEngine.evaluate_htf(st, candles)
    assert res.is_valid, res.reason
    assert res.bias == "BULLISH"
    assert res.target_price == 118.0
    assert res.invalidation_price == 95.0
    assert res.expectation == HTFExpectation.PULLBACK_EXPECTED
    print("  OK test_htf_bias_engine")


def test_mtf_setup_engine():
    st = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_CHOCH_BULLISH,
                                trigger_timestamp=1500, trigger_price=104.0)],
        protected_low=_swing(SwingOrientation.LOW, 96.0, 800),
        obs=[PriceZone(ZoneType.BULLISH_OB, high_price=103.0, low_price=101.0,
                       creation_timestamp=1400)],
        close=105.0,
    )
    candles = [
        Candle(1400, 100, 103, 101, 102, 100),
        Candle(1500, 102, 106, 101.5, 105, 200),
        Candle(1600, 105, 107, 104.5, 106, 100),
    ]
    res = MTFSetupEngine.evaluate_mtf_setup(st, candles, "BULLISH")
    assert res.is_aligned, res.reason
    assert res.structure_shift is True
    assert res.trailing_anchor == 96.0
    print("  OK test_mtf_setup_engine")


def test_ltf_entry_liquidity_sweep():
    levels = [_swing(SwingOrientation.LOW, 100.0, 1000)]
    candles = []
    for i in range(18):
        candles.append(Candle(1000 + i * 60, 101 + i * 0.001, 102 + i * 0.001,
                              100.4, 101.8 + i * 0.001, 100))
    candles.append(Candle(2000, 101.0, 102.0, 99.5, 101.5, 150))  # sweep below 100
    candles.append(Candle(2060, 101.5, 103.0, 101.0, 102.5, 150))
    st = _state(bias="BULLISH",
                events=[StructuralEvent(event_type=EventType.EXTERNAL_CHOCH_BULLISH,
                                        trigger_timestamp=2060, trigger_price=102.0)],
                internal=levels, close=102.5, trend="BULLISH")
    res = LTFEntryEngine.evaluate_ltf_entry(st, candles, "BULLISH")
    assert res.is_triggered, res.reason
    assert res.entry_model == "LIQUIDITY_SWEEP"
    assert res.stop_loss_price < res.trigger_price, res.reason
    print("  OK test_ltf_entry_liquidity_sweep")


def test_mtf_trailing():
    trade = ManagedTrade(
        trade_id="t1", symbol="BTCUSDT", set_id="SET_3_SWING",
        strategy="A_PULLBACK_RIDING", action="BUY",
        entry_price=100.0, stop_loss=98.0, take_profit=130.0,
        position_size=1.0, dollar_risk=10.0, entry_timestamp=0,
        lockin_r=0.5, giveback_r=0.25, entry_risk_distance=2.0,
        initial_stop_loss=98.0, max_favorable_price=100.0,
    )
    assert trade.initial_stop_loss == 98.0
    assert trade.lockin_r == 0.5 and trade.giveback_r == 0.25
    # ratchet: protected_low above current SL trails it up
    st = _state(protected_low=_swing(SwingOrientation.LOW, 101.0, 600), close=104.0)
    sig = MTFTrailingEngine.on_mtf_close(trade, st)
    assert sig is None
    assert trade.stop_loss == 101.0, trade.stop_loss

    # opposing CHoCH -> market exit signal
    st2 = _state(bias="BEARISH",
                 events=[StructuralEvent(event_type=EventType.EXTERNAL_CHOCH_BEARISH,
                                         trigger_timestamp=9999, trigger_price=100.0)],
                 close=99.0)
    sig2 = MTFTrailingEngine.on_mtf_close(trade, st2)
    assert sig2 is not None
    assert sig2[1] == ExitReason.MTF_CHOCH_EXIT
    print("  OK test_mtf_trailing")


def test_trailing_stop_classification():
    """Profit-locked stops must report MTF_TRAIL_HIT, raw stops stay SL_HIT."""
    from market_language.market_structure import Candle as _C
    t = ManagedTrade(
        trade_id="t2", symbol="BTCUSDT", set_id="SET_3_SWING",
        strategy="B_CONTINUATION_RIDING", action="BUY",
        entry_price=100.0, stop_loss=98.0, take_profit=130.0,
        position_size=1.0, dollar_risk=10.0, entry_timestamp=0,
        lockin_r=0.5, giveback_r=0.25, entry_risk_distance=2.0,
        initial_stop_loss=98.0, max_favorable_price=100.0,
    )
    # raw stop, no excursion -> SL_HIT
    hit = MTFTrailingEngine.check_intrabar_exit(t, _C(1, 100, 100, 97, 98, 10))
    assert hit is not None and hit[1] == ExitReason.SL_HIT, hit
    # after +1R excursion the lock moves the stop into profit -> MTF_TRAIL_HIT
    t2 = ManagedTrade(
        trade_id="t3", symbol="BTCUSDT", set_id="SET_3_SWING",
        strategy="B_CONTINUATION_RIDING", action="BUY",
        entry_price=100.0, stop_loss=98.0, take_profit=130.0,
        position_size=1.0, dollar_risk=10.0, entry_timestamp=0,
        lockin_r=0.5, giveback_r=0.25, entry_risk_distance=2.0,
        initial_stop_loss=98.0, max_favorable_price=100.0,
    )
    # +1.0R excursion (high 102): lock floor = 102 - 0.25*2 = 101.5, no fill on
    # this bar (low 101.6 > stop), stop ratchets into profit.
    assert MTFTrailingEngine.check_intrabar_exit(t2, _C(2, 100, 102, 101.6, 101.8, 10)) is None
    assert t2.stop_loss > 100.0, t2.stop_loss  # locked into profit
    hit2 = MTFTrailingEngine.check_intrabar_exit(t2, _C(3, 101, 101, 100, 100, 10))
    assert hit2 is not None and hit2[1] == ExitReason.MTF_TRAIL_HIT, hit2
    print("  OK test_trailing_stop_classification")


def test_orchestrator_full():
    htf_state = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_BOS_BULLISH,
                                trigger_timestamp=1000, trigger_price=100.0)],
        external=[_swing(SwingOrientation.HIGH, 102.0, 1000),
                  _swing(SwingOrientation.LOW, 90.0, 900)],
        protected_low=_swing(SwingOrientation.LOW, 88.0, 800),
        weak_high=_swing(SwingOrientation.HIGH, 115.0, 1000),
        obs=[PriceZone(ZoneType.BULLISH_OB, 96.0, 94.0, 900)],
        close=100.0,
    )
    mtf_state = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_CHOCH_BULLISH,
                                trigger_timestamp=1500, trigger_price=100.0)],
        protected_low=_swing(SwingOrientation.LOW, 97.0, 700),
        close=100.0,
    )
    ltf_level = [_swing(SwingOrientation.LOW, 99.0, 500)]
    ltf_candles = [Candle(500 + i * 60, 99.5, 101, 99.3, 100.6, 100) for i in range(20)]
    ltf_candles.append(Candle(2000, 100.5, 101.5, 98.9, 100.8, 150))
    ltf_candles.append(Candle(2060, 100.8, 102.0, 100.5, 101.5, 150))
    ltf_state = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_CHOCH_BULLISH,
                                trigger_timestamp=2060, trigger_price=101.0)],
        internal=ltf_level, close=101.5, trend="BULLISH",
    )
    htf_candles = [Candle(100, 95, 100, 94, 99, 100)]
    mtf_candles = [Candle(100, 95, 100, 94, 99, 100)]

    cand = StrategyOrchestrator.evaluate_bar(
        set_id="SET_4_INTRADAY",
        htf_state=htf_state, mtf_state=mtf_state, ltf_state=ltf_state,
        htf_candles=htf_candles, mtf_candles=mtf_candles, ltf_candles=ltf_candles,
        account_balance=1000.0,
        rr_pullback_mult=1.0,  # test fixture RR=4.44 clears 1:4 but not the live 1:6 pullback premium
    )
    assert cand is not None, "orchestrator returned None"
    assert cand.strategy in ("A_PULLBACK_RIDING", "B_CONTINUATION_RIDING")
    assert cand.reward_to_risk >= 4.0
    print("  OK test_orchestrator_full ->", cand.strategy)


def test_orchestrator_pullback_premium():
    """Strategy A must clear the 1.5x pullback premium (live default)."""
    htf_state = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_BOS_BULLISH,
                                trigger_timestamp=1000, trigger_price=100.0)],
        external=[_swing(SwingOrientation.HIGH, 102.0, 1000),
                  _swing(SwingOrientation.LOW, 90.0, 900)],
        protected_low=_swing(SwingOrientation.LOW, 88.0, 800),
        weak_high=_swing(SwingOrientation.HIGH, 115.0, 1000),
        obs=[PriceZone(ZoneType.BULLISH_OB, 96.0, 94.0, 900)],
        close=100.0,
    )
    mtf_state = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_CHOCH_BULLISH,
                                trigger_timestamp=1500, trigger_price=100.0)],
        protected_low=_swing(SwingOrientation.LOW, 97.0, 700),
        close=100.0,
    )
    ltf_level = [_swing(SwingOrientation.LOW, 99.0, 500)]
    ltf_candles = [Candle(500 + i * 60, 99.5, 101, 99.3, 100.6, 100) for i in range(20)]
    ltf_candles.append(Candle(2000, 100.5, 101.5, 98.9, 100.8, 150))
    ltf_candles.append(Candle(2060, 100.8, 102.0, 100.5, 101.5, 150))
    ltf_state = _state(
        bias="BULLISH",
        events=[StructuralEvent(event_type=EventType.EXTERNAL_CHOCH_BULLISH,
                                trigger_timestamp=2060, trigger_price=101.0)],
        internal=ltf_level, close=101.5, trend="BULLISH",
    )
    htf_candles = [Candle(100, 95, 100, 94, 99, 100)]
    mtf_candles = [Candle(100, 95, 100, 94, 99, 100)]
    # Fixture RR is ~4.44: passes 1:4 with no premium, fails the live 1:6 pullback bar.
    cand_plain = StrategyOrchestrator.evaluate_bar(
        set_id="SET_4_INTRADAY",
        htf_state=htf_state, mtf_state=mtf_state, ltf_state=ltf_state,
        htf_candles=htf_candles, mtf_candles=mtf_candles, ltf_candles=ltf_candles,
        account_balance=1000.0, rr_pullback_mult=1.0,
    )
    assert cand_plain is not None
    cand_live = StrategyOrchestrator.evaluate_bar(
        set_id="SET_4_INTRADAY",
        htf_state=htf_state, mtf_state=mtf_state, ltf_state=ltf_state,
        htf_candles=htf_candles, mtf_candles=mtf_candles, ltf_candles=ltf_candles,
        account_balance=1000.0, rr_pullback_mult=1.5,
    )
    assert cand_live is None, "pullback premium must reject RR=4.44 at 1:6 bar"
    print("  OK test_orchestrator_pullback_premium")


if __name__ == "__main__":
    print("APEX strategy-layer unit tests")
    test_htf_bias_engine()
    test_mtf_setup_engine()
    test_ltf_entry_liquidity_sweep()
    test_mtf_trailing()
    test_trailing_stop_classification()
    test_orchestrator_full()
    test_orchestrator_pullback_premium()
    print("\n✅ ALL STRATEGY-LAYER TESTS PASSED")

