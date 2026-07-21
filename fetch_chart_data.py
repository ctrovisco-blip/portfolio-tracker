"""
Fetch Yahoo Finance chart data for all positions across multiple time ranges.
Reads:  data/positions.json + metadata.json
Writes: data/chart_data.json

O gráfico mostra performance do preço (% desde início do período),
sem pesos por quantidade/posição — informação pura de mercado.
"""
import json, urllib.request, time, os
from datetime import datetime

with open("data/positions.json", encoding="utf-8") as f:
    positions = json.load(f)
with open("metadata.json", encoding="utf-8") as f:
    METADATA = json.load(f)
with open("data/fx.json", encoding="utf-8") as f:
    FX = json.load(f)   # {"€":1.0, "$":0.xxx, "p":0.xxx, "C$":0.xxx}

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
    ("max", "1mo", "max"),
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
    """% desde o primeiro preço do período, ordenado por data/hora."""
    if not prices: return {}
    items = sorted(prices.items())
    base  = items[0][1]
    if not base or base <= 0: return {}
    return {d: round((v / base - 1) * 100, 4) for d, v in items}

# ── Watchlist: tickers do screener que não são posições ───────────────────
# Entram nas séries de preço para o entry_dashboard os avaliar,
# mas nunca no cálculo do portfolio (weights só cobre posições).
watchlist = []
if os.path.exists("data/screener.json"):
    with open("data/screener.json", encoding="utf-8") as f:
        screener = json.load(f)
    pos_set = {p["ticker"] for p in positions}
    watchlist = [t for t in screener if t not in pos_set]

# ── Fetch raw prices for every ticker × range ─────────────────────────────
print(f"Fetching {len(positions)} tickers + {len(watchlist)} watchlist × {len(RANGES)} ranges...")
raw = {}   # ticker → range_key → {date: price}
fetch_list = [(p["ticker"], METADATA.get(p["ticker"], {}).get("yf")) for p in positions]
# Screener usa símbolos US compatíveis com o Yahoo; metadata.json pode sobrepor
fetch_list += [(t, METADATA.get(t, {}).get("yf", t)) for t in watchlist]
for ticker, yf_sym in fetch_list:
    if not yf_sym:
        print(f"  SKIP {ticker}")
        raw[ticker] = {rk: {} for rk, _, _ in RANGES}
        continue
    print(f"  {ticker} ({yf_sym})")
    raw[ticker] = {}
    for rk, interval, range_ in RANGES:
        raw[ticker][rk] = fetch_raw(yf_sym, interval, range_)
        time.sleep(0.2)

# ── Normalised stock series (% desde início do período) ───────────────────
stock_series = {}
for ticker, r_data in raw.items():
    stock_series[ticker] = {rk: normalize(r_data[rk]) for rk, _, _ in RANGES}

# ── Pesos por valor actual de posição em EUR ──────────────────────────────
# Peso = qty × preço_actual × fx  →  reflecte o peso real de cada stock
# na carteira, sem precisar de histórico de ordens.
position_eur = {}
for p in positions:
    ticker  = p["ticker"]
    fx_rate = FX.get(p.get("cur", "€"), 1.0)
    val_eur = p.get("qty", 0) * p.get("curPrice", 0) * fx_rate
    if val_eur > 0:
        position_eur[ticker] = val_eur

total_eur = sum(position_eur.values()) or 1
weights   = {t: v / total_eur for t, v in position_eur.items()}
print("Portfolio weights (EUR):")
for t, w in sorted(weights.items(), key=lambda x: -x[1]):
    print(f"  {t:12s} {w*100:5.1f}%  (€{position_eur[t]:,.0f})")

# ── Portfolio series: média ponderada por valor de posição em EUR ──────────
# Cada acção contribui proporcionalmente ao seu peso actual na carteira.
portfolio_series = {}
for rk, _, _ in RANGES:
    all_keys = sorted(set(k for t in stock_series.values() for k in t[rk]))

    port = {}
    for key in all_keys:
        wr = 0.0
        w_sum = 0.0
        for ticker, t_data in stock_series.items():
            if key in t_data[rk] and ticker in weights:
                wr    += weights[ticker] * t_data[rk][key]
                w_sum += weights[ticker]
        if w_sum > 0:
            port[key] = round(wr / w_sum, 4)
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
