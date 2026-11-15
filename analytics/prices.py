"""
Histórico de preços e câmbios → preço em EUR de qualquer instrumento em qualquer dia.

data/price_history.json (escrito por fetch_price_history.py):
  {
    "instruments": { "<isin>": {"symbol": "NVD.DE", "ccy": "EUR",
                                "closes": {"2025-01-02": 123.4, ...},
                                "divs":   {"2025-03-05": 0.01, ...}} },
    "fx":          { "USD": {"2025-01-02": 1.03, ...}, ... }   # unidades por 1 EUR
    "benchmarks":  { "SPY": {"ccy": "USD", "closes": {...}}, ... }  # adjclose
  }

Quando falta cotação para um instrumento (ex.: título deslistado), usa-se o
último preço de transação em EUR do ledger (marcado em `fallback`).
"""
from __future__ import annotations

import bisect
import json
import os
from datetime import date

from .ledger import instrument_key
from .util import to_date


class Series:
    """Série data→valor com forward-fill."""

    def __init__(self, points: dict):
        items = sorted((to_date(k), float(v)) for k, v in points.items() if v is not None)
        self.dates = [d for d, _ in items]
        self.vals = [v for _, v in items]

    def __bool__(self):
        return bool(self.dates)

    def at(self, d: date):
        i = bisect.bisect_right(self.dates, d) - 1
        if i < 0:
            return None
        return self.vals[i]

    def first(self):
        return self.dates[0] if self.dates else None

    def last(self):
        return (self.dates[-1], self.vals[-1]) if self.dates else (None, None)


def _ccy_scale(ccy):
    """Cotações em pence (GBp/GBX) → libras."""
    if ccy in ("GBp", "GBX"):
        return "GBP", 0.01
    if ccy == "ILA":
        return "ILS", 0.01
    if ccy == "ZAc":
        return "ZAR", 0.01
    return ccy, 1.0


class PriceBook:
    def __init__(self, history: dict | None, events: list[dict]):
        history = history or {}
        self.fx = {c: Series(v) for c, v in (history.get("fx") or {}).items()}
        self.inst = {}
        self.inst_meta = {}
        for k, v in (history.get("instruments") or {}).items():
            ccy, scale = _ccy_scale(v.get("ccy") or "EUR")
            self.inst[k] = Series({d: p * scale for d, p in (v.get("closes") or {}).items()})
            self.inst_meta[k] = {"symbol": v.get("symbol"), "ccy": ccy, "scale": scale,
                                 "divs": v.get("divs") or {}}
        self.bench = {}
        for k, v in (history.get("benchmarks") or {}).items():
            ccy, scale = _ccy_scale(v.get("ccy") or "USD")
            self.bench[k] = (ccy, Series({d: p * scale for d, p in (v.get("closes") or {}).items()}))

        # Fallback: último preço de transação em EUR
        pts = {}
        for e in events:
            if e["type"] in ("BUY", "SELL") and e.get("qty") and e.get("totalEur"):
                gross = e["totalEur"] + (e.get("feesEur") or 0) * (-1 if e["type"] == "BUY" else 1)
                pts.setdefault(instrument_key(e), {})[e["date"]] = gross / e["qty"]
        self.trade_px = {k: Series(v) for k, v in pts.items()}
        self.fallback_used = set()
        self.overrides = {}  # key → preço EUR atual (cotação ao vivo)

    def fx_rate(self, ccy: str, d: date):
        if not ccy or ccy == "EUR":
            return 1.0
        s = self.fx.get(ccy)
        if not s:
            return None
        v = s.at(d)
        if v is None and s:
            v = s.vals[0]
        return v

    def to_eur(self, amount: float, ccy: str, d: date):
        ccy, scale = _ccy_scale(ccy)
        r = self.fx_rate(ccy, d)
        if r is None:
            return None
        return amount * scale / r

    def price_eur(self, key: str, d: date, today: date | None = None):
        if today is not None and d >= today and key in self.overrides:
            return self.overrides[key]
        s = self.inst.get(key)
        if s:
            p = s.at(d)
            if p is not None:
                ccy = self.inst_meta[key]["ccy"]
                r = self.fx_rate(ccy, d)
                if r:
                    return p / r
        t = self.trade_px.get(key)
        if t:
            p = t.at(d)
            if p is None:
                p = t.vals[0]
            self.fallback_used.add(key)
            return p
        return None

    def bench_eur(self, name: str, d: date):
        b = self.bench.get(name)
        if not b:
            return None
        ccy, s = b
        p = s.at(d)
        if p is None:
            return None
        r = self.fx_rate(ccy, d)
        return p / r if r else None

    def dividends_native(self, key: str):
        """{date: valor por ação na moeda do título (já em libras para GBp)}"""
        m = self.inst_meta.get(key)
        if not m:
            return {}, None
        return ({to_date(d): v * m["scale"] for d, v in m["divs"].items()}, m["ccy"])


def load_price_history(path="data/price_history.json"):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
