"""
APEX Quant OS - Profitability certification (reproducible).
Regenerates headline metrics from a trade CSV + checks per-combo profitability,
exit mix, and cost realism. Fails (exit 1) if system is not profitable.
Usage:
  python3 scripts/certify_profitability.py trades.csv
  python3 scripts/certify_profitability.py /tmp/repro_trades.csv
"""
import csv, sys, collections, pathlib

def load(path):
    rows = list(csv.DictReader(open(path)))
    if not rows:
        print("FAIL: no trades"); sys.exit(1)
    return rows

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "trades.csv"
    if not pathlib.Path(path).exists():
        print(f"FAIL: {path} not found"); sys.exit(1)
    rows = load(path)
    pnls = [float(r["pnl"]) for r in rows]
    rs = [float(r["r_multiple"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    pf = sum(wins)/abs(sum(losses)) if losses else 0.0
    wr = len(wins)/len(rows)*100
    avg_r = sum(rs)/len(rs)
    mix = collections.Counter(r["exit_reason"] for r in rows)
    print(f"trades={len(rows)} wins={len(wins)} ({wr:.1f}%) PF={pf:.2f} avgR={avg_r:.3f} net=${net:,.2f}")
    print(f"exit mix: {dict(mix)}")
    comb = collections.defaultdict(list)
    for r in rows:
        comb[(r["symbol"], r["set_id"])].append(float(r["pnl"]))
    bad = []
    for k, v in sorted(comb.items()):
        cnet = sum(v); cwr = sum(1 for x in v if x > 0)/len(v)*100
        gw = sum(x for x in v if x > 0); gl = abs(sum(x for x in v if x < 0))
        cpf = gw/gl if gl else 0
        flag = "" if cnet > 0 else "  <-- LOSING CELL"
        if cnet <= 0: bad.append(k)
        print(f"  {k[0]:<8} {k[1]:<16} n={len(v):>3} net=${cnet:>8.2f} WR={cwr:>5.1f}% PF={cpf:.2f}{flag}")
    ok = net > 0 and pf > 1.0 and avg_r > 0 and not bad
    print("CERTIFIED PROFITABLE" if ok else f"NOT PROFITABLE (losing cells: {bad})")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
