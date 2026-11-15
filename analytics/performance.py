"""
Motor de desempenho.

Convenções (alinhadas com a metodologia do Sharpyield):
  • TWR — só o "sleeve" de títulos: encadeia o retorno diário do valor das
    posições, neutralizando compras e vendas. A caixa parada e os dividendos
    ficam de fora (os dividendos entram no Retorno Total e no IRR).
      r_d = (V_d − V_{d−1} − F_d) / V_{d−1},  F_d = compras − vendas do dia (fluxo ao fecho)
  • CAGR — TWR anualizado.
  • IRR — money-weighted (XIRR). `irrPct`: dinheiro que entrou e saiu das
    posições (compras −, vendas +, dividendos líquidos +, valor final +).
    `irrAccountPct`: a conta inteira (depósitos −, levantamentos +, valor total final +).
  • Retorno Total — valor total da conta − capital líquido depositado.
  • Risco — volatilidade, Sharpe, Sortino (taxa sem risco 2%), drawdown
    máximo, Calmar, beta e capturas vs S&P 500, em EUR, dias úteis.
  • "Se investido no índice" — o MESMO dinheiro, nas MESMAS datas: cada compra
    compra o índice, cada venda e cada dividendo vende-o.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .ledger import EXTERNAL_FLOWS, instrument_key
from .util import business_days, pct, r2, to_date, xirr

RF = 0.02
MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
BENCHMARKS = {"spy": "SPY", "qqq": "QQQ", "world": "URTH"}
BENCH_LABEL = {"spy": "S&P 500", "qqq": "Nasdaq 100", "world": "MSCI World"}


def _cash_delta(e):
    t, v = e["type"], e.get("totalEur") or 0.0
    if t in ("DEPOSIT", "SELL", "DIVIDEND", "INTEREST", "CASHBACK"):
        return v
    if t in ("WITHDRAWAL", "BUY", "FEE"):
        return -v
    return 0.0


def _max_drawdown(idx_series):
    peak, mdd, troughs = -1e18, 0.0, []
    cur_trough = None
    for d, v in idx_series:
        if v > peak:
            if cur_trough:
                troughs.append(cur_trough)
            peak, cur_trough = v, None
        dd = v / peak - 1 if peak > 0 else 0
        if dd < 0 and (cur_trough is None or dd < cur_trough[1]):
            cur_trough = (d, dd)
        mdd = min(mdd, dd)
    if cur_trough:
        troughs.append(cur_trough)
    troughs.sort(key=lambda x: x[1])
    return mdd, troughs


def _period_returns(idx_series, keyfn):
    """Retorno por período (mês/ano) a partir de um índice encadeado."""
    out, prev_end, last_key, last_val = {}, None, None, None
    base = idx_series[0][1] if idx_series else None
    for d, v in idx_series:
        k = keyfn(d)
        if last_key is not None and k != last_key:
            start = prev_end if prev_end is not None else base
            out[last_key] = last_val / start - 1
            prev_end = last_val
        last_key, last_val = k, v
    if last_key is not None:
        start = prev_end if prev_end is not None else base
        out[last_key] = last_val / start - 1
    return out


def compute(events, book, today: date, live_cash_eur=None):
    events = sorted(events, key=lambda e: e["time"])
    if not events:
        return {"available": False, "motivo": "sem transações no ledger"}
    start = to_date(events[0]["date"])
    days = business_days(start, today)
    if not days or days[-1] != today:
        days.append(today)

    qty = defaultdict(float)
    cash = 0.0
    net_dep = 0.0
    ei = 0
    prev_v = 0.0
    idx = 1.0
    rows = []
    daily_r = []
    shadow_units = {k: 0.0 for k in BENCHMARKS}
    cum_in = cum_out = 0.0
    pos_flows = []  # para o IRR das posições
    acc_flows = []
    missing = set()

    for d in days:
        flow_buy = flow_sell = 0.0
        day_events = []
        while ei < len(events) and to_date(events[ei]["date"]) <= d:
            e = events[ei]
            ei += 1
            day_events.append(e)
            t, k = e["type"], instrument_key(e)
            cash += _cash_delta(e)
            if t == "BUY":
                qty[k] += e.get("qty") or 0
                flow_buy += e.get("totalEur") or 0
            elif t == "SELL":
                qty[k] -= e.get("qty") or 0
                flow_sell += e.get("totalEur") or 0
            elif t == "SPLIT_IN":
                qty[k] += e.get("qty") or 0
            elif t == "SPLIT_OUT":
                qty[k] -= e.get("qty") or 0
            if t in EXTERNAL_FLOWS:
                amt = e.get("totalEur") or 0
                net_dep += amt if t == "DEPOSIT" else -amt
                acc_flows.append((d, -amt if t == "DEPOSIT" else amt))
            if t == "BUY":
                pos_flows.append((d, -(e.get("totalEur") or 0)))
            elif t in ("SELL", "DIVIDEND"):
                pos_flows.append((d, e.get("totalEur") or 0))

        v = 0.0
        for k, q in qty.items():
            if abs(q) < 1e-9:
                continue
            p = book.price_eur(k, d, today)
            if p is None:
                missing.add(k)
                continue
            v += q * p

        f = flow_buy - flow_sell
        # Fluxo no fim do dia (as execuções são valorizadas ao fecho). No
        # primeiro dia com posições, a base é o que se comprou.
        denom = prev_v if prev_v > 1e-6 else max(f, 0.0)
        r = (v - prev_v - f) / denom if denom > 1e-6 else 0.0
        if denom > 1e-6:
            idx *= 1 + r
            daily_r.append((d, r))
        prev_v = v

        # Réplica no índice
        outflow = flow_sell + sum(e.get("totalEur") or 0 for e in day_events if e["type"] == "DIVIDEND")
        cum_in += flow_buy
        cum_out += outflow
        for bk, sym in BENCHMARKS.items():
            px = book.bench_eur(sym, d)
            if px:
                shadow_units[bk] += (flow_buy - outflow) / px

        bvals = {bk: book.bench_eur(sym, d) for bk, sym in BENCHMARKS.items()}
        rows.append({"d": d, "v": v, "cash": cash, "dep": net_dep, "idx": idx, "r": r, **{f"b_{k}": x for k, x in bvals.items()}})

    last = rows[-1]
    cash_now = live_cash_eur if live_cash_eur is not None else last["cash"]
    total_value = last["v"] + cash_now
    total_return = total_value - last["dep"]

    pos_flows_irr = pos_flows + [(today, last["v"])]
    acc_flows_irr = acc_flows + [(today, total_value)]
    irr = xirr(pos_flows_irr)
    irr_acc = xirr(acc_flows_irr)

    # ── TWR / CAGR / benchmarks ────────────────────────────────────────────
    first_inv = next((r_ for r_ in rows if r_["v"] > 0), rows[0])
    span_days = max((today - first_inv["d"]).days, 1)
    twr = last["idx"] - 1
    cagr = (1 + twr) ** (365.25 / span_days) - 1 if span_days >= 45 else None

    idx_series = [(r_["d"], r_["idx"]) for r_ in rows if r_["d"] >= first_inv["d"]]
    bench_idx = {}
    for bk in BENCHMARKS:
        pts = [(r_["d"], r_[f"b_{bk}"]) for r_ in rows if r_["d"] >= first_inv["d"] and r_[f"b_{bk}"]]
        if len(pts) > 1:
            b0 = pts[0][1]
            bench_idx[bk] = [(d, v / b0) for d, v in pts]

    bench_twr = {bk: s[-1][1] - 1 for bk, s in bench_idx.items()}
    bench_cagr = {bk: ((1 + t) ** (365.25 / span_days) - 1 if span_days >= 45 else None)
                  for bk, t in bench_twr.items()}

    # ── risco ──────────────────────────────────────────────────────────────
    rets = [r_ for d, r_ in daily_r if d >= first_inv["d"]][1:]
    vol = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 20 else None
    rf_d = RF / 252
    downside = [min(x - rf_d, 0) ** 2 for x in rets]
    dd_dev = math.sqrt(sum(downside) / len(downside)) * math.sqrt(252) if len(rets) > 20 else None
    mdd, troughs = _max_drawdown(idx_series)
    sharpe = (cagr - RF) / vol if cagr is not None and vol else None
    sortino = (cagr - RF) / dd_dev if cagr is not None and dd_dev else None
    calmar = cagr / abs(mdd) if cagr is not None and mdd < 0 else None

    beta = None
    spy = dict(bench_idx.get("spy", []))
    pairs = []
    prev_b = None
    for d, r_ in daily_r:
        b = spy.get(d)
        if b is not None and prev_b is not None and d > first_inv["d"]:
            pairs.append((r_, b / prev_b - 1))
        if b is not None:
            prev_b = b
    if len(pairs) > 20:
        mp = statistics.mean(p for p, _ in pairs)
        mb = statistics.mean(b for _, b in pairs)
        cov = sum((p - mp) * (b - mb) for p, b in pairs) / len(pairs)
        var = sum((b - mb) ** 2 for _, b in pairs) / len(pairs)
        beta = cov / var if var else None
    alpha_adj = (cagr - (RF + beta * (bench_cagr.get("spy") - RF))) if (
        cagr is not None and beta is not None and bench_cagr.get("spy") is not None) else None

    bench_mdd = {bk: _max_drawdown(s)[0] for bk, s in bench_idx.items()}

    # ── mensal / anual ─────────────────────────────────────────────────────
    monthly = _period_returns(idx_series, lambda d: (d.year, d.month))
    annual = _period_returns(idx_series, lambda d: d.year)
    bench_monthly = {bk: _period_returns(s, lambda d: (d.year, d.month)) for bk, s in bench_idx.items()}
    bench_annual = {bk: _period_returns(s, lambda d: d.year) for bk, s in bench_idx.items()}

    matrix = defaultdict(dict)
    for (y, m), v in monthly.items():
        matrix[str(y)][MONTHS_PT[m - 1]] = pct(v)
    cur_ym = (today.year, today.month)
    completed = {k: v for k, v in monthly.items() if k != cur_ym}
    best = max(completed.items(), key=lambda x: x[1]) if completed else None
    worst = min(completed.items(), key=lambda x: x[1]) if completed else None
    streak, direction = 0, None
    for k in sorted(monthly, reverse=True):
        s = "up" if monthly[k] >= 0 else "down"
        if direction is None:
            direction = s
        if s != direction:
            break
        streak += 1
    seasonality = []
    for m in range(1, 13):
        vals = [v for (y, mm), v in completed.items() if mm == m]
        if vals:
            seasonality.append({"month": m, "label": MONTHS_PT[m - 1].capitalize(),
                                "avgPct": pct(statistics.mean(vals), 1), "count": len(vals),
                                "positiveShare": round(100 * sum(v >= 0 for v in vals) / len(vals))})

    up_m = [(p, bench_monthly["spy"][k]) for k, p in monthly.items()
            if "spy" in bench_monthly and k in bench_monthly["spy"] and bench_monthly["spy"][k] > 0]
    dn_m = [(p, bench_monthly["spy"][k]) for k, p in monthly.items()
            if "spy" in bench_monthly and k in bench_monthly["spy"] and bench_monthly["spy"][k] < 0]
    cap_up = (statistics.mean(p for p, _ in up_m) / statistics.mean(b for _, b in up_m)) if up_m else None
    cap_dn = (statistics.mean(p for p, _ in dn_m) / statistics.mean(b for _, b in dn_m)) if dn_m else None
    beat = [k for k, p in monthly.items() if "spy" in bench_monthly and k in bench_monthly["spy"]]
    months_beating = (sum(monthly[k] > bench_monthly["spy"][k] for k in beat) / len(beat)) if beat else None

    annual_rows = []
    for y in sorted(annual):
        row = {"year": y, "portfolioPct": pct(annual[y])}
        for bk in BENCHMARKS:
            row[f"{bk}Pct"] = pct(bench_annual.get(bk, {}).get(y))
        annual_rows.append(row)

    # YTD (TWR)
    ytd_base = next((v for d, v in reversed(idx_series) if d.year < today.year), None)
    ytd = (idx_series[-1][1] / ytd_base - 1) if ytd_base else (annual.get(today.year))

    # ── réplica no índice ──────────────────────────────────────────────────
    own_gain = last["v"] + cum_out - cum_in
    replica = {}
    for bk, sym in BENCHMARKS.items():
        px = book.bench_eur(sym, today)
        if px:
            g = shadow_units[bk] * px + cum_out - cum_in
            replica[bk] = {"eur": r2(g), "pct": pct(g / last["dep"]) if last["dep"] > 0 else None,
                           "label": BENCH_LABEL[bk]}

    # ── máximos ────────────────────────────────────────────────────────────
    prior = rows[:-1]
    peak_v = max(prior, key=lambda r_: r_["v"]) if prior else last
    pnl_rows = [(r_["d"], r_["v"] + r_["cash"] - r_["dep"]) for r_ in prior]
    peak_pnl = max(pnl_rows, key=lambda x: x[1]) if pnl_rows else (today, total_return)

    # ── série para gráficos (semanal + último dia) ─────────────────────────
    chart = []
    bench_dicts = {bk: dict(s) for bk, s in bench_idx.items()}
    for i, r_ in enumerate(rows):
        if r_["d"] < first_inv["d"]:
            continue
        if r_["d"].weekday() == 4 or i == len(rows) - 1:
            pt = {"d": r_["d"].isoformat(), "v": r2(r_["v"]), "t": r2(r_["v"] + r_["cash"]),
                  "dep": r2(r_["dep"]), "pnl": r2(r_["v"] + r_["cash"] - r_["dep"]),
                  "twr": pct(r_["idx"] - 1)}
            for bk, bd in bench_dicts.items():
                dd = bd.get(r_["d"])
                pt[bk] = pct(dd - 1) if dd else None
            chart.append(pt)
    if chart:
        chart[-1]["t"] = r2(total_value)
        chart[-1]["pnl"] = r2(total_return)

    return {
        "available": True,
        "asOf": today.isoformat(),
        "inicio": first_inv["d"].isoformat(),
        "totais": {
            "totalValueEur": r2(total_value), "positionsValueEur": r2(last["v"]),
            "cashEur": r2(cash_now), "cashLedgerEur": r2(last["cash"]),
            "netDepositsEur": r2(last["dep"]),
            "totalReturnEur": r2(total_return),
            "totalReturnPct": pct(total_return / last["dep"]) if last["dep"] > 0 else None,
            "irrPct": pct(irr), "irrAccountPct": pct(irr_acc),
            "twrPct": pct(twr), "cagrPct": pct(cagr), "ytdPct": pct(ytd),
            "benchmarkTwrPct": {k: pct(v) for k, v in bench_twr.items()},
            "benchmarkCagrPct": {k: pct(v) for k, v in bench_cagr.items()},
            "superacaoCagrVsSpyPct": pct(cagr - bench_cagr["spy"]) if cagr is not None and bench_cagr.get("spy") is not None else None,
        },
        "risco": {
            "volatilityPct": pct(vol), "sharpe": r2(sharpe), "sortino": r2(sortino),
            "maxDrawdownPct": pct(mdd), "calmar": r2(calmar), "beta": r2(beta),
            "alphaAdjustedPct": pct(alpha_adj),
            "captureVsSpyPct": {"emAlta": pct(cap_up, 0), "emBaixa": pct(cap_dn, 0)},
            "monthsBeatingSpyPct": pct(months_beating, 0),
            "benchmarkMaxDrawdownPct": {k: pct(v, 1) for k, v in bench_mdd.items()},
            "worstDrawdownTroughs": [{"date": d.isoformat(), "drawdownPct": pct(v, 1)} for d, v in troughs[:3]],
            "taxaSemRiscoPct": RF * 100,
        },
        "seInvestidoNoIndice": {"teu": {"eur": r2(own_gain), "pct": pct(own_gain / last["dep"]) if last["dep"] > 0 else None},
                                **replica},
        "maximos": {
            "carteira": {"maximoEur": r2(peak_v["v"]), "data": peak_v["d"].isoformat(),
                         "vsMaximoPct": pct(last["v"] / peak_v["v"] - 1) if peak_v["v"] else None},
            "retornoTotal": {"maximoEur": r2(peak_pnl[1]), "data": peak_pnl[0].isoformat(),
                             "faltaRecuperarEur": r2(max(peak_pnl[1] - total_return, 0))},
        },
        "monthlyMatrix": dict(matrix),
        "bestMonth": {"ym": f"{best[0][0]}-{best[0][1]:02d}", "pct": pct(best[1])} if best else None,
        "worstMonth": {"ym": f"{worst[0][0]}-{worst[0][1]:02d}", "pct": pct(worst[1])} if worst else None,
        "currentStreak": {"months": streak, "direction": direction},
        "seasonality": seasonality,
        "annual": annual_rows,
        "chart": chart,
        "semCotacao": sorted(missing),
        "benchmarks": BENCH_LABEL,
        "metodologia": __doc__.strip(),
    }


def by_position(events, book, today: date, fifo_open_cost: dict | None = None):
    """Resultado por posição (aberta ou fechada): investido, recebido, valor, P&L, ROI, IRR."""
    acc = defaultdict(lambda: {"buys": 0.0, "sells": 0.0, "divs": 0.0, "fees": 0.0,
                               "qty": 0.0, "flows": [], "first": None, "last": None,
                               "ticker": None, "name": None, "isin": None})
    for e in sorted(events, key=lambda e: e["time"]):
        t = e["type"]
        if t not in ("BUY", "SELL", "DIVIDEND", "SPLIT_IN", "SPLIT_OUT"):
            continue
        k = instrument_key(e)
        a = acc[k]
        a["ticker"] = a["ticker"] or e.get("ticker")
        a["name"] = e.get("name") or a["name"]
        a["isin"] = e.get("isin")
        d = to_date(e["date"])
        a["first"] = a["first"] or d
        a["last"] = d
        v = e.get("totalEur") or 0
        if t == "BUY":
            a["buys"] += v; a["qty"] += e.get("qty") or 0; a["flows"].append((d, -v))
            a["fees"] += e.get("feesEur") or 0
        elif t == "SELL":
            a["sells"] += v; a["qty"] -= e.get("qty") or 0; a["flows"].append((d, v))
            a["fees"] += e.get("feesEur") or 0
        elif t == "DIVIDEND":
            a["divs"] += v; a["flows"].append((d, v))
        elif t == "SPLIT_IN":
            a["qty"] += e.get("qty") or 0
        elif t == "SPLIT_OUT":
            a["qty"] -= e.get("qty") or 0

    out = []
    for k, a in acc.items():
        if a["buys"] == 0 and a["divs"] == 0:
            continue
        is_open = a["qty"] > 1e-6
        px = book.price_eur(k, today, today) if is_open else None
        value = a["qty"] * px if (is_open and px) else 0.0
        pnl = value + a["sells"] + a["divs"] - a["buys"]
        flows = a["flows"] + ([(today, value)] if value else [])
        held_days = ((today if is_open else a["last"]) - a["first"]).days
        irr = xirr(flows) if held_days >= 45 else None
        out.append({
            "key": k, "ticker": a["ticker"], "name": a["name"], "isin": a["isin"],
            "status": "aberta" if is_open else "fechada",
            "qty": r2(a["qty"], 6) if is_open else 0,
            "investedEur": r2(a["buys"]), "proceedsEur": r2(a["sells"]),
            "dividendsNetEur": r2(a["divs"]), "valueEur": r2(value),
            "pnlEur": r2(pnl), "roiPct": pct(pnl / a["buys"]) if a["buys"] else None,
            "irrPct": pct(irr), "feesEur": r2(a["fees"]),
            "firstDate": a["first"].isoformat(), "lastDate": a["last"].isoformat(),
            "heldDays": held_days,
            "openCostEur": r2((fifo_open_cost or {}).get(k)) if is_open else None,
        })
    out.sort(key=lambda x: -(x["pnlEur"] or 0))
    return out


def trading_stats(positions):
    closed = [p for p in positions if p["status"] == "fechada"]
    if not closed:
        return {"count": 0}
    wins = [p for p in closed if (p["pnlEur"] or 0) > 0]
    losses = [p for p in closed if (p["pnlEur"] or 0) <= 0]
    avg = lambda xs: statistics.mean(xs) if xs else None
    return {
        "count": len(closed),
        "winRatePct": round(100 * len(wins) / len(closed), 1),
        "totalPnlEur": r2(sum(p["pnlEur"] or 0 for p in closed)),
        "avgWinPct": r2(avg([p["roiPct"] for p in wins if p["roiPct"] is not None])),
        "avgLossPct": r2(avg([p["roiPct"] for p in losses if p["roiPct"] is not None])),
        "avgHeldDays": round(avg([p["heldDays"] for p in closed]) or 0),
        "best": sorted(closed, key=lambda p: -(p["pnlEur"] or 0))[:5],
        "worst": sorted(closed, key=lambda p: (p["pnlEur"] or 0))[:5],
    }
