"""
Calcula as métricas do relatório de avaliação de posições.
Corre a partir da raiz do repositório:  python3 .claude/skills/relatorio-posicoes/report_metrics.py
Escreve JSON (summary + positions + séries ytd) para stdout.

Convenções importantes:
- ppl da T212 está em EUR e inclui efeito cambial → custo-base = valor_EUR - ppl.
- O valor bruto de compras via orders.json é INCOMPLETO (ordens antigas sem
  filledValue) — não usar como "capital investido"; usar o custo-base.
- A série 'portfolio' do chart_data é a composição ACTUAL projectada no tempo
  (backtest), não o retorno real da conta.
"""
import json, sys
from collections import defaultdict
from datetime import datetime, timezone
import subprocess

pos    = json.load(open("data/positions.json", encoding="utf-8"))
fx     = json.load(open("data/fx.json", encoding="utf-8"))
fund   = json.load(open("data/fundamentals.json", encoding="utf-8"))
chart  = json.load(open("data/chart_data.json", encoding="utf-8"))
orders = json.load(open("data/orders.json", encoding="utf-8"))
t212m  = json.load(open("data/t212_map.json", encoding="utf-8"))

def last(series):
    if not series: return None
    return round(series[max(series)], 2)

# data de actualização = último commit que tocou data/positions.json
try:
    asof = subprocess.check_output(
        ["git", "log", "-1", "--format=%ci", "--", "data/positions.json"],
        text=True).strip()[:16] + " UTC"
except Exception:
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

nsells = defaultdict(int); sellval = defaultdict(float)
exited = set()
for x in orders:
    if x.get("status") != "FILLED": continue
    d = t212m.get(x["ticker"], x["ticker"])
    if x["side"] == "SELL":
        nsells[d] += 1
        sellval[d] += abs(x.get("filledValue") or 0)
    exited.add(d)
cur_tickers = {p["ticker"] for p in pos}
n_exited = len(exited - cur_tickers)

total = sum(p["qty"] * p["curPrice"] * fx[p["cur"]] for p in pos)
sp = chart["indexes"]["SP500"]
out = []
for p in pos:
    t = p["ticker"]
    val = p["qty"] * p["curPrice"] * fx[p["cur"]]
    cost = val - p["ppl"]
    st = chart["stocks"].get(t, {})
    f = fund.get(t, {})
    dy = f.get("divYield")
    row = {
        "ticker": t, "name": p["name"], "sector": p["sector"], "flag": p["flag"],
        "cur": p["cur"], "qty": p["qty"], "avgPrice": p["avgPrice"], "curPrice": p["curPrice"],
        "valueEur": round(val, 2), "weight": round(val / total * 100, 2),
        "costEur": round(cost, 2), "plEur": p["ppl"],
        "plPct": round(p["ppl"] / cost * 100, 2),
        "nBuys": len(p["buyDates"]),
        "firstBuy": p["buyDates"][0] if p["buyDates"] else None,
        "lastBuy": p["buyDates"][-1] if p["buyDates"] else None,
        "nSells": nsells[t], "sellValEur": round(sellval[t], 2),
        "perf3mo": last(st.get("3mo")), "perfYtd": last(st.get("ytd")), "perf1y": last(st.get("1y")),
        "spYtd": last(sp["ytd"]),
        "pe": f.get("pe"), "divYield": dy, "payout": f.get("payoutRatio"),
        "netMargin": f.get("netMargin"), "revGrowth": f.get("revenueGrowth"),
        "fcfYield": f.get("fcfYield"), "roe": f.get("roe"), "marketCap": f.get("marketCap"),
        "estDivEur": round(dy / 100 * val, 2) if dy else 0,
    }
    row["yieldOnCost"] = round(row["estDivEur"] / cost * 100, 2) if row["estDivEur"] else 0
    out.append(row)

out.sort(key=lambda r: -r["valueEur"])
totPl = sum(r["plEur"] for r in out)
totCost = sum(r["costEur"] for r in out)
sect = defaultdict(float); curr = defaultdict(float)
for r in out:
    sect[r["sector"]] += r["weight"]; curr[r["cur"]] += r["weight"]
w = sorted((r["weight"] for r in out), reverse=True)
port = chart["portfolio"]
summary = {
    "asof": asof,
    "totalEur": round(total, 2), "plEur": round(totPl, 2),
    "plPct": round(totPl / totCost * 100, 2), "costEur": round(totCost, 2),
    "estDivEur": round(sum(r["estDivEur"] for r in out), 2),
    "top5": round(sum(w[:5]), 1),
    "hhi": round(sum((x / 100) ** 2 for x in w) * 10000),
    "nExited": n_exited,
    "sectors": dict(sorted(sect.items(), key=lambda x: -x[1])),
    "listingCur": dict(sorted(curr.items(), key=lambda x: -x[1])),
    "port3mo": last(port["3mo"]), "portYtd": last(port["ytd"]), "port1y": last(port["1y"]),
    "idx": {n: {per: last(chart["indexes"][n][per]) for per in ["3mo", "ytd", "1y"]}
            for n in chart["indexes"]},
}
summary["divYieldPort"] = round(summary["estDivEur"] / total * 100, 2)

json.dump({
    "summary": summary,
    "positions": out,
    "ytd": {"port": sorted(port["ytd"].items()),
            "sp":   sorted(sp["ytd"].items())},
}, sys.stdout, ensure_ascii=False, indent=1)
