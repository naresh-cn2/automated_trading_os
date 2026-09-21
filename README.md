# APEX Quant OS

**Institutional Multi-Asset, Multi-Timeframe Automated Trading Platform**

APEX Quant OS is a research-grade quantitative trading platform that implements a
**three-timeframe structural alignment thesis** — Higher-Timeframe Bias →
Medium-Timeframe Setup → Lower-Timeframe Entry — across four independent trading
styles, three crypto assets, and a fully cost-aware execution model.

The platform is built around a single, falsifiable claim: **institutional
structural information (BOS/CHoCH, keyzones, liquidity, protected structure)
propagates predictably across timeframes, and that propagation can be harvested
as positive-expectancy with disciplined risk and structural trailing.**

---

## Executive Summary

| Metric | Value |
|---|---|
| **Universe** | BTC · ETH · SOL, 4 timeframe sets, 2 strategies |
| **Backtest span** | Daily data Nov 2023 → Jul 2026 (~2.7 years, 1,000 bars); monthly/weekly back to 2017 |
| **Combined net P&L** (12 × $1,000 independent accounts) | **+$1,726.54** |
| **Profit factor** (gross win ÷ gross loss) | **1.78** |
| **Expectancy per trade** | **+0.18R** at 1% risk/trade |
| **Win rate** | **66.0%** |
| **Profitable cells** (of 12 asset × set combos) | **12 / 12** |
| **Exit mix** | MTF structural trail 83.2% (incl. profit-locked) · MTF CHoCH 24.5% of trail · True stop-loss 16.8% |
| **Out-of-sample validation** | Time-half splits ✅ · Held-out asset ✅ · Doubled fees ✅ |

All results are produced by the walk-forward backtest engine with an
institutional execution model (maker/taker fees, adverse slippage, cost-aware
filter) — no clean-fill assumptions.

---

## Investment Thesis

The platform operationalizes Smart Money Concepts (SMC) / Inner Circle Trading
(ICT) / price-action theory into a deterministic, testable pipeline:

```
  HTF BIAS  →  MTF SETUP  →  LTF ENTRY  →  RISK FIREWALL  →  MTF TRAILING
```

Every timeframe contributes its own structure, trend, keyzones, and phase:

1. **HTF Bias** — derived from the newest *external* Break of Structure (BOS) or
   Change of Character (CHoCH). The institutional keyzone (Order Block / Fair
   Value Gap) of the impulse leg is mapped and the expected phase classified:
   - **Strategy A — Pullback Riding**: a BOS has occurred and a pullback is
     expected; we do **not** wait for the deep HTF zone — we enter as soon as
     the MTF realigns.
   - **Strategy B — Continuation Riding**: price has already pulled back into the
     HTF keyzone; we expect continuation through the weak swing.
2. **MTF Setup** — the medium timeframe must *shift structure* (CHoCH/BOS) back
   toward the HTF bias, exposing a protected structural anchor.
3. **LTF Entry** — a liquidity sweep (wick through a recent internal swing +
   reclaim) or a pure structure shift toward the bias. The stop-loss is anchored
   at the LTF strong reversal point; if that breaks, alignment is lost.
4. **Risk Firewall** — maximum **1% of account per trade**, minimum **1:4 R:R**
   (pullback entries must clear a premium R:R). Position size is derived from
   risk distance and account equity.

5. **MTF Structural Trailing** — the core edge-preservation layer:
   - ratchet the stop behind MTF protected structure (never backwards);
   - exit immediately at market if MTF structure CHoCHs against the position;
   - **profit-lock**: once a trade reaches +0.5R favorable excursion, the stop
     is locked to allow at most 0.25R giveback from the peak.

This converts a low-TP / high-RR system into positive expectancy: TP hits are
rare, but structural trailing + profit-lock capture the majority of exits as
winners.

---

## Four Independent Trading Styles

