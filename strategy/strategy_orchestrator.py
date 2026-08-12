"""
APEX Quant OS - Layer 3: Master Strategy Orchestrator Engine
Chains the full multi-timeframe pipeline for the concept:

    HTF Bias (external BOS/CHoCH + keyzone + expectation phase)
        -> MTF Setup (structure shift / realignment toward bias + trailing anchor)
            -> LTF Entry Model (liquidity sweep / structure shift + strong SL)
                -> Risk Firewall (max 1% risk, min 1:4 R:R)

Both operating strategies are produced from the same pipeline:
    Strategy A (Pullback Riding)    active when HTF expects a pullback to its keyzone.
    Strategy B (Continuation Riding) active when price has already pulled back into
                                    the HTF keyzone and a continuation is expected.

The take-profit is fixed at the HTF objective; the stop-loss is the LTF strong
reversal point; the trade is trailed by MTF structure in trade_management.
"""

import uuid
from dataclasses import dataclass
from typing import List, Optional

from market_language.market_structure import Candle
from market_language.timeframe_engine import TimeframeState

from risk.risk_engine import RiskEngine
from strategy.htf_bias_engine import HTFBiasEngine, HTFExpectation
from strategy.mtf_setup_engine import MTFSetupEngine
from strategy.ltf_entry_engine import LTFEntryEngine


@dataclass
class TradeCandidate:
    trade_id: str
    set_id: str
    strategy: str                 # A_PULLBACK_RIDING / B_CONTINUATION_RIDING
    action: str                   # BUY / SELL
    entry_price: float
    stop_loss: float
    take_profit: float
    reward_to_risk: float
    dollar_risk: float
    position_size: float
    htf_bias: str
    htf_target: float
    mtf_trailing_anchor: float
    entry_model: str
    reason: str


class StrategyOrchestrator:

    @staticmethod
    def evaluate_bar(
        set_id: str,
        htf_state: TimeframeState,
        mtf_state: TimeframeState,
        ltf_state: TimeframeState,
        htf_candles: List[Candle],
        mtf_candles: List[Candle],
        ltf_candles: List[Candle],
        risk_pct: float = 0.01,
        min_rr: float = 4.0,
        account_balance: float = 1000.0,
        maker_fee: float = 0.0002,
        taker_fee: float = 0.0005,
        taker_slippage: float = 0.0003,
        cost_budget_pct: float = 0.25,
        min_vol_pct: float = 0.0,
        rr_pullback_mult: float = 1.5,  # pullback (Strategy A) entries must clear a premium R:R
    ) -> Optional[TradeCandidate]:

        # 1. HTF Bias + keyzone + expectation phase
        htf_res = HTFBiasEngine.evaluate_htf(htf_state, htf_candles)
        if not htf_res.is_valid:
            return None

        strategy = (
            "A_PULLBACK_RIDING" if htf_res.expectation == HTFExpectation.PULLBACK_EXPECTED
            else "B_CONTINUATION_RIDING"
        )

        # 2. MTF Setup (structure realignment toward bias)
        mtf_res = MTFSetupEngine.evaluate_mtf_setup(mtf_state, mtf_candles, htf_res.bias)
        if not mtf_res.is_aligned:
            return None

        # 3. LTF Entry Model (liquidity sweep / structure shift)
        ltf_res = LTFEntryEngine.evaluate_ltf_entry(ltf_state, ltf_candles, htf_res.bias)
        if not ltf_res.is_triggered:
            return None

        entry_p = ltf_res.trigger_price
        sl_p = ltf_res.stop_loss_price
        tp_p = htf_res.target_price

        # 4. Math-only risk firewall: max `risk_pct` risk, minimum R:R. Pullback
        #    (Strategy A) entries are structurally lower quality (they fade the
        #    immediate move), so they must clear a premium R:R before being taken.
        eff_min_rr = min_rr * (rr_pullback_mult if strategy == "A_PULLBACK_RIDING" else 1.0)
        risk_check = RiskEngine.calculate_risk(
            account_balance, entry_p, sl_p, tp_p,
            risk_percentage=risk_pct, min_rr_ratio=eff_min_rr,
        )
        if not risk_check.is_trade_allowed:
            return None

        # 4b. Institutional cost-aware filter: reject setups whose estimated round-trip
        # execution cost (limit/maker entry + market/taker exit + slippage) would consume
        # more than `cost_budget_pct` of the dollar risk. This surgically removes the
        # tight-stop, high-notional-to-risk trades that bleed fees on every round trip.
        notional = risk_check.position_size * entry_p
        est_cost = notional * (maker_fee + taker_fee + taker_slippage)
        if risk_check.dollar_risk > 0 and est_cost > cost_budget_pct * risk_check.dollar_risk:
            return None

        # 4c. Volatility floor filter: skip dead / low-volatility chop where the trend
        # rarely reaches the HTF objective (mostly noise). Disabled when min_vol_pct <= 0.
        if min_vol_pct > 0:
            vol = StrategyOrchestrator._ltf_volatility_pct(ltf_candles)
            if vol < min_vol_pct:
                return None

        action = "BUY" if htf_res.bias == "BULLISH" else "SELL"

        return TradeCandidate(
            trade_id=f"trd_{uuid.uuid4().hex[:8]}",
            set_id=set_id,
            strategy=strategy,
            action=action,
            entry_price=entry_p,
            stop_loss=sl_p,
            take_profit=tp_p,
            reward_to_risk=risk_check.reward_to_risk_ratio,
            dollar_risk=risk_check.dollar_risk,
            position_size=risk_check.position_size,
            htf_bias=htf_res.bias,
            htf_target=tp_p,
            mtf_trailing_anchor=mtf_res.trailing_anchor,
            entry_model=ltf_res.entry_model,
            reason=(
                f"[{strategy}] HTF={htf_res.bias} {htf_res.expectation.value} | "
                f"MTF={mtf_res.reason} | LTF={ltf_res.entry_model} | RR=1:{risk_check.reward_to_risk_ratio:.2f}"
            ),
        )

    @staticmethod
    def _ltf_volatility_pct(candles: List[Candle], period: int = 14) -> float:
        """
        Current ATR (Wilder) of the most recent `period` bars, expressed as a
        percentage of the latest close. Used by the volatility floor filter.
        """
        if len(candles) < 2:
            return 0.0
        trs = []
        start = max(0, len(candles) - period)
        for i in range(start, len(candles)):
            if i == 0:
                trs.append(candles[i].range)
            else:
                prev_close = candles[i - 1].close
                trs.append(max(
                    candles[i].high - candles[i].low,
                    abs(candles[i].high - prev_close),
                    abs(candles[i].low - prev_close),
                ))
        if not trs:
            return 0.0
        price = candles[-1].close or 1.0
        return (sum(trs) / len(trs)) / price * 100.0
