"""
Corre os motores de análise e escreve data/analytics.json (lido por build_html.py).

Lê: data/transactions.json, data/price_history.json, data/positions.json,
    data/account.json, data/fx.json, data/fundamentals.json, metadata.json,
    data/t212_map.json, data/orders.json, data/fiscal_config.json
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analytics import dividends, fiscal_pt, ledger, performance  # noqa: E402
from analytics.prices import PriceBook, load_price_history  # noqa: E402
from analytics.util import r2  # noqa: E402

OUT = "data/analytics.json"


def jload(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def isin_to_display():
    """ISIN → ticker de apresentação (o do dashboard), via orders.json + t212_map.json."""
    tmap = jload("data/t212_map.json", {})
    out = {}
    for o in jload("data/orders.json", []) or []:
        inst = o.get("instrument") or {}
        disp = tmap.get(o.get("ticker"))
        if inst.get("isin") and disp:
            out[inst["isin"]] = disp
    return out


def build(today=None, write=True):
    today = today or datetime.now(timezone.utc).date()
    events = ledger.load_transactions()
    if not events:
        res = {"available": False, "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "motivo": "Ainda não há histórico de transações (data/transactions.json). "
                         "Corre fetch_history.py com as chaves da T212 ou coloca extratos CSV em data/statements/."}
        if write:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False)
        print(res["motivo"])
        return res

    history = load_price_history()
    book = PriceBook(history, events)
    meta = jload("metadata.json", {})
    fx_now = jload("data/fx.json", {"€": 1.0})
    positions = jload("data/positions.json", []) or []
    fundamentals = jload("data/fundamentals.json", {}) or {}
    account = jload("data/account.json")
    disp = isin_to_display()

    # Cotação ao vivo da T212 para hoje (mais fresca que o fecho do Yahoo)
    pos_by_disp = {p["ticker"]: p for p in positions}
    for isin, d in disp.items():
        p = pos_by_disp.get(d)
        if p and p.get("curPrice"):
            book.overrides[isin] = p["curPrice"] * fx_now.get(p.get("cur", "€"), 1.0)

    sectors = {isin: (meta.get(d) or {}).get("sector") for isin, d in disp.items()}
    dividends.enrich_gross(events, book)

    cfg = fiscal_pt.load_config()
    fiscal = fiscal_pt.compute(events, book, today, cfg, sectors)
    open_cost = fiscal.pop("_openCost")
    fiscal.pop("_simulate")

    live_cash = None
    if account and account.get("free") is not None:
        live_cash = sum(account.get(k) or 0 for k in ("free", "blocked", "pieCash"))
    perf = performance.compute(events, book, today, live_cash)
    by_pos = performance.by_position(events, book, today, open_cost)
    for p in by_pos:
        p["display"] = disp.get(p["isin"]) or p["ticker"]
    perf["porPosicao"] = by_pos
    perf["fechadas"] = performance.trading_stats(by_pos)

    qty_end = ledger.quantities_at_end(events)
    insts = ledger.instruments(events)
    open_positions = {}
    for k, q in qty_end.items():
        if q <= 0:
            continue
        px = book.price_eur(k, today, today)
        open_positions[k] = {"qty": q, "costEur": open_cost.get(k, 0.0), "valueEur": (q * px) if px else None,
                             "ticker": insts.get(k, {}).get("ticker"), "name": insts.get(k, {}).get("name"),
                             "isin": insts.get(k, {}).get("isin"), "display": disp.get(k) or insts.get(k, {}).get("ticker")}
    divs = dividends.compute(events, book, today, open_positions, fundamentals, fiscal_pt.TaxRules(cfg))

    # ── qualidade dos dados ────────────────────────────────────────────────
    mismatches = []
    disp_qty = {}
    for k, q in qty_end.items():
        d = disp.get(k)
        if d:
            disp_qty[d] = disp_qty.get(d, 0) + q
    for p in positions:
        lq = disp_qty.get(p["ticker"])
        if lq is None or abs(lq - p.get("qty", 0)) > 1e-3:
            mismatches.append({"ticker": p["ticker"], "corretora": p.get("qty"), "ledger": r2(lq, 6)})
    quality = {
        "eventos": len(events),
        "primeiroEvento": min(e["date"] for e in events),
        "ultimoEvento": max(e["date"] for e in events),
        "fontes": sorted({e.get("source") for e in events}),
        "semCotacaoYahoo": sorted(insts.get(k, {}).get("ticker") or k for k in book.fallback_used),
        "quantidadesDiferentes": mismatches,
        "avisos": fiscal.get("avisos", []),
        "temPrecosHistoricos": bool(history),
        "dividendosBrutoEstimado": divs["recebido"]["brutoEstimado"],
    }

    res = {
        "available": True,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asOf": today.isoformat(),
        "performance": perf,
        "fiscal": fiscal,
        "dividends": divs,
        "dataQuality": quality,
    }
    if write:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
        t = perf["totais"]
        print(f"analytics.json escrito ({os.path.getsize(OUT) // 1024} KB)")
        print(f"  Valor total {t['totalValueEur']} € · Retorno {t['totalReturnEur']} € ({t['totalReturnPct']}%)")
        print(f"  IRR {t['irrPct']}% · TWR {t['twrPct']}% · CAGR {t['cagrPct']}%")
        print(f"  IRS estimado {today.year}: {fiscal['irsEstimadoDoAno']['totalEur']} €")
        print(f"  Dividendos recebidos: {divs['recebido']['totalNetEur']} € líquidos · previsão anual {divs['previsao']['estimatedAnnualIncomeNetEur']} €")
        if mismatches:
            print(f"  ⚠ {len(mismatches)} posições com quantidade diferente da corretora")
    return res


if __name__ == "__main__":
    build()