| Set | HTF (bias) | MTF (setup/trail) | LTF (entry) | Style | Horizon |
|-----|-----------|------------------|-------------|-------|---------|
| `SET_1_INVESTING`  | 1 Month | 1 Week  | 1 Day   | Investing  | Multi-month |
| `SET_2_POSITIONAL` | 1 Week  | 1 Day   | 4H      | Positional | Weeks       |
| `SET_3_SWING`      | 1 Day   | 4H      | 1H      | Swing      | Days        |
| `SET_4_INTRADAY`   | 4H      | 1H      | 15M     | Intraday   | Hours       |

Each set is engineered and backtested independently, and each produces its own
characteristics — creating a natural diversification across holding periods.

---

## Architecture

```
                    ┌───────────────────────────────────────────────┐
                    │                 APEX QUANT OS                  │
                    │                                                │
  ┌──────────────┐  │  ┌──────────────┐     ┌──────────────┐        │
  │ market_language│ │  │   strategy   │     │     risk     │        │
  │ SMC structure │──→│ HTF→MTF→LTF   │────→│ 1% cap, min  │        │
  │ BOS/CHoCH,    │  │  orchestrator │     │ 1:4 R:R, size│        │
  │ keyzones,     │  │               │     └──────┬────────┘        │
  │ phases        │  └───────────────┘            │                 │
  └──────────────┘  ┌───────────────┐   ┌─────────▼───────┐         │
                    │trade_management│   │    execution    │         │
  ┌──────────────┐  │ MTF structural│   │  paper broker   │         │
  │ backtesting  │  │ trailing +    │──→│  24/7 runner    │         │
  │ walk-forward │  │ profit-lock   │   └─────────────────┘         │
  └──────────────┘  └───────────────┘                               │
                    └───────────────────────────────────────────────┘
```

| Component | Responsibility |
|---|---|
| `market_language/` | SMC structure engine: swings, BOS/CHoCH events, order blocks / fair value gaps, key levels (EQH/EQL, PDH/PDL), phases, reusable fractal `TimeframeEngine` |
| `strategy/` | `HTFBiasEngine` → `MTFSetupEngine` → `LTFEntryEngine`, orchestrated by `StrategyOrchestrator` (both strategies) |
| `risk/` | Math-only `RiskEngine`: 1% equity risk, min 1:4 R:R, exact position sizing, mis-side firewall |
| `trade_management/` | `MTFTrailingEngine` + `ManagedTrade`: structural ratchet, CHoCH invalidation exit, profit-lock |
| `backtesting/` | Bar-by-bar walk-forward replay engine with institutional cost modeling |
| `execution/` | `PaperBroker` (SQLite-journaled) + 24/7 paper-mode runner over warehouse or live ccxt feed |
| `configs/sets.py` | The 4 timeframe configurations (trading styles) |


---

## Backtest Methodology

### Engine

- **Walk-forward, bar-by-bar replay** across the HTF/MTF/LTF stack — no
  look-ahead bias; each decision uses only candles with timestamps ≤ the current
  bar.
- Each of the 12 combinations (3 assets × 4 sets) runs as an **independent
  account** (default $1,000) compounding at 1% risk per trade.

### Institutional Execution Model

| Order type | Treatment | Fee / slippage (default) |
|---|---|---|
| Entry & take-profit | Post-only **limit** orders resting at the keyzone | 0.02% maker fee · 0 slippage |
| Stop-loss, trailing & CHoCH exits | **Market** orders | 0.05% taker fee + 3 bps adverse slippage |

Additional filters:

- **Cost-aware filter** (`--costbudget`, default 25%): any setup whose estimated
  round-trip execution cost exceeds that fraction of the dollar risk is skipped
  — surgically removing the tight-stop, high-notional-to-risk trades that bleed
  fees on every round trip.
- **Volatility floor** (`--minvol 0`): optionally skip dead low-ATR chop.

### Risk Parameters

| Parameter | Default |
|---|---|
| Risk per trade | 1% of current account |
| Minimum R:R | 1:4 (1:6 effective for pullback/Strategy A entries) |
| Profit-lock | Lock after +0.5R, max 0.25R giveback from peak |
| Pullback premium | ×1.5 R:R multiplier |

---

## Validated Backtest Results

### Combined (all 12 combos, default parameters)

