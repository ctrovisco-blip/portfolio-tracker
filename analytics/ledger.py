"""
Ledger normalizado de transações.

Fontes suportadas (todas convertidas para o MESMO formato de evento):
  1. CSV de extrato da Trading 212 (export pela API ou descarregado à mão
     e colocado em data/statements/*.csv)
  2. JSON da API pública da T212 (/equity/history/orders com `fill`,
     /equity/history/dividends, /equity/history/transactions) — fallback

Formato de evento (todos os valores monetários em EUR, positivos; o sinal
deduz-se do tipo):
  {
    "id", "date" (YYYY-MM-DD), "time" (ISO), "type",
    "isin", "ticker" (T212), "name",
    "qty", "price", "priceCcy", "fxRate" (unidades de priceCcy por 1 EUR),
    "totalEur"        BUY: o que saiu da conta (com comissões)
                      SELL: o que entrou (já sem comissões)
                      DIVIDEND: líquido recebido
                      DEPOSIT/WITHDRAWAL/INTEREST/FEE/CASHBACK: o montante
    "feesEur", "grossEur", "withholdingEur", "grossNative", "nativeCcy",
    "resultEur" (resultado reportado pela corretora numa venda),
    "source"
  }
Tipos: BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, INTEREST, FEE, CASHBACK,
       SPLIT_IN, SPLIT_OUT, FX, OTHER
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from collections import defaultdict

TRADE_TYPES = {"BUY", "SELL"}
CASH_IN = {"DEPOSIT", "SELL", "DIVIDEND", "INTEREST", "CASHBACK"}
CASH_OUT = {"WITHDRAWAL", "BUY", "FEE"}
EXTERNAL_FLOWS = {"DEPOSIT", "WITHDRAWAL"}


# ─── helpers ─────────────────────────────────────────────────────────────────

def _f(v):
    if v is None:
        return None
    s = str(v).strip().replace(" ", "")
    if s in ("", "Not available", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None


def _norm_ccy(c):
    if not c:
        return None
    c = str(c).strip()
    return {"GBX": "GBp", "GBp": "GBp", "GBP": "GBP"}.get(c, c.upper())


def _event_id(*parts):
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return f"h{h}"


def classify_action(action: str) -> str:
    a = (action or "").strip().lower()
    if "split" in a and "close" in a:
        return "SPLIT_OUT"
    if "split" in a and "open" in a:
        return "SPLIT_IN"
    if a.endswith("buy") or a in ("buy",):
        return "BUY"
    if a.endswith("sell") or a in ("sell",):
        return "SELL"
    if a.startswith("dividend"):
        return "DIVIDEND"
    if a == "deposit" or a.startswith("deposit"):
        return "DEPOSIT"
    if a.startswith("withdraw"):
        return "WITHDRAWAL"
    if "interest" in a:
        return "INTEREST"
    if "cashback" in a:
        return "CASHBACK"
    if a.startswith("card debit") or a.startswith("card"):
        return "WITHDRAWAL"
    if "currency conversion" in a:
        return "FX"
    if "fee" in a:
        return "FEE"
    return "OTHER"


# ─── CSV T212 ────────────────────────────────────────────────────────────────

# Colunas de encargos (para além da conversão cambial) — qualquer coluna com
# estas palavras, que não seja a retenção na fonte, conta como comissão/taxa.
_FEE_WORDS = ("fee", "stamp duty", "transaction tax", "finra")


def parse_t212_csv(text: str, source: str = "t212-csv") -> list[dict]:
    rdr = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = rdr.fieldnames or []
    fee_cols = [h for h in headers
                if not h.lower().startswith("currency (")
                and any(w in h.lower() for w in _FEE_WORDS)]
    out = []
    for row in rdr:
        action = row.get("Action", "")
        typ = classify_action(action)
        time_ = (row.get("Time") or "").strip().replace(" ", "T")
        if not time_:
            continue
        qty = _f(row.get("No. of shares"))
        price = _f(row.get("Price / share"))
        price_ccy = _norm_ccy(row.get("Currency (Price / share)"))
        fx = _f(row.get("Exchange rate"))
        total = _f(row.get("Total"))
        total_ccy = (row.get("Currency (Total)") or "EUR").strip().upper()
        result = _f(row.get("Result"))
        wht = _f(row.get("Withholding tax"))
        wht_ccy = _norm_ccy(row.get("Currency (Withholding tax)"))

        fees_eur = 0.0
        for col in fee_cols:
            v = _f(row.get(col))
            if not v:
                continue
            ccy = (row.get(f"Currency ({col})") or "EUR").strip().upper()
            if ccy != "EUR" and fx:
                # encargo na moeda do título: o câmbio da linha é essa moeda por EUR
                v = v / fx
            fees_eur += abs(v)

        ev = {
            "id": (row.get("ID") or "").strip() or None,
            "date": time_[:10],
            "time": time_,
            "type": typ,
            "action": action,
            "isin": (row.get("ISIN") or "").strip() or None,
            "ticker": (row.get("Ticker") or "").strip() or None,
            "name": (row.get("Name") or "").strip() or None,
            "qty": abs(qty) if qty is not None else None,
            "price": price,
            "priceCcy": price_ccy,
            "fxRate": fx,
            "totalEur": abs(total) if total is not None else None,
            "totalCcy": total_ccy,
            "feesEur": round(fees_eur, 6),
            "resultEur": result,
            "source": source,
        }
        if typ == "DIVIDEND":
            net = abs(total or 0.0)
            w_eur = 0.0
            if wht:
                w = abs(wht)
                if wht_ccy in (None, "EUR"):
                    w_eur = w
                elif fx:
                    # retenção na moeda do título; o câmbio da linha é essa moeda por EUR
                    w_eur = w / fx
            ev["withholdingEur"] = round(w_eur, 6)
            ev["grossEur"] = round(net + w_eur, 6)
            if qty and price:
                ev["grossNative"] = abs(qty) * price
                ev["nativeCcy"] = price_ccy
        if total_ccy != "EUR" and ev["totalEur"] is not None and typ in TRADE_TYPES and fx:
            # Conta noutra moeda — não deve acontecer numa conta em EUR.
            ev["warning"] = f"total em {total_ccy}"
        if not ev["id"]:
            ev["id"] = _event_id(action, time_, ev["isin"], qty, total)
        out.append(ev)
    return out


# ─── JSON da API T212 ────────────────────────────────────────────────────────

def parse_t212_api(orders=None, dividends=None, transactions=None) -> list[dict]:
    out = []
    for it in orders or []:
        o = it.get("order", it)
        fill = it.get("fill")
        if not fill or o.get("status") != "FILLED":
            continue
        inst = o.get("instrument") or {}
        side = o.get("side")
        qty = abs(_f(fill.get("quantity")) or _f(o.get("filledQuantity")) or 0)
        wi = fill.get("walletImpact") or {}
        fxr = _f(wi.get("fxRate"))
        fees = 0.0
        for t in wi.get("taxes") or []:
            v = abs(_f(t.get("quantity")) or 0)
            if (t.get("currency") or "EUR").upper() != "EUR" and fxr:
                v = v / fxr
            fees += v
        t_ = (fill.get("filledAt") or o.get("createdAt") or "")[:19]
        out.append({
            "id": str(fill.get("id") or o.get("id")),
            "date": t_[:10], "time": t_,
            "type": "BUY" if side == "BUY" else "SELL",
            "action": f"{o.get('type', '')} {side}".lower(),
            "isin": inst.get("isin"), "ticker": o.get("ticker"), "name": inst.get("name"),
            "qty": qty, "price": _f(fill.get("price")),
            "priceCcy": _norm_ccy(inst.get("currency") or o.get("currency")),
            "fxRate": fxr,
            "totalEur": abs(_f(wi.get("netValue")) or 0),
            "feesEur": round(fees, 6),
            "resultEur": _f(wi.get("realisedProfitLoss")),
            "source": "t212-api",
        })
    for d in dividends or []:
        inst = d.get("instrument") or {}
        qty = _f(d.get("quantity")) or 0
        gps = _f(d.get("grossAmountPerShare"))
        t_ = (d.get("paidOn") or "")[:19]
        net = abs(_f(d.get("amountInEuro")) or _f(d.get("amount")) or 0)
        out.append({
            "id": str(d.get("reference") or _event_id("div", d.get("ticker"), t_, net)),
            "date": t_[:10], "time": t_, "type": "DIVIDEND", "action": d.get("type") or "dividend",
            "isin": inst.get("isin"), "ticker": d.get("ticker"), "name": inst.get("name"),
            "qty": qty, "price": gps, "priceCcy": _norm_ccy(d.get("tickerCurrency") or inst.get("currency")),
            "totalEur": net, "feesEur": 0.0,
            # bruto em EUR completado mais tarde com o câmbio do dia (ver dividends.py)
            "grossNative": (qty * gps) if gps else None,
            "nativeCcy": _norm_ccy(d.get("tickerCurrency") or inst.get("currency")),
            "source": "t212-api",
        })
    tmap = {"DEPOSIT": "DEPOSIT", "WITHDRAW": "WITHDRAWAL", "FEE": "FEE", "TRANSFER": "OTHER"}
    for t in transactions or []:
        typ = tmap.get((t.get("type") or "").upper(), "OTHER")
        amt = _f(t.get("amount")) or 0
        if typ == "OTHER" and (t.get("type") or "").upper() == "TRANSFER":
            typ = "DEPOSIT" if amt > 0 else "WITHDRAWAL"
        t_ = (t.get("dateTime") or "")[:19]
        out.append({
            "id": str(t.get("reference") or _event_id("tx", t_, amt)),
            "date": t_[:10], "time": t_, "type": typ, "action": t.get("type"),
            "totalEur": abs(amt), "feesEur": 0.0, "source": "t212-api",
        })
    return out


# ─── merge / persistência ────────────────────────────────────────────────────

def _soft_key(e):
    """Chave para deduplicar o mesmo evento vindo de fontes diferentes."""
    return (e["type"], e["date"], e.get("isin") or e.get("ticker"),
            round(e.get("qty") or 0, 4), round(e.get("totalEur") or 0, 2))


_SOURCE_RANK = {"t212-csv": 0, "manual-csv": 0, "t212-api": 1}


def merge_events(*lists: list[dict]) -> list[dict]:
    """Junta listas de eventos; o CSV (mais completo) ganha sobre o JSON da API."""
    by_id, by_soft = {}, {}
    for ev in sorted((e for l in lists for e in l),
                     key=lambda e: _SOURCE_RANK.get(e.get("source"), 2)):
        if ev["id"] in by_id:
            continue
        # A chave "suave" só deduplica ENTRE fontes de família diferente (CSV vs
        # API): dentro da mesma fonte, dois eventos iguais no mesmo dia são reais.
        sk = _soft_key(ev)
        fam = "api" if ev.get("source") == "t212-api" else "csv"
        if any(f != fam for f in by_soft.get(sk, ())):
            continue
        by_id[ev["id"]] = ev
        by_soft.setdefault(sk, set()).add(fam)
    return sorted(by_id.values(), key=lambda e: (e["time"], 0 if e["type"] == "BUY" else 1))


def load_statement_dir(path="data/statements") -> list[dict]:
    evs = []
    if not os.path.isdir(path):
        return evs
    for fn in sorted(os.listdir(path)):
        if fn.lower().endswith(".csv"):
            with open(os.path.join(path, fn), encoding="utf-8-sig") as f:
                evs.extend(parse_t212_csv(f.read(), source="manual-csv"))
    return evs


def load_transactions(path="data/transactions.json") -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("events", data) if isinstance(data, dict) else data


def save_transactions(events, path="data/transactions.json", meta=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta or {}, "events": events}, f, ensure_ascii=False, separators=(",", ":"))


# ─── vistas derivadas ────────────────────────────────────────────────────────

def instrument_key(e) -> str:
    return e.get("isin") or e.get("ticker") or "?"


def instruments(events) -> dict:
    """isin → {isin, ticker, name, priceCcy, firstDate, lastDate}"""
    out = {}
    for e in events:
        if e["type"] not in ("BUY", "SELL", "DIVIDEND", "SPLIT_IN", "SPLIT_OUT"):
            continue
        k = instrument_key(e)
        d = out.setdefault(k, {"isin": e.get("isin"), "ticker": e.get("ticker"),
                               "name": e.get("name"), "priceCcy": None,
                               "firstDate": e["date"], "lastDate": e["date"]})
        if e["type"] in TRADE_TYPES and e.get("priceCcy"):
            d["priceCcy"] = e["priceCcy"]
        d["ticker"] = d["ticker"] or e.get("ticker")
        d["name"] = e.get("name") or d["name"]
        d["lastDate"] = max(d["lastDate"], e["date"])
    return out


def quantities_at_end(events) -> dict:
    q = defaultdict(float)
    for e in events:
        k = instrument_key(e)
        if e["type"] in ("BUY", "SPLIT_IN"):
            q[k] += e.get("qty") or 0
        elif e["type"] in ("SELL", "SPLIT_OUT"):
            q[k] -= e.get("qty") or 0
    return {k: v for k, v in q.items() if abs(v) > 1e-6}
