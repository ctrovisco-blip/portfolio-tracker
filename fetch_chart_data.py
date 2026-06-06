"""
Fetch Yahoo Finance chart data for all positions.
Reads:  data/positions.json
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

def fetch_yf(symbol, range_="1y", interval="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        out = {}
        for t, c in zip(timestamps, closes):
            if c is not None:
                d = str(datetime.fromtimestamp(t).date())
                out[d] = round(c, 4)
        return out
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return {}

total_value = sum(p["qty"] * p["curPrice"] for p in positions)
chart_data = {}
print(f"Fetching {len(positions)} tickers...")

for p in positions:
    ticker = p["ticker"]
    yf_sym = METADATA.get(ticker, {}).get("yf")
    if yf_sym is None:
        print(f"  SKIP {ticker}")
        chart_data[ticker] = {"prices": {}, "avgPrice": p["avgPrice"],
                              "weight": round((p["qty"]*p["curPrice"])/total_value, 6)}
        continue
    print(f"  {ticker} ({yf_sym})...")
    prices = fetch_yf(yf_sym)
    chart_data[ticker] = {"prices": prices, "avgPrice": p["avgPrice"],
                          "weight": round((p["qty"]*p["curPrice"])/total_value, 6)}
    time.sleep(0.3)

all_dates = sorted(set(d for p in chart_data.values() for d in p["prices"].keys()))
portfolio_series = {}
for date in all_dates:
    wr, tw = 0.0, 0.0
    for d in chart_data.values():
        if date in d["prices"] and d["avgPrice"] > 0:
            wr += d["weight"] * (d["prices"][date] / d["avgPrice"] - 1) * 100
            tw += d["weight"]
    if tw > 0:
        portfolio_series[date] = round(wr, 4)

stock_series = {}
for ticker, d in chart_data.items():
    if not d["prices"]:
        stock_series[ticker] = {}
        continue
    avg = d["avgPrice"]
    items = sorted({dt: round((pr/avg-1)*100, 4) for dt, pr in d["prices"].items()}.items())[-252:]
    stock_series[ticker] = dict(items)

ptrim = dict(sorted(portfolio_series.items())[-252:])
os.makedirs("data", exist_ok=True)
with open("data/chart_data.json", "w") as f:
    json.dump({"portfolio": ptrim, "stocks": stock_series}, f)
print(f"Done! Portfolio: {len(ptrim)} days")
