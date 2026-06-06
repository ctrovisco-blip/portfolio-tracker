"""
Fetch spot FX rates from Yahoo Finance and save to data/fx.json.
Rates are stored as: 1 unit of that currency = X EUR
"""
import json, urllib.request, os

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}

def spot(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        return d["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None

print("Fetching FX rates...")
eurusd = spot("EURUSD=X") or 1.08   # USD per 1 EUR
eurgbp = spot("EURGBP=X") or 0.854  # GBP per 1 EUR
eurcad = spot("EURCAD=X") or 1.56   # CAD per 1 EUR (for Enbridge)

fx = {
    "€": 1.0,
    "$": round(1 / eurusd, 6),        # 1 USD  => EUR
    "p": round(1 / eurgbp / 100, 6),  # 1 GBp  => EUR (pence => pounds => EUR)
    "C$": round(1 / eurcad, 6),       # 1 CAD  => EUR
}

os.makedirs("data", exist_ok=True)
with open("data/fx.json", "w") as f:
    json.dump(fx, f, indent=2)

print(f"  EUR/USD = {eurusd:.4f}  =>  1 USD = {fx['$']:.4f} €")
print(f"  EUR/GBP = {eurgbp:.4f}  =>  1 GBp = {fx['p']:.6f} €")
print(f"  EUR/CAD = {eurcad:.4f}  =>  1 CAD = {fx['C$']:.4f} €")
print(f"Saved to data/fx.json")
