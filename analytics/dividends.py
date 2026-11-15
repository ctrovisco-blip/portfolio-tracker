"""
Dividendos.

RECEBIDOS (exatos, do extrato): por ano, por mês, por posição — bruto,
retenção na fonte, líquido, % do custo já recuperado, peso no total — e a
variação ano a ano.

PREVISÃO (estimativa, do historial do emitente via Yahoo Finance): para
cada posição aberta, a frequência, o dividendo anual por ação (soma dos
últimos 12 meses), o próximo ex-dividendo previsto pela cadência, o yield
atual, o yield sobre o custo, o crescimento do dividendo a 3/5 anos, a
estabilidade e o payout ratio (fundamentais). O líquido aplica a taxa de
retenção que essa posição teve nos últimos 12 meses (ou a de convenção).
Nunca são valores garantidos.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from .ledger import instrument_key
from .util import isin_country, pct, r2, to_date

MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
PAY_LAG_DAYS = 21  # atraso típico entre ex-dividendo e pagamento (estimado)


def enrich_gross(events, book):
    """Completa grossEur/withholdingEur quando a fonte não os traz (API JSON)."""
    for e in events:
        if e["type"] != "DIVIDEND" or e.get("grossEur") is not None:
            continue
        net = e.get("totalEur") or 0
        g_eur = None
        if e.get("grossNative"):
            g_eur = book.to_eur(e["grossNative"], e.get("nativeCcy") or "EUR", to_date(e["date"]))
        if g_eur is None or g_eur < net:
            g_eur = net
        e["grossEur"] = round(g_eur, 6)
        e["withholdingEur"] = round(g_eur - net, 6)
        e["grossEstimated"] = True
    return events


def _freq(dates):
    """Pagamentos por ano a partir das datas dos últimos 2 anos."""
    if len(dates) < 2:
        return 1 if dates else 0
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    g = statistics.median(gaps)
    for f, lo, hi in ((12, 20, 45), (4, 70, 120), (2, 150, 230), (1, 300, 420)):
        if lo <= g <= hi:
            return f
    return max(1, round(365 / g)) if g else 1


def compute(events, book, today: date, open_positions: dict, fundamentals=None, rules=None):
    """
    open_positions: key → {"qty", "costEur", "ticker", "name", "valueEur", "display"}
    fundamentals:   display_ticker → {payoutRatio, ...} (data/fundamentals.json)
    """
    fundamentals = fundamentals or {}
    divs = [e for e in events if e["type"] == "DIVIDEND"]

    # ── RECEBIDOS ──────────────────────────────────────────────────────────
    by_year = defaultdict(lambda: {"grossEur": 0.0, "taxEur": 0.0, "netEur": 0.0, "count": 0})
    by_month = defaultdict(lambda: defaultdict(float))
    by_pos = defaultdict(lambda: {"grossEur": 0.0, "taxEur": 0.0, "netEur": 0.0, "count": 0,
                                  "ticker": None, "name": None, "isin": None, "last12Gross": 0.0, "last12Tax": 0.0,
                                  "byYear": defaultdict(float)})
    total_net = 0.0
    for e in divs:
        d = to_date(e["date"])
        g, w, n = e.get("grossEur") or 0, e.get("withholdingEur") or 0, e.get("totalEur") or 0
        y = by_year[d.year]
        y["grossEur"] += g; y["taxEur"] += w; y["netEur"] += n; y["count"] += 1
        by_month[str(d.year)][MONTHS_PT[d.month - 1]] += n
        p = by_pos[instrument_key(e)]
        p["ticker"] = p["ticker"] or e.get("ticker"); p["name"] = e.get("name") or p["name"]; p["isin"] = e.get("isin")
        p["grossEur"] += g; p["taxEur"] += w; p["netEur"] += n; p["count"] += 1
        p["byYear"][d.year] += n
        if d > today - timedelta(days=365):
            p["last12Gross"] += g; p["last12Tax"] += w
        total_net += n

    invested = defaultdict(float)
    for e in events:
        if e["type"] == "BUY":
            invested[instrument_key(e)] += e.get("totalEur") or 0

    years_sorted = sorted(by_year)
    year_rows = []
    for i, y in enumerate(years_sorted):
        v = by_year[y]
        prev = by_year[years_sorted[i - 1]]["netEur"] if i else None
        year_rows.append({"ano": y, "grossEur": r2(v["grossEur"]), "taxEur": r2(v["taxEur"]),
                          "netEur": r2(v["netEur"]), "pagamentos": v["count"],
                          "variacaoPct": pct(v["netEur"] / prev - 1) if prev else None,
                          "parcial": y == today.year})

    pos_rows = []
    for k, p in by_pos.items():
        inv = invested.get(k) or 0
        pos_rows.append({
            "key": k, "ticker": p["ticker"], "name": p["name"], "isin": p["isin"],
            "grossEur": r2(p["grossEur"]), "taxEur": r2(p["taxEur"]), "netEur": r2(p["netEur"]),
            "withholdingPct": pct(p["taxEur"] / p["grossEur"], 1) if p["grossEur"] else None,
            "pagamentos": p["count"],
            "costRecoveredPct": pct(p["netEur"] / inv) if inv else None,
            "shareOfTotalPct": pct(p["netEur"] / total_net) if total_net else None,
            "aberta": k in open_positions,
            "porAno": {str(y): r2(v) for y, v in sorted(p["byYear"].items())},
        })
    pos_rows.sort(key=lambda x: -(x["netEur"] or 0))

    # Variação ano a ano por posição: quem fez crescer (ou cair) o rendimento
    yoy = None
    if len(years_sorted) >= 2:
        y1 = today.year - 1
        y0 = y1 - 1
        if y1 in by_year and y0 in by_year:
            contrib = []
            for k, p in by_pos.items():
                a, b = p["byYear"].get(y0, 0), p["byYear"].get(y1, 0)
                if a or b:
                    motivo = "nova posição" if not a else ("deixou de pagar / vendida" if not b else "variação")
                    contrib.append({"ticker": p["ticker"], "de": r2(a), "para": r2(b), "deltaEur": r2(b - a), "motivo": motivo})
            contrib.sort(key=lambda x: -abs(x["deltaEur"] or 0))
            yoy = {"de": y0, "para": y1, "deltaEur": r2(by_year[y1]["netEur"] - by_year[y0]["netEur"]),
                   "porPosicao": contrib[:15]}

    # ── PREVISÃO ───────────────────────────────────────────────────────────
    forecast = []
    calendar = []
    proj_month = defaultdict(lambda: {"grossEur": 0.0, "netEur": 0.0})
    horizon = today + timedelta(days=365)
    for k, op in open_positions.items():
        hist, ccy = book.dividends_native(k)
        if not hist:
            continue
        dates = sorted(hist)
        recent = [d for d in dates if d > today - timedelta(days=730)]
        if not recent:
            continue  # deixou de pagar
        f = _freq(recent)
        ttm = [d for d in dates if d > today - timedelta(days=365)]
        annual_dps = sum(hist[d] for d in ttm) if ttm else 0
        if not ttm or (f and len(ttm) < f * 0.5):
            # historial irregular: último pagamento × frequência
            annual_dps = hist[dates[-1]] * (f or 1)
        if annual_dps <= 0:
            continue
        annual_eur = book.to_eur(annual_dps * op["qty"], ccy, today)
        if annual_eur is None:
            continue
        # cadência → próximos ex-dividendos
        gaps = [(b - a).days for a, b in zip(recent, recent[1:])]
        gap = int(statistics.median(gaps)) if gaps else 365
        nxt = dates[-1]
        upcoming = []
        guard = 0
        while guard < 30:
            guard += 1
            nxt = nxt + timedelta(days=gap)
            if nxt <= today:
                continue
            if nxt > horizon:
                break
            upcoming.append(nxt)
        # retenção esperada
        pr = by_pos.get(k)
        if pr and pr["last12Gross"] > 0:
            wrate = pr["last12Tax"] / pr["last12Gross"]
        elif pr and pr["grossEur"] > 0:
            wrate = pr["taxEur"] / pr["grossEur"]
        else:
            c = isin_country(op.get("isin"))
            wrate = 0.0 if c in ("GB", None) else (rules.treaty.get(c, 0.15) if rules else 0.15)
        per_pay = annual_eur / (f or 1)
        for d in upcoming:
            pay = d + timedelta(days=PAY_LAG_DAYS)
            calendar.append({"ticker": op.get("display") or op.get("ticker"), "exDate": d.isoformat(),
                             "payDate": pay.isoformat(), "estimado": True,
                             "brutoEur": r2(per_pay), "liquidoEur": r2(per_pay * (1 - wrate))})
            mk = f"{pay.year}-{pay.month:02d}"
            proj_month[mk]["grossEur"] += per_pay
            proj_month[mk]["netEur"] += per_pay * (1 - wrate)
        # crescimento e estabilidade (anos civis completos)
        yearly = defaultdict(float)
        for d, v in hist.items():
            yearly[d.year] += v
        full = sorted(y for y in yearly if y < today.year)
        def cagr(n):
            if len(full) < n + 1:
                return None
            a, b = yearly[full[-1 - n]], yearly[full[-1]]
            return (b / a) ** (1 / n) - 1 if a > 0 and b > 0 else None
        cuts = sum(1 for a, b in zip(full, full[1:]) if yearly[b] < yearly[a] * 0.95)
        stability = round(100 * (1 - cuts / (len(full) - 1))) if len(full) > 1 else None
        fund = fundamentals.get(op.get("display") or "", {}) or {}
        px = op["valueEur"] / op["qty"] if op.get("qty") and op.get("valueEur") else None
        dps_eur = annual_eur / op["qty"] if op["qty"] else None
        forecast.append({
            "key": k, "ticker": op.get("display") or op.get("ticker"), "name": op.get("name"),
            "frequency": f, "frequencyLabel": {12: "mensal", 4: "trimestral", 2: "semestral", 1: "anual"}.get(f, f"{f}×/ano"),
            "annualDpsNative": r2(annual_dps, 4), "ccy": ccy,
            "estimatedAnnualIncomeEur": r2(annual_eur),
            "estimatedAnnualIncomeNetEur": r2(annual_eur * (1 - wrate)),
            "withholdingRateAppliedPct": pct(wrate, 1),
            "currentYieldPct": pct(dps_eur / px) if px and dps_eur else None,
            "yieldOnCostPct": pct(annual_eur / op["costEur"]) if op.get("costEur") else None,
            "lastExDate": dates[-1].isoformat(),
            "nextExDate": upcoming[0].isoformat() if upcoming else None,
            "nextPayDate": (upcoming[0] + timedelta(days=PAY_LAG_DAYS)).isoformat() if upcoming else None,
            "dpsCagr3yPct": pct(cagr(3), 1), "dpsCagr5yPct": pct(cagr(5), 1),
            "stability": stability,
            "payoutRatioPct": r2(fund.get("payoutRatio")) if fund.get("payoutRatio") is not None else None,
            "historicoAnual": {str(y): r2(yearly[y], 4) for y in full[-10:]},
        })
    forecast.sort(key=lambda x: -(x["estimatedAnnualIncomeEur"] or 0))
    calendar.sort(key=lambda x: x["exDate"])

    total_annual = sum(x["estimatedAnnualIncomeEur"] or 0 for x in forecast)
    total_annual_net = sum(x["estimatedAnnualIncomeNetEur"] or 0 for x in forecast)
    port_value = sum(op.get("valueEur") or 0 for op in open_positions.values())
    port_cost = sum(op.get("costEur") or 0 for op in open_positions.values())
    for x in forecast:
        x["shareOfIncomePct"] = pct((x["estimatedAnnualIncomeEur"] or 0) / total_annual) if total_annual else None

    # Até ao fim do ano: o que já entrou + o previsto
    eoy = date(today.year, 12, 31)
    falta = sum(c["liquidoEur"] or 0 for c in calendar if to_date(c["payDate"]) <= eoy)
    recebido_ano = by_year.get(today.year, {}).get("netEur", 0) if today.year in by_year else 0

    return {
        "available": True,
        "asOf": today.isoformat(),
        "recebido": {
            "totalGrossEur": r2(sum(v["grossEur"] for v in by_year.values())),
            "totalTaxEur": r2(sum(v["taxEur"] for v in by_year.values())),
            "totalNetEur": r2(total_net),
            "porAno": year_rows,
            "porMes": {y: {m: r2(v) for m, v in ms.items()} for y, ms in by_month.items()},
            "porPosicao": pos_rows,
            "variacaoAnual": yoy,
            "brutoEstimado": any(e.get("grossEstimated") for e in divs),
        },
        "previsao": {
            "estimatedAnnualIncomeEur": r2(total_annual),
            "estimatedAnnualIncomeNetEur": r2(total_annual_net),
            "estimatedMonthlyAverageNetEur": r2(total_annual_net / 12),
            "portfolioYieldPct": pct(total_annual / port_value) if port_value else None,
            "yieldOnCostPct": pct(total_annual / port_cost) if port_cost else None,
            "payingPositions": len(forecast), "totalPositions": len(open_positions),
            "topPayerSharePct": forecast[0]["shareOfIncomePct"] if forecast else None,
            "posicoes": forecast,
            "calendario": calendar,
            "porMes": {k: {"grossEur": r2(v["grossEur"]), "netEur": r2(v["netEur"])} for k, v in sorted(proj_month.items())},
            "anoAtual": {"recebidoEur": r2(recebido_ano), "faltaReceberEur": r2(falta),
                         "totalPrevistoEur": r2(recebido_ano + falta)},
        },
        "metodologia": __doc__.strip(),
    }
