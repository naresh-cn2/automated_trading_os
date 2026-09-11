"""
APEX Quant OS - Pipeline Gate Diagnostic Harness
Runs strictly on tracked Git modules to isolate strategy execution gates.
"""

import os
import sys
import bisect

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from market_data.warehouse_loader import FullWarehouseLoader
from configs.sets import TIMEFRAME_SETS
from market_language.timeframe_engine import TimeframeEngine
from risk.risk_engine import RiskEngine

# Import the strategy engine tracked in Git commit 6ffce9f
alignment_engine_available = False
try:
    from strategy.alignment_engine import AlignmentEngine
    alignment_engine_available = True
    print("  ✅ [Engine Check] AlignmentEngine successfully loaded.")
except Exception as e:
    print(f"  ⚠️ [Engine Check] AlignmentEngine import notice: {e}")

print("==========================================================================================================")
print("     APEX QUANT OS: PIPELINE GATE DIAGNOSTIC HARNESS (SINGLE-CELL AUDIT)")
print("==========================================================================================================\n")

# 1. Load Market History for BTC SET_3_SWING
set_cfg = TIMEFRAME_SETS.get("SET_3_SWING")
if not set_cfg:
    print("❌ Error: SET_3_SWING configuration not found.")
    sys.exit(1)

print(f"📥 Loading candles for BTC/USDT (HTF: {set_cfg.htf}, MTF: {set_cfg.mtf}, LTF: {set_cfg.ltf})...")
c_htf = FullWarehouseLoader.load_full_history("BTC/USDT", set_cfg.htf)
c_mtf = FullWarehouseLoader.load_full_history("BTC/USDT", set_cfg.mtf)
c_ltf = FullWarehouseLoader.load_full_history("BTC/USDT", set_cfg.ltf)

print(f"  • HTF Candles : {len(c_htf):,}")
print(f"  • MTF Candles : {len(c_mtf):,}")
print(f"  • LTF Candles : {len(c_ltf):,}")

if not c_htf or not c_mtf or not c_ltf:
    print("\n⚠️ Historical data cache is empty. Run `python3 historical_downloader.py` or `python3 download_history.py` to fetch candle data.")
    sys.exit(1)

# 2. Setup Telemetry & Gate Counters
tf_engine = TimeframeEngine()
htf_ts = [c.timestamp for c in c_htf]
mtf_ts = [c.timestamp for c in c_mtf]

gate_counters = {
    "total_ltf_bars_evaluated": 0,
    "mtf_slice_valid": 0,
    "htf_slice_valid": 0,
    "htf_bias_bullish_or_bearish": 0,
    "alignment_passed": 0,
    "risk_allowed": 0,
    "trades_executed": 0
}

balance = 1000.0
sample_biases = set()

print("\n⏱️ Starting Bar-by-Bar Pipeline Inspection...\n")

for i in range(120, len(c_ltf), 2):
    gate_counters["total_ltf_bars_evaluated"] += 1
    current_bar = c_ltf[i]
    ts = current_bar.timestamp

    # Gate 1: MTF Slicing
    idx_mtf = bisect.bisect_right(mtf_ts, ts)
    if idx_mtf < 15: continue
    gate_counters["mtf_slice_valid"] += 1

    mtf_slice = c_mtf[max(0, idx_mtf - 100):idx_mtf]
    mtf_st = tf_engine.evaluate(mtf_slice, timeframe=set_cfg.mtf)
    if mtf_st is None: continue

    # Gate 2: HTF Slicing
    idx_htf = bisect.bisect_right(htf_ts, ts)
    if idx_htf < 10: continue
    gate_counters["htf_slice_valid"] += 1

    htf_slice = c_htf[max(0, idx_htf - 60):idx_htf]
    ltf_slice = c_ltf[max(0, i - 100):i + 1]

    htf_st = tf_engine.evaluate(htf_slice, timeframe=set_cfg.htf)
    ltf_st = tf_engine.evaluate(ltf_slice, timeframe=set_cfg.ltf)

    if htf_st is None or ltf_st is None: continue

    # Inspect exact HTF Bias representation
    raw_bias = getattr(htf_st, 'trend_direction', getattr(htf_st, 'trend', 'NEUTRAL'))
    bias_str = str(raw_bias.value) if hasattr(raw_bias, 'value') else str(raw_bias)
    sample_biases.add(f"{type(raw_bias).__name__}:{raw_bias} -> '{bias_str}'")

    if bias_str in ["BULLISH", "BEARISH"]:
        gate_counters["htf_bias_bullish_or_bearish"] += 1

        # Gate 3: Strategy Alignment
        is_aligned = True
        if alignment_engine_available:
            try:
                res = AlignmentEngine.check_alignment(htf_st, mtf_st, ltf_st)
                is_aligned = getattr(res, 'is_aligned', True)
            except Exception:
                is_aligned = True

        if is_aligned:
            gate_counters["alignment_passed"] += 1

            # Gate 4: Risk Calculation
            entry_p = current_bar.close
            sl_p = ltf_slice[-1].low if bias_str == "BULLISH" else ltf_slice[-1].high
            risk_dist = abs(entry_p - sl_p)

            if risk_dist > 0:
                tp_p = entry_p + (risk_dist * 4.0) if bias_str == "BULLISH" else entry_p - (risk_dist * 4.0)
                risk_res = RiskEngine.calculate_risk(balance, entry_p, sl_p, tp_p, 0.01, 4.0)
                
                if risk_res.is_trade_allowed:
                    gate_counters["risk_allowed"] += 1
                    gate_counters["trades_executed"] += 1

print("=" * 100)
print("📊 GATE TELEMETRY SUMMARY FOR BTC / SET_3_SWING")
print("=" * 100)
for gate, count in gate_counters.items():
    print(f"  • {gate:<35} : {count:,}")

print("\n🔍 HTF Bias Objects Observed:")
for sample in list(sample_biases)[:5]:
    print(f"  • {sample}")

print("=" * 100)
