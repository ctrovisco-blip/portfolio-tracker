"""
Histórico diário de preços, dividendos por ação, câmbios e benchmarks
(Yahoo Finance) para todos os instrumentos do ledger → data/price_history.json

  • Símbolo Yahoo de cada ISIN: metadata.json (via orders.json + t212_map.json),
    depois a cache data/symbol_map.json, depois a pesquisa do Yahoo pelo ISIN.
    Correções manuais: editar data/symbol_map.json (ISIN → símbolo, ou null
    para ignorar).
  • Preços desde a primeira transação de cada instrumento; dividendos por ação
    dos últimos 11 anos nas posições abertas (crescimento a 10 anos).
  • Câmbios EUR→moeda (EURUSD=X, …) e benchmarks SPY, QQQ, URTH (adjclose,
    com dividendos reinvestidos).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analytics import ledger  # noqa: E402

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Accept": "application/json"}
OUT = "data/price_history.json"
SYMBOL_MAP = "data/symbol_map.json"
BENCHMARKS = ["SPY", "QQQ", "URTH"]

EUR_SUFFIX = (".DE", ".F", ".AS", ".PA", ".MI", ".LS", ".MC", ".BR", ".VI", ".HE", ".IR")


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def chart(symbol, start: datetime, end: datetime):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?period1={int(start.timestamp())}&period2={int(end.timestamp())}"
           f"&interval=1d&events=div&includeAdjustedClose=true")
    data = get_json(url)
    res = data["chart"]["result"][0]
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    adj = (res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
    closes, adjc = {}, {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
        c = (q.get("close") or [None] * len(ts))[i]
        if c is not None:
            closes[d] = round(c, 6)
        if adj and adj[i] is not None:
            adjc[d] = round(adj[i], 6)
    divs = {}
    for v in ((res.get("events") or {}).get("dividends") or {}).values():
        d = datetime.fromtimestamp(v["date"], tz=timezone.utc).date().isoformat()
        divs[d] = round(v["amount"], 6)
    return meta.get("currency"), closes, adjc, divs


def search_isin(isin, price_ccy):
    """Símbolos Yahoo com este ISIN, do mais provável para o menos provável."""
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=10&newsCount=0"
    quotes = [q for q in get_json(url).get("quotes", []) if q.get("symbol")]
    if not quotes:
        return []

    def score(q):
        s = q["symbol"]
        if price_ccy == "EUR":
            return 0 if s.endswith(".DE") else (1 if s.endswith(EUR_SUFFIX) else 3)
        if price_ccy in ("GBp", "GBP"):
            return 0 if s.endswith(".L") else 3
        if price_ccy == "USD":
            return 0 if "." not in s else 3
        if price_ccy == "CAD":
            return 0 if s.endswith(".TO") else 3
        return 1
    return [q["symbol"] for q in sorted(quotes, key=score)]


def seed_symbols():
    """ISIN → símbolo Yahoo a partir do que o repositório já sabe."""
    seeds = {}
    try:
        with open("metadata.json", encoding="utf-8") as f:
            meta = json.load(f)
        with open("data/t212_map.json", encoding="utf-8") as f:
            tmap = json.load(f)
        with open("data/orders.json", encoding="utf-8") as f:
            orders = json.load(f)
        for o in orders:
            inst = o.get("instrument") or {}
            disp = tmap.get(o.get("ticker"))
            yf = (meta.get(disp) or {}).get("yf") if disp else None
            if inst.get("isin") and yf:
                seeds[inst["isin"]] = yf
    except FileNotFoundError:
        pass
    return seeds


def main():
    events = ledger.load_transactions()
    if not events:
        print("Sem transações — nada a fazer.")
        return
    insts = ledger.instruments(events)
    open_keys = set(ledger.quantities_at_end(events))
    now = datetime.now(timezone.utc)

    symmap = {}
    if os.path.exists(SYMBOL_MAP):
        with open(SYMBOL_MAP, encoding="utf-8") as f:
            symmap = json.load(f)
    for isin, sym in seed_symbols().items():
        symmap.setdefault(isin, sym)

    out = {"updated": now.isoformat(timespec="seconds"), "instruments": {}, "fx": {}, "benchmarks": {}}
    ccys = {"USD"}
    first_all = min(datetime.fromisoformat(i["firstDate"]) for i in insts.values()).replace(tzinfo=timezone.utc)

    for key, inst in sorted(insts.items()):
        isin = inst.get("isin")
        mapped = symmap.get(isin or key)
        if mapped is None and (isin or key) in symmap:
            continue  # ignorado explicitamente
        start = datetime.fromisoformat(inst["firstDate"]).replace(tzinfo=timezone.utc) - timedelta(days=7)
        div_start = now - timedelta(days=365 * 11) if key in open_keys else start
        s0 = start.date().isoformat()

        # Candidatos: o símbolo guardado e, se falhar ou vier sem cotações,
        # as outras cotações do mesmo ISIN que o Yahoo conhece.
        candidates = [mapped] if mapped else []
        searched = False
        sym = ccy = closes = divs = None
        i = 0
        while True:
            if i >= len(candidates):
                if searched or not isin:
                    break
                searched = True
                try:
                    candidates += [c for c in search_isin(isin, inst.get("priceCcy")) if c not in candidates]
                    time.sleep(0.4)
                except Exception as e:
                    print(f"  pesquisa {isin}: {e}")
                continue
            cand = candidates[i]
            i += 1
            try:
                c_ccy, c_closes, _, c_divs = chart(cand, min(start, div_start), now)
            except Exception as e:
                print(f"  {cand}: {e}")
                continue
            c_closes = {d: v for d, v in c_closes.items() if d >= s0}
            if c_closes and c_ccy:
                sym, ccy, closes, divs = cand, c_ccy, c_closes, c_divs
                break
            print(f"  {cand}: sem cotações — a tentar outro símbolo")
        if not sym:
            print(f"  SEM SÍMBOLO {inst.get('ticker')} {isin} — usa o preço das transações")
            continue
        if isin and sym != mapped:
            if mapped:
                print(f"  {inst.get('ticker')}: {mapped} → {sym}")
            symmap[isin] = sym
        out["instruments"][key] = {"symbol": sym, "ccy": ccy, "closes": closes, "divs": divs}
        if ccy:
            ccys.add({"GBp": "GBP", "GBX": "GBP", "ILA": "ILS", "ZAc": "ZAR"}.get(ccy, ccy))
        print(f"  {inst.get('ticker') or key:10s} {sym:12s} {ccy} {len(closes)} dias, {len(divs)} div.")
        time.sleep(0.3)

    for c in sorted(ccys - {"EUR"}):
        try:
            _, closes, _, _ = chart(f"EUR{c}=X", first_all - timedelta(days=10), now)
            out["fx"][c] = closes
            print(f"  FX EUR{c}: {len(closes)}")
        except Exception as e:
            print(f"  FX {c}: {e}")
        time.sleep(0.3)

    for b in BENCHMARKS:
        try:
            ccy, closes, adj, _ = chart(b, first_all - timedelta(days=10), now)
            out["benchmarks"][b] = {"ccy": ccy, "closes": adj or closes}
            print(f"  Benchmark {b}: {len(adj or closes)}")
        except Exception as e:
            print(f"  Benchmark {b}: {e}")
        time.sleep(0.3)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    with open(SYMBOL_MAP, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(symmap.items())), f, ensure_ascii=False, indent=1)
    print(f"Guardado {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
