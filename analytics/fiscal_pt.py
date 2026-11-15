"""
Fiscalidade portuguesa (IRS de residente, Categoria E e G).

  • Mais-valias de valores mobiliários — FIFO por lote, em EUR, com os
    encargos de compra e de venda (art. 51.º CIRS). Saldo anual único
    tributado a 28% (art. 72.º n.º 1 al. c)), com a exclusão parcial por
    tempo de detenção da Lei 31/2024 (10/20/30% aos 2/5/8 anos) e a
    correção monetária das ações com mais de 24 meses (art. 50.º).
  • Dividendos — 28% sobre o bruto com crédito do imposto retido lá fora,
    limitado pela convenção (art. 81.º). Dividendos portugueses: a retenção
    de 28% é liberatória.
  • Juros — 28% sobre o bruto quando não houve retenção em Portugal.

Câmbio: usa a taxa da corretora (a AT pede a do Banco de Portugal no dia;
a diferença costuma ser de cêntimos). Estimativa informativa.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date

from .ledger import instrument_key
from .util import COUNTRY_NAME_PT, ISIN_COUNTRY_NUM, add_years, isin_country, r2, to_date

DEFAULT_CONFIG_PATH = "data/fiscal_config.json"

_ETF_WORDS = ("etf", "ucits", "ishares", "vanguard", "xtrackers", "spdr", "amundi", "invesco",
              "wisdomtree", "lyxor", "etc", "physical", "xetra-gold", "global x", "vaneck", "hanetf")


def load_config(path=DEFAULT_CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def asset_type(name: str | None, isin: str | None, sector: str | None = None) -> str:
    n = (name or "").lower()
    if sector and "etf" in sector.lower():
        return "etf"
    if any(w in n for w in _ETF_WORDS) or "(acc)" in n or "(dist)" in n:
        return "etf"
    return "acao"


class TaxRules:
    def __init__(self, cfg):
        self.cfg = cfg
        base = cfg.get("taxaAutonomaPct", 28) / 100
        self.rate = base * (0.7 if cfg.get("regiao") == "acores" else 1)
        esc = cfg["escaloesDetencao"]
        self.tier_since = to_date(esc["aplicaDesde"])
        self.tiers = sorted(esc["escalas"], key=lambda t: t["anosMin"])
        cm = cfg.get("correcaoMonetaria", {})
        self.cm_months = cm.get("mesesMinimos", 24)
        self.cm_coef = {int(k): float(v) for k, v in (cm.get("coeficientes") or {}).items()}
        dv = cfg.get("dividendos", {})
        self.treaty = {k: v / 100 for k, v in (dv.get("taxaConvencaoPct") or {}).items() if not k.startswith("_")}
        self.no_treaty_cap = dv.get("semConvencaoLimitePct", 28) / 100

    def tier(self, buy: date, sell: date):
        """(label, exclusão) para um lote comprado em `buy` e vendido em `sell`."""
        if sell < self.tier_since:
            return self.tiers[0]["label"], 0.0
        chosen = self.tiers[0]
        for t in self.tiers:
            if sell >= add_years(buy, t["anosMin"]):
                chosen = t
        return chosen["label"], chosen["exclusaoPct"] / 100

    def next_tier(self, buy: date, today: date):
        for t in self.tiers:
            when = add_years(buy, t["anosMin"])
            if when > today:
                return t, when
        return None, None

    def monetary_coef(self, kind: str, buy: date, sell: date):
        if kind != "acao":
            return 1.0
        months = (sell.year - buy.year) * 12 + (sell.month - buy.month) - (1 if sell.day < buy.day else 0)
        if months <= self.cm_months:
            return 1.0
        return self.cm_coef.get(buy.year, 1.0)

    def dividend_irs(self, gross, withheld, country):
        """IRS ainda devido em Portugal sobre um dividendo (com o crédito internacional)."""
        if gross <= 0:
            return 0.0, 0.0
        if country == "PT":
            return 0.0, withheld
        cap = self.treaty.get(country, self.no_treaty_cap)
        credit = min(withheld, cap * gross, self.rate * gross)
        return max(self.rate * gross - credit, 0.0), credit


# ─── FIFO ───────────────────────────────────────────────────────────────────

def run_fifo(events, meta_by_key=None):
    """
    Devolve (lotes_abertos, vendas_por_lote, avisos).
    Cada lote: {key, date, qty, costEur, feesEur}
    Cada parcela vendida: {key, buyDate, sellDate, qty, costEur, buyFeesEur,
                           proceedsEur, sellFeesEur, ...}
    """
    meta_by_key = meta_by_key or {}
    lots = defaultdict(list)
    pieces, warnings = [], []
    pending_split = {}
    info = {}
    for e in sorted(events, key=lambda e: (e["time"], 0 if e["type"] in ("BUY", "SPLIT_OUT") else 1)):
        t, k = e["type"], instrument_key(e)
        if t in ("BUY", "SELL", "SPLIT_IN", "SPLIT_OUT"):
            info.setdefault(k, {"ticker": e.get("ticker"), "name": e.get("name"), "isin": e.get("isin")})
            if e.get("name"):
                info[k]["name"] = e["name"]
        q = e.get("qty") or 0
        if t == "BUY" and q > 0:
            lots[k].append({"key": k, "date": to_date(e["date"]), "qty": q,
                            "costEur": e.get("totalEur") or 0.0, "feesEur": e.get("feesEur") or 0.0})
        elif t == "SELL" and q > 0:
            remaining = q
            proceeds, sfees = e.get("totalEur") or 0.0, e.get("feesEur") or 0.0
            sd = to_date(e["date"])
            while remaining > 1e-9 and lots[k]:
                lot = lots[k][0]
                take = min(lot["qty"], remaining)
                frac_lot = take / lot["qty"]
                frac_sale = take / q
                pieces.append({
                    "key": k, "buyDate": lot["date"], "sellDate": sd, "qty": take,
                    "costEur": lot["costEur"] * frac_lot, "buyFeesEur": lot["feesEur"] * frac_lot,
                    "proceedsEur": proceeds * frac_sale, "sellFeesEur": sfees * frac_sale,
                    "brokerResultEur": (e.get("resultEur") or 0) * frac_sale,
                })
                lot["costEur"] -= lot["costEur"] * frac_lot
                lot["feesEur"] -= lot["feesEur"] * frac_lot
                lot["qty"] -= take
                remaining -= take
                if lot["qty"] <= 1e-9:
                    lots[k].pop(0)
            if remaining > 1e-6:
                warnings.append(f"{info.get(k, {}).get('ticker') or k}: venda de {remaining:.6f} unidades sem compra correspondente em {sd} (custo desconhecido — fora do apuramento)")
        elif t == "SPLIT_OUT" and q > 0:
            pending_split.setdefault(e["date"], []).append((k, q, lots.pop(k, [])))
        elif t == "SPLIT_IN" and q > 0:
            cands = pending_split.get(e["date"], [])
            src = next((c for c in cands if c[0] == k), cands[0] if cands else None)
            if src:
                cands.remove(src)
                old_k, old_q, old_lots = src
                ratio = q / old_q if old_q else 1
                for lot in old_lots:
                    lot["qty"] *= ratio
                    lot["key"] = k
                lots[k].extend(old_lots)
                lots[k].sort(key=lambda l: l["date"])
            else:
                lots[k].append({"key": k, "date": to_date(e["date"]), "qty": q,
                                "costEur": e.get("totalEur") or 0.0, "feesEur": 0.0})
    for d, rest in pending_split.items():
        for k, q, l in rest:
            warnings.append(f"{info.get(k, {}).get('ticker') or k}: evento de split/fecho em {d} sem abertura correspondente")
    open_lots = {k: v for k, v in lots.items() if v}
    return open_lots, pieces, warnings, info


# ─── apuramento ─────────────────────────────────────────────────────────────

def _annual_tax(pieces_year, rules):
    """IRS de mais-valias de um ano a partir das parcelas (já com tier e ganho tributável)."""
    by_tier = defaultdict(lambda: {"gainsEur": 0.0, "lossesEur": 0.0, "exclusao": 0.0})
    for p in pieces_year:
        t = by_tier[p["tier"]]
        t["exclusao"] = p["exclusao"]
        g = p["taxableBaseEur"]
        if g >= 0:
            t["gainsEur"] += g
        else:
            t["lossesEur"] += -g
    taxable = 0.0
    tiers = []
    for label, t in by_tier.items():
        base = t["gainsEur"] - t["lossesEur"]
        tb = base * (1 - t["exclusao"]) if base > 0 else base
        taxable += tb
        tiers.append({"label": label, "ratePct": r2(rules.rate * (1 - t["exclusao"]) * 100, 1),
                      "gainsEur": r2(t["gainsEur"]), "lossesEur": r2(t["lossesEur"]),
                      "baseEur": r2(base), "irsEur": r2(max(tb, 0) * rules.rate)})
    tiers.sort(key=lambda x: x["label"])
    return max(taxable, 0.0) * rules.rate, taxable, tiers


def _enrich_piece(p, rules, info, sectors):
    i = info.get(p["key"], {})
    kind = asset_type(i.get("name"), i.get("isin"), sectors.get(p["key"]))
    label, excl = rules.tier(p["buyDate"], p["sellDate"])
    coef = rules.monetary_coef(kind, p["buyDate"], p["sellDate"])
    cost_corr = p["costEur"] * coef
    country = isin_country(i.get("isin"))
    p.update({
        "ticker": i.get("ticker"), "name": i.get("name"), "isin": i.get("isin"),
        "tipo": kind, "pais": country,
        "gainEur": p["proceedsEur"] - p["costEur"],
        "correcaoMonetariaEur": cost_corr - p["costEur"],
        "taxableBaseEur": p["proceedsEur"] - cost_corr,
        "tier": label, "exclusao": excl,
        "holdingDays": (p["sellDate"] - p["buyDate"]).days,
        "anexo": "G" if country == "PT" else "J",
    })
    return p


def compute(events, book, today: date, cfg=None, sectors=None):
    rules = TaxRules(cfg or load_config())
    sectors = sectors or {}
    open_lots, pieces, warnings, info = run_fifo(events)
    for p in pieces:
        _enrich_piece(p, rules, info, sectors)

    years = sorted({p["sellDate"].year for p in pieces} |
                   {to_date(e["date"]).year for e in events if e["type"] in ("DIVIDEND", "INTEREST", "BUY")})

    # Dividendos e juros por ano
    div_by_year = defaultdict(lambda: {"grossEur": 0.0, "withheldEur": 0.0, "irsEur": 0.0, "creditEur": 0.0})
    div_by_country = defaultdict(lambda: defaultdict(lambda: {"grossEur": 0.0, "withheldEur": 0.0, "creditEur": 0.0}))
    int_by_year = defaultdict(float)
    fees_by_year = defaultdict(float)
    orders_by_year = defaultdict(int)
    for e in events:
        y = to_date(e["date"]).year
        if e["type"] == "DIVIDEND":
            gross = e.get("grossEur") or e.get("totalEur") or 0
            wh = e.get("withholdingEur") or max(gross - (e.get("totalEur") or 0), 0)
            c = isin_country(e.get("isin"))
            irs, credit = rules.dividend_irs(gross, wh, c)
            d = div_by_year[y]
            d["grossEur"] += gross; d["withheldEur"] += wh; d["irsEur"] += irs; d["creditEur"] += credit
            dc = div_by_country[y][c or "?"]
            dc["grossEur"] += gross; dc["withheldEur"] += wh; dc["creditEur"] += credit
        elif e["type"] == "INTEREST":
            int_by_year[y] += e.get("totalEur") or 0
        elif e["type"] in ("BUY", "SELL"):
            fees_by_year[y] += e.get("feesEur") or 0
            orders_by_year[y] += 1
        elif e["type"] == "FEE":
            fees_by_year[y] += e.get("totalEur") or 0

    by_year = []
    for y in years:
        py = [p for p in pieces if p["sellDate"].year == y]
        irs_mv, taxable, tiers = _annual_tax(py, rules)
        gains = sum(p["gainEur"] for p in py if p["gainEur"] > 0)
        losses = -sum(p["gainEur"] for p in py if p["gainEur"] < 0)
        d = div_by_year.get(y, {"grossEur": 0, "withheldEur": 0, "irsEur": 0, "creditEur": 0})
        irs_int = int_by_year.get(y, 0) * rules.rate
        by_year.append({
            "ano": y,
            "realizedGainsEur": r2(gains), "realizedLossesEur": r2(losses),
            "netRealizedEur": r2(gains - losses), "taxableEur": r2(taxable),
            "correcaoMonetariaEur": r2(sum(p["correcaoMonetariaEur"] for p in py)),
            "irsRealizedEur": r2(irs_mv), "byTier": tiers,
            "dividendsGrossEur": r2(d["grossEur"]), "dividendTaxEur": r2(d["withheldEur"]),
            "dividendCreditEur": r2(d["creditEur"]), "irsDividendsEur": r2(d["irsEur"]),
            "jurosBrutosEur": r2(int_by_year.get(y, 0)), "irsJurosEur": r2(irs_int),
            "commissionsEur": r2(fees_by_year.get(y, 0)), "orderCount": orders_by_year.get(y, 0),
            "irsEstimateEur": r2(irs_mv + d["irsEur"] + irs_int),
            "vendas": len(py),
            "prejuizoAReportarEur": r2(-taxable) if taxable < 0 else 0,
        })

    # ── lotes abertos a preços de hoje ─────────────────────────────────────
    lots_out = []
    lei31_saving = 0.0
    nearest = None
    for k, ls in open_lots.items():
        i = info.get(k, {})
        kind = asset_type(i.get("name"), i.get("isin"), sectors.get(k))
        px = book.price_eur(k, today, today)
        for lot in ls:
            value = lot["qty"] * px if px else None
            gain = (value - lot["costEur"]) if value is not None else None
            label, excl = rules.tier(lot["date"], today)
            nt, when = rules.next_tier(lot["date"], today)
            saving_next = None
            if nt and gain and gain > 0:
                saving_next = gain * rules.rate * (nt["exclusaoPct"] / 100 - excl)
            if gain and gain > 0:
                lei31_saving += gain * rules.rate * excl
            row = {
                "key": k, "ticker": i.get("ticker"), "name": i.get("name"), "isin": i.get("isin"),
                "tipo": kind, "date": lot["date"].isoformat(), "qty": r2(lot["qty"], 6),
                "costEur": r2(lot["costEur"]), "valueEur": r2(value), "gainEur": r2(gain),
                "holdingYears": r2((today - lot["date"]).days / 365.25, 2),
                "tier": label, "ratePct": r2(rules.rate * (1 - excl) * 100, 1),
                "nextTier": nt["label"] if nt else None,
                "nextTierRatePct": r2(rules.rate * (1 - nt["exclusaoPct"] / 100) * 100, 1) if nt else None,
                "nextTierDate": when.isoformat() if when else None,
                "daysToNextTier": (when - today).days if when else None,
                "savingAtNextTierEur": r2(saving_next),
            }
            lots_out.append(row)
            if when and (nearest is None or when < to_date(nearest["date"])):
                nearest = {"ticker": i.get("ticker"), "date": when.isoformat(),
                           "toRatePct": row["nextTierRatePct"], "units": row["qty"],
                           "savingEur": r2(saving_next), "dias": (when - today).days}

    # ── simulação: vender hoje ─────────────────────────────────────────────
    def simulate(keys=None, units=None):
        """IRS do ano antes e depois de vender hoje as posições `keys` (todas por omissão)."""
        cur_year = [p for p in pieces if p["sellDate"].year == today.year]
        before, _, _ = _annual_tax(cur_year, rules)
        extra = []
        for k, ls in open_lots.items():
            if keys is not None and k not in keys:
                continue
            px = book.price_eur(k, today, today)
            if not px:
                continue
            left = (units or {}).get(k)
            for lot in ls:
                q = lot["qty"] if left is None else min(lot["qty"], left)
                if q <= 1e-9:
                    break
                frac = q / lot["qty"]
                p = {"key": k, "buyDate": lot["date"], "sellDate": today, "qty": q,
                     "costEur": lot["costEur"] * frac, "buyFeesEur": lot["feesEur"] * frac,
                     "proceedsEur": q * px, "sellFeesEur": 0.0}
                extra.append(_enrich_piece(p, rules, info, sectors))
                if left is not None:
                    left -= q
        after, _, _ = _annual_tax(cur_year + extra, rules)
        mv = sum(p["proceedsEur"] for p in extra)
        return {"valorDeMercadoEur": r2(mv), "ganhoEur": r2(sum(p["gainEur"] for p in extra)),
                "irsDoAnoSemVenderEur": r2(before), "irsDoAnoVendendoEur": r2(after),
                "irsDaVendaEur": r2(after - before), "valorLiquidoEur": r2(mv - (after - before))}

    sell_all = simulate()

    # ── otimização por perdas ──────────────────────────────────────────────
    pos_unreal = defaultdict(lambda: {"costEur": 0.0, "valueEur": 0.0})
    for l in lots_out:
        if l["valueEur"] is None:
            continue
        pos_unreal[l["key"]]["costEur"] += l["costEur"]
        pos_unreal[l["key"]]["valueEur"] += l["valueEur"]
    losers = [k for k, v in pos_unreal.items() if v["valueEur"] < v["costEur"]]
    tlh_sim = simulate(set(losers)) if losers else None
    tlh = {
        "posicoesEmPerda": [{"ticker": info[k].get("ticker"), "name": info[k].get("name"),
                             "perdaEur": r2(pos_unreal[k]["valueEur"] - pos_unreal[k]["costEur"])}
                            for k in sorted(losers, key=lambda k: pos_unreal[k]["valueEur"] - pos_unreal[k]["costEur"])],
        "perdaPorRealizarEur": r2(sum(pos_unreal[k]["valueEur"] - pos_unreal[k]["costEur"] for k in losers)),
        "irsDoAnoAtualEur": tlh_sim["irsDoAnoSemVenderEur"] if tlh_sim else None,
        "irsVendendoAsPerdasEur": tlh_sim["irsDoAnoVendendoEur"] if tlh_sim else None,
        "poupancaPossivelEur": r2(tlh_sim["irsDoAnoSemVenderEur"] - tlh_sim["irsDoAnoVendendoEur"]) if tlh_sim else 0,
        "nota": "Estimativa aos preços atuais. Vender e recomprar logo a seguir não está proibido em Portugal, mas tem custos (comissões, spread, câmbio) e reinicia a contagem dos anos de detenção do lote.",
    }

    # ── rascunho das linhas da declaração ──────────────────────────────────
    decl = defaultdict(list)
    for p in pieces:
        y = p["sellDate"].year
        decl[y].append({
            "anexo": "Anexo G · Q9" if p["anexo"] == "G" else "Anexo J · Q9.2A",
            "codigo": "G01", "pais": ISIN_COUNTRY_NUM.get(p["pais"] or "", p["pais"]),
            "paisNome": COUNTRY_NAME_PT.get(p["pais"] or "", p["pais"]),
            "ticker": p["ticker"], "isin": p["isin"],
            "realizacaoData": p["sellDate"].isoformat(),
            "realizacaoValorEur": r2(p["proceedsEur"] + p["sellFeesEur"]),
            "aquisicaoData": p["buyDate"].isoformat(),
            "aquisicaoValorEur": r2(p["costEur"] - p["buyFeesEur"]),
            "despesasEncargosEur": r2(p["buyFeesEur"] + p["sellFeesEur"]),
            "resultadoEur": r2(p["gainEur"]),
        })
    div_decl = {}
    for y, cs in div_by_country.items():
        div_decl[y] = [{"anexo": "Anexo G · Q4 (retenção liberatória, opcional)" if c == "PT" else "Anexo J · Q8A",
                        "codigo": "E11", "pais": ISIN_COUNTRY_NUM.get(c, c), "paisNome": COUNTRY_NAME_PT.get(c, c),
                        "brutoEur": r2(v["grossEur"]), "impostoPagoEstrangeiroEur": r2(v["withheldEur"]),
                        "creditoAdmitidoEur": r2(v["creditEur"])}
                       for c, v in sorted(cs.items(), key=lambda x: -x[1]["grossEur"])]

    realized_rows = [{
        "ticker": p["ticker"], "name": p["name"], "isin": p["isin"], "tipo": p["tipo"],
        "buyDate": p["buyDate"].isoformat(), "sellDate": p["sellDate"].isoformat(),
        "qty": r2(p["qty"], 6), "costEur": r2(p["costEur"]), "proceedsEur": r2(p["proceedsEur"]),
        "gainEur": r2(p["gainEur"]), "brokerResultEur": r2(p["brokerResultEur"]),
        "holdingDays": p["holdingDays"], "tier": p["tier"], "anexo": p["anexo"],
    } for p in sorted(pieces, key=lambda p: p["sellDate"], reverse=True)]

    cur = next((y for y in by_year if y["ano"] == today.year), None)
    open_cost = defaultdict(float)
    for k, ls in open_lots.items():
        open_cost[k] = sum(l["costEur"] for l in ls)

    return {
        "available": True,
        "asOf": today.isoformat(),
        "byYear": by_year,
        "irsEstimadoDoAno": {
            "ano": today.year,
            "maisValiasEur": cur["irsRealizedEur"] if cur else 0,
            "dividendosEur": cur["irsDividendsEur"] if cur else 0,
            "jurosEur": cur["irsJurosEur"] if cur else 0,
            "totalEur": cur["irsEstimateEur"] if cur else 0,
        },
        "totais": {
            "irsEstimateEur": r2(sum(y["irsEstimateEur"] or 0 for y in by_year)),
            "netRealizedEur": r2(sum(y["netRealizedEur"] or 0 for y in by_year)),
            "dividendsGrossEur": r2(sum(y["dividendsGrossEur"] or 0 for y in by_year)),
        },
        "lei31": {
            "escalas": [{"label": t["label"], "ratePct": r2(rules.rate * (1 - t["exclusaoPct"] / 100) * 100, 1)}
                        for t in rules.tiers],
            "poupancaEstimadaEur": r2(lei31_saving),
            "proximaTransicao": nearest,
        },
        "lotesAbertos": sorted(lots_out, key=lambda l: (l["ticker"] or "", l["date"])),
        "vendasPorLote": realized_rows,
        "seVenderTudoHoje": sell_all,
        "taxLossHarvest": tlh,
        "declaracaoRascunho": {str(y): rows for y, rows in decl.items()},
        "dividendosPorPais": {str(y): rows for y, rows in div_decl.items()},
        "avisos": warnings,
        "anexos": (cfg or load_config()).get("anexos"),
        "basesLegais": [
            "Art. 72.º n.º 1 CIRS — taxa autónoma de 28% (saldo das mais-valias; rendimentos de capitais sem retenção em PT)",
            "Art. 43.º n.º 5 CIRS (Lei 31/2024) — exclusão de 10/20/30% do ganho aos 2/5/8 anos de detenção",
            "Art. 50.º CIRS — correção monetária do custo das ações com mais de 24 meses",
            "Art. 51.º CIRS — encargos de compra e venda dedutíveis",
            "Art. 81.º CIRS — crédito por dupla tributação internacional",
            "Art. 22.º CIRS — opção de englobamento (não simulada aqui)",
        ],
        "metodologia": __doc__.strip(),
        "_openCost": dict(open_cost),
        "_simulate": simulate,
    }
