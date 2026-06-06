"""
Fetch Yahoo Finance chart data for all positions across multiple time ranges.
Reads:  data/positions.json + metadata.json
Writes: data/chart_data.json
"""
import json, urllib.request, time, os
from datetime import datetime

with open("data/positions.json", encoding="utf-8") as f:
    positions = json.load(f)
with open("metadata.json", encoding="utf-8") as f:
    METADATA = json.load(f)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

# (key, yf_interval, yf_range)
RANGES = [
    ("1d",  "2m",  "1d"),
    ("3mo", "1d",  "3mo"),
    ("ytd", "1d",  "ytd"),
    ("1y",  "1d",  "1y"),
    ("5y",  "1wk", "5y"),
]
INTRADAY = {"1m","2m","5m","15m","30m","1h"}

def fetch_raw(symbol, interval, range_):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval={interval}&range={range_}")
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes     = result["indicators"]["quote"][0]["close"]
        out = {}
        for t, c in zip(timestamps, closes):
            if c is None: continue
            dt  = datetime.utcfromtimestamp(t)
            key = dt.strftime("%H:%M") if interval in INTRADAY else str(dt.date())
            out[key] = round(c, 4)
        return out
    except Exception as e:
        print(f"    ERROR {symbol} [{range_}]: {e}")
        return {}

def normalize(prices):
    """% from first price in period, sorted."""
    if not prices: return {}
    items = sorted(prices.items())
    base  = items[0][1]
    if not base or base <= 0: return {}
    return {d: round((v / base - 1) * 100, 4) for d, v in items}

p_map = {p["ticker"]: p for p in positions}

# ── Fetch raw prices for every ticker × range ─────────────────────────────
print(f"Fetching {len(positions)} tickers × {len(RANGES)} ranges...")
raw = {}   # ticker → range_key → {date: price}
for p in positions:
    ticker = p["ticker"]
    yf_sym = METADATA.get(ticker, {}).get("yf")
    if not yf_sym:
        print(f"  SKIP {ticker}")
        raw[ticker] = {rk: {} for rk, _, _ in RANGES}
        continue
    print(f"  {ticker} ({yf_sym})")
    raw[ticker] = {}
    for rk, interval, range_ in RANGES:
        raw[ticker][rk] = fetch_raw(yf_sym, interval, range_)
        time.sleep(0.2)

# ── Normalised stock series ────────────────────────────────────────────────
stock_series = {}
for ticker, r_data in raw.items():
    stock_series[ticker] = {rk: normalize(r_data[rk]) for rk, _, _ in RANGES}

# ── Portfolio series per range (weighted avg % from period start) ──────────
# Os pesos são calculados com base nos preços do INÍCIO do período,
# não nos preços actuais — evita distorção por stocks que apreciaram muito
# (ex: NVDA ×10 em 5 anos daria peso enorme se usássemos preço actual).
portfolio_series = {}
for rk, _, _ in RANGES:
    all_keys = sorted(set(k for t in raw.values() for k in t[rk]))

    # Preço inicial do período para cada ticker
    bases = {}
    for ticker, r_data in raw.items():
        items = sorted(r_data[rk].items())
        if items:
            bases[ticker] = items[0][1]

    # Pesos baseados em qty × preço_inicial (não preço actual)
    initial_values = {}
    for ticker, init_price in bases.items():
        pos = p_map.get(ticker)
        if pos and init_price and init_price > 0:
            initial_values[ticker] = pos["qty"] * init_price
    total_initial = sum(initial_values.values()) or 1
    period_weights = {t: v / total_initial for t, v in initial_values.items()}

    port = {}
    for key in all_keys:
        wr, tw = 0.0, 0.0
        for ticker, r_data in raw.items():
            if key in r_data[rk] and bases.get(ticker, 0) > 0:
                pct = (r_data[rk][key] / bases[ticker] - 1) * 100
                w   = period_weights.get(ticker, 0)
                wr += w * pct
                tw += w
        if tw > 0:
            port[key] = round(wr / tw, 4)  # normalizar pelo peso total disponível
    portfolio_series[rk] = port

# ── Benchmark indices ─────────────────────────────────────────────────────
INDEXES = {
    "SP500":   "^GSPC",
    "FTSE100": "^FTSE",
    "DAX":     "^GDAXI",
    "NASDAQ":  "^IXIC",
}
index_series = {}
print("Fetching benchmark indices...")
for name, sym in INDEXES.items():
    print(f"  {name} ({sym})")
    index_series[name] = {}
    for rk, interval, range_ in RANGES:
        index_series[name][rk] = normalize(fetch_raw(sym, interval, range_))
        time.sleep(0.2)

os.makedirs("data", exist_ok=True)
with open("data/chart_data.json", "w") as f:
    json.dump({"portfolio": portfolio_series,
               "stocks":    stock_series,
               "indexes":   index_series}, f)
print("Done!")
