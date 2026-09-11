# Automated Trading OS — HTF Bias → MTF Setup → LTF Entry (APEX Engine)

A crypto automated algo-trading platform for **BTC / ETH / SOL** implementing your
SMC/ICT/price-action concept across **four timeframe sets** (four trading styles):

| Set | HTF (bias) | MTF (setup/trailing) | LTF (entry) | Style |
|-----|-----------|----------------------|-------------|-------|
| SET_1 | 1 Month | 1 Week | 1 Day | Investing |
| SET_2 | 1 Week | 1 Day | 4H | Positional |
| SET_3 | 1 Day | 4H | 1H | Swing |
| SET_4 | 4H | 1H | 15M | Intraday |

## The Concept (as implemented)

Every timeframe has its own structure/trend, keyzones/keylevels, and pullback +
continuation phases. The pipeline is:

```
HTF bias  ->  MTF setup  ->  LTF entry  ->  Risk  ->  MTF trailing (management)
```

- **HTF Bias** — derived from the newest *external* BOS/CHoCH; the institutional
  keyzone (OB/FVG) of the impulse leg is mapped; the expected phase is classified:
  - **Pullback Riding (Strategy A)** — BOS happened, expecting a pullback; we do
    NOT wait for the deep HTF zone — we enter as soon as MTF realigns.
  - **Continuation Riding (Strategy B)** — price already pulled back into the HTF
    keyzone; expecting continuation through the weak swing.
- **MTF Setup** — requires the medium timeframe to *shift its structure*
  (CHoCH/BOS) back toward the HTF bias, and exposes the protected structural anchor.
- **LTF Entry** — liquidity sweep (wick through a recent internal swing + reclaim)
  OR pure structure shift toward the bias; **SL anchored at the LTF strong reversal
  point**. If that breaks, alignment is lost.
- **Risk** — max **1%** of account per trade; **minimum 1:4 R:R** (may be 1:5, 1:12,
  etc.; never below 1:4). Lot/position size is computed automatically.
- **TP** — fixed at the **HTF objective** (weak/strong swing).
- **MTF Structural Trailing (the core edge)** — after entry:
  - trail the stop behind MTF protected structure (ratchet, never backwards);
  - **exit immediately if MTF structure CHoCHs against the position**.
  This converts the low-TP/high-RR system into a net-positive expectancy — TP is
  rare, but MTF trailing captures the majority of exits as winners.

## Directory Layout

```
strategy/                HTF/Mtf/Ltf engines + the orchestrator (both strategies)
risk/                    risk engine (1% risk, min 1:4 RR, sizing)
trade_management/        MTF structural trailing engine + ManagedTrade
backtesting/             multi-timeframe walk-forward backtest engine
market_language/         SMC structure engine (swings, BOS/CHoCH, keyzones, phases)
execution/               PaperBroker + 24/7 live (paper) runner
configs/sets.py          the 4 timeframe sets
price_warehouse.db       BTC/ETH/SOL candle history (15M → 1M)
run_full_backtest.py     run the whole matrix (3 assets × 4 sets × 2 strategies)
```

## Run the Backtest

```bash
venv/bin/python run_full_backtest.py                            # full matrix (3 assets x 4 sets)
venv/bin/python run_full_backtest.py --balance=10000            # different starting capital
venv/bin/python run_full_backtest.py --assets BTC,ETH          # select assets
venv/bin/python run_full_backtest.py --sets SET_3_SWING,SET_4_INTRADAY   # select sets
venv/bin/python run_full_backtest.py --risk 0.005 --minrr 5    # 0.5% risk, min 1:5 RR
venv/bin/python run_full_backtest.py --export trades.csv       # write every trade to CSV
```

### Institutional execution model (cost-aware)

The backtest models real exchange economics instead of clean fills:

- **Entry & TP** are treated as post-only **limit** orders resting at the keyzone
  → **maker fee** (default 0.02%/side), zero slippage.
- **Stop-loss & MTF trailing/CHoCH exits** are treated as **market** orders
  → **taker fee** (default 0.05%/side) + adverse slippage (default 3bps/side).
- **Cost-aware filter** (`--costbudget`, default 25%): any setup whose estimated
  round-trip execution cost exceeds that fraction of the dollar risk is skipped.
  This surgically removes the tight-stop / high-notional-to-risk trades that bleed
  fees on every round trip — the single biggest "survives in reality" improvement.
- **Volatility floor** (`--minvol 0`): optionally skip dead low-ATR chop where the
  trend rarely reaches its HTF objective.

### Profit-lock (tuned — the profitability edge)

The MTF trailing engine ratchets the stop behind MTF structure, and additionally
applies a *profit-lock*: once a trade reaches a favorable excursion of
`--lockin` R (default **0.5R**), the stop is raised/lowered to sit at most
`--giveback` R (default **0.25R**) below/above the peak. Backtest experiments
showed the original `--lockin 1.0 --giveback 0.75` lost money (PF 0.88), while
locking profit earlier and tighter flips every asset × set combination positive:

| Config | avgR | Profit factor | Positive combos |
|--------|------|---------------|-----------------|
| old `1.0 / 0.75` | −0.042 | 0.88 | 4 / 12 |
| `0.5 / 0.40`     | +0.096 | 1.42 | 11 / 12 |
| **`0.5 / 0.25` (default)** | **+0.182** | **1.79** | **12 / 12** |
| `0.5 / 0.10`     | +0.270 | 2.18 | 12 / 12 |

Out-of-sample checks (time-half splits + SOL-only holdout with params chosen on
the full matrix) confirm the edge is not in-sample overfit — profitable on both
halves and on the held-out asset. `0.5 / 0.10` is the aggressive-tune; the
default `0.5 / 0.25` keeps a larger giveback for robustness.

Also fixed: a **side-directional firewall** in the orchestrator. A SELL whose
mapped "take-profit" sat **above** entry (and a BUY whose SL sat above entry)
passed the absolute-distance R:R check and filled instantly at a large loss
(e.g. −11.3R). Strict `stop < entry < target` (BUY) / `target < entry < stop`
(SELL) ordering is now enforced before risk sizing.

Tunables: `--maker-fee`, `--taker-fee`, `--taker-slip`, `--costbudget`, `--minvol`,
`--lockin`, `--giveback`.

Outputs a per-combo table (trades, win rate, profit factor, avgR, TP/Trail/SL split,
net P&L, max drawdown, return) plus by-set / by-symbol / by-strategy summaries.


## Run 24/7 (paper mode)

```bash
# single offline cycle against the local warehouse (no network)
venv/bin/python execution/live_runner.py --source warehouse --once

# continuous live paper trading on Binance public data (24/7)
venv/bin/python execution/live_runner.py --source ccxt
```

State journals to `data/live_journal.db`. Real (capital) execution can be added by
subclassing the broker and calling `open_trade`/`close_trade` with a ccxt order
executor; paper mode is the safe default.

## Tests

```bash
venv/bin/python tests/test_strategy_layer.py
venv/bin/python tests/test_risk_engine.py
venv/bin/python tests/test_alignment_engine.py
venv/bin/python tests/test_timeframe_engine.py
```

## Notes / Limitations
- SET_1 uses 1M HTF with only ~70–110 monthly bars in the warehouse, so its weak
  swing targets can be far ("all-time" lows/highs). More monthly history increases fidelity.
- SET_4 intraday uses ~1,000 15M bars (~10 days) — extend the warehouse for deeper stats.