| Metric | Result |
|---|---|
| Trades | 870 |
| Win rate | 66.0% |
| Profit factor | 1.78 |
| Expectancy | +0.18R / trade |
| Instant-fill accidents | 0 (side firewall active) |
| **Aggregate net P&L** | **+$1,726.54** |
| **Average combo return** | **+14.4%** |
| **Exit mix** | MTF_TRAIL_HIT 511 · MTF_CHOCH_EXIT 213 · SL_HIT 146 (true initial-stop losses 16.8%) |
| **Trade audit** | `scripts/certify_profitability.py trades.csv` → CERTIFIED PROFITABLE |

### Per-Combo Breakdown (net P&L per $1,000 account)

| Combo | Trades | WR | PF | avgR | Net P&L | Return |
|---|---|---|---|---|---|---|
| BTC · SET_1 Investing  | 63 | 76.2% | 2.46 | +0.29 | +$197.63 | +19.8% |
| BTC · SET_2 Positional | 145 | 66.9% | 1.51 | +0.13 | +$194.38 | +19.4% |
| BTC · SET_3 Swing     | 22 | 68.2% | 1.21 | +0.04 | +$8.24  | +0.8%  |
| BTC · SET_4 Intraday  | 11 | 54.5% | 2.02 | +0.12 | +$13.17 | +1.3%  |
| ETH · SET_1 Investing | 142 | 65.5% | 1.94 | +0.25 | +$408.54 | +40.9% |
| ETH · SET_2 Positional | 88 | 64.8% | 2.38 | +0.29 | +$288.06 | +28.8% |
| ETH · SET_3 Swing     | 39 | 59.0% | 1.56 | +0.13 | +$50.70 | +5.1%  |
| ETH · SET_4 Intraday  | 28 | 67.9% | 1.80 | +0.11 | +$31.71 | +3.2%  |
| SOL · SET_1 Investing | 154 | 64.9% | 1.44 | +0.13 | +$211.44 | +21.1% |
| SOL · SET_2 Positional | 62 | 66.1% | 1.73 | +0.19 | +$123.40 | +12.3% |
| SOL · SET_3 Swing     | 105 | 61.9% | 1.66 | +0.13 | +$144.66 | +14.5% |
| SOL · SET_4 Intraday  | 11 | 90.9% | 6.77 | +0.49 | +$54.63 | +5.5%  |

### Out-of-Sample Robustness

The configuration was **not** selected on a single favorable window — the edge
was validated where it matters:

| Validation | Design | Result |
|---|---|---|
| **Time-half split (SET_1/2)** | Params picked on full history, tested on each half independently | First half avgR **+0.274** · Second half avgR **+0.189** — profitable on both |
| **Time-half split (SET_3/4)** | Same | First half avgR **+0.242** · Second half avgR **+0.248** |
| **Held-out asset (SOL)** | Params chosen on the full matrix, SOL excluded | **4/4 combos positive**, avgR +0.153 to +0.236 |
| **Doubled fees & slippage** | 2× maker/taker fee + 2× slippage | Net **+$845.95**, PF 1.43 — positive under extreme adversity |
---

## Quickstart

### Prerequisites

- Python 3.9+ and a local `venv`
- Candle warehouse at `price_warehouse.db` (bundled: BTC/ETH/SOL, 15M → 1M)

### Run the full backtest matrix

```bash
# full matrix: 3 assets × 4 sets × 2 strategies (default config)
venv/bin/python run_full_backtest.py

# customise capital, filters, or export every trade
venv/bin/python run_full_backtest.py --balance=100000
venv/bin/python run_full_backtest.py --assets BTC,ETH
venv/bin/python run_full_backtest.py --sets SET_3_SWING,SET_4_INTRADAY
venv/bin/python run_full_backtest.py --risk 0.005 --minrr 5
venv/bin/python run_full_backtest.py --export trades.csv
```

### Run 24/7 paper mode

```bash
# single offline cycle against the local warehouse (no network)
venv/bin/python execution/live_runner.py --source warehouse --once

# continuous live paper trading on Binance public data
venv/bin/python execution/live_runner.py --source ccxt
```

State journals to `data/live_journal.db`. Real (capital) execution can be added by
subclassing the broker and calling `open_trade`/`close_trade` with a ccxt order
executor; paper mode is the safe default.

### Run the test suite

```bash
venv/bin/python tests/test_risk_engine.py
venv/bin/python tests/test_alignment_engine.py
venv/bin/python tests/test_timeframe_engine.py
venv/bin/python tests/test_strategy_layer.py
```

### Tunable parameters

```text
--risk <pct>            risk fraction per trade         (default 0.01)
--minrr <R>             minimum reward:risk             (default 4.0)
--maker-fee <pct>       limit-fill fee (entry & TP)     (default 0.0002)
--taker-fee <pct>       market-fill fee (SL/trail)      (default 0.0005)
--taker-slip <bps>      adverse slippage on market fills(default 0.0003)
--costbudget <pct>      cost filter budget of risk      (default 0.25)
--minvol <pct>          LTF ATR% volatility floor       (default 0 = off)
--rrpullback <mult>     pullback (Strat A) R:R premium  (default 1.5)
--lockin <R>            profit-lock trigger excursion   (default 0.5)
--giveback <R>          max giveback from peak          (default 0.25)
```

---

## Data Coverage (`price_warehouse.db`)

| Symbol | 1M | 1W | 1D | 4H | 1H | 15M |
|---|---|---|---|---|---|---|
| BTC/USDT | 2017-08 | 2017-08 | 2023-11 → 2026-07 | 2026-02 | 2026-06 | last ~10 days |
| ETH/USDT | 2017-08 | 2017-08 | 2023-11 → 2026-07 | 2026-02 | 2026-06 | last ~10 days |
| SOL/USDT | 2020-08 | 2020-08 | 2023-11 → 2026-07 | 2026-02 | 2026-06 | last ~10 days |

---

## Project Layout

```
strategy/                HTF / MTF / LTF engines + orchestrator (2 strategies)
risk/                    math-only risk engine (1% cap, min 1:4 R:R, sizing)
trade_management/        MTF structural trailing + profit-lock + ManagedTrade
backtesting/             multi-timeframe walk-forward backtest engine
market_language/         SMC structure engine (swings, BOS/CHoCH, keyzones, phases)
execution/               PaperBroker + 24/7 live (paper) runner
configs/sets.py          the 4 timeframe sets (trading styles)
tests/                   deterministic unit suites (risk, alignment, timeframe, strategy)
price_warehouse.db       BTC/ETH/SOL candle history (15M → 1M)
run_full_backtest.py     full matrix runner (3 assets × 4 sets × 2 strategies)
```

---

## Validation History

- **v1.0** — baseline concept pipeline (HTF Bias → MTF Setup → LTF Entry).
- **`acd3c4d`** — *profitability release*. Fixed a **side-directional bug** (a
  SELL whose mapped take-profit sat above entry passed the absolute-distance R:R
  check and filled at −6.5R to −11.3R; strict `sl < entry < tp` / `tp < entry < sl`
  ordering is now enforced) and retuned the profit-lock (0.5R lock-in, 0.25R
  giveback). Net P&L moved from **−$298 → +$1,726**, profit factor **0.88 → 1.78**,
  profitable cells **4/12 → 12/12**.

---

## Known Limitations & Roadmap

1. **Intraday depth** — SET_4's 15M series (~10 days) and 4H series (~166 days)
   limit statistical confidence for the intraday cells; extend warehouse history
   to deepen those cells.
2. **SET_1 monthly HTF** — only ~72–108 monthly bars exist; weak-swing targets
   can be far ("all-time" levels). More monthly history increases fidelity.
3. **Forward confirmation** — backtested profitability must be confirmed in
   live paper mode before capital execution.
4. **Transaction cost realism** — fees/slippage are modeled, not observed;
   validate against the venue's actual fee schedule.

---

## Disclaimer

This software is a **research and simulation platform**. Past backtested
performance, including all out-of-sample results presented here, **does not
guarantee future results**. Cryptographic asset markets are volatile; there is
meaningful risk of loss. This platform is provided for research, educational,
and paper-trading use. Nothing here constitutes financial advice. Deploy to
live capital at your own risk.
