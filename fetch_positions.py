"""
Fetch live positions from Trading212 + order history for buy dates.
Outputs: data/positions.json
Requires env vars: T212_API_KEY, T212_SECRET_KEY
"""
import json, os, time, base64, urllib.request
from datetime import datetime

API_KEY    = os.environ.get("T212_API_KEY", "")
API_SECRET = os.environ.get("T212_SECRET_KEY", "")

BASIC = base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
HEADERS = {
    "Authorization": f"Basic {BASIC}",
    "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":        "application/json",
}

BASE = "https://live.trading212.com"

def get(path, retries=5):
    delays = [10, 30, 60, 120, 180]
    for attempt in range(retries):
        req = urllib.request.Request(BASE + path, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = delays[attempt]
                print(f"  Rate limit (429), aguardando {wait}s antes de retry {attempt + 1}/{retries - 1}...")
                time.sleep(wait)
            else:
                raise

# Load static metadata
with open("metadata.json", encoding="utf-8") as f:
    METADATA = json.load(f)

# T212 internal ticker → display ticker mapping (lido de data/t212_map.json)
# Actualizado automaticamente pelo auto_discover.py quando há novas posições
with open("data/t212_map.json", encoding="utf-8") as f:
    T212_TO_DISPLAY = json.load(f)
DISPLAY_TO_T212 = {v: k for k, v in T212_TO_DISPLAY.items()}

print("Fetching portfolio positions...")
portfolio = get("/api/v0/equity/portfolio")

# Build base positions from portfolio
pos_map = {}  # display_ticker -> position dict
for p in portfolio:
    t212 = p["ticker"]
    display = T212_TO_DISPLAY.get(t212)
    if not display:
        print(f"  UNKNOWN T212 ticker: {t212}")
        continue
    meta = METADATA.get(display, {})
    pos_map[display] = {
        "ticker":   display,
        "name":     meta.get("name", display),
        "sector":   meta.get("sector", "Outro"),
        "flag":     meta.get("flag", "🌍"),
        "exchange": meta.get("exchange", "—"),
        "qty":      round(float(p["quantity"]), 6),
        "avgPrice": round(float(p["averagePrice"]), 4),
        "curPrice": round(float(p["currentPrice"]), 4),
        "ppl":      round(float(p["ppl"]), 2),
        "cur":      meta.get("cur", "€"),
        "initialFillDate": p.get("initialFillDate", "")[:10],
        "buyDates": [],
    }

print(f"  {len(pos_map)} open positions found")

# Fetch all order history for buy dates
print("Fetching order history...")
all_orders = []
path = "/api/v0/equity/history/orders?limit=50"
while path:
    data = get(path)
    all_orders.extend([i["order"] for i in data.get("items", [])])
    path = data.get("nextPagePath")
    if path:
        time.sleep(0.3)

print(f"  {len(all_orders)} total orders")

# Save order history — só sobrescreve se obtivemos dados (evita apagar histórico com array vazio)
if all_orders:
    with open("data/orders.json", "w", encoding="utf-8") as f:
        json.dump(all_orders, f, ensure_ascii=False)
    print(f"  Saved {len(all_orders)} orders to data/orders.json")
else:
    print("  Sem ordens obtidas — orders.json não foi sobrescrito")

# Build buy dates per ticker from filled buy orders
buy_dates = {}  # display_ticker -> set of date strings
for o in all_orders:
    t212 = o.get("ticker", "")
    display = T212_TO_DISPLAY.get(t212)
    if not display or display not in pos_map:
        continue
    if o.get("status") != "FILLED" or o.get("side") != "BUY":
        continue
    date = o.get("createdAt", "")[:10]
    if date:
        buy_dates.setdefault(display, set()).add(date)

# Merge buy dates: initialFillDate + order history, deduped & sorted
for display, pos in pos_map.items():
    dates = set(buy_dates.get(display, set()))
    init = pos.pop("initialFillDate", "")
    if init:
        dates.add(init)
    pos["buyDates"] = sorted(dates)

# Preserve order from METADATA keys (consistent ordering)
positions = [pos_map[t] for t in METADATA.keys() if t in pos_map]

# Add any new positions not yet in metadata
for display, pos in pos_map.items():
    if display not in METADATA:
        positions.append(pos)
        print(f"  NEW position not in metadata: {display}")

os.makedirs("data", exist_ok=True)
with open("data/positions.json", "w", encoding="utf-8") as f:
    json.dump(positions, f, ensure_ascii=False, indent=2)

print(f"\nSaved {len(positions)} positions to data/positions.json")
for p in positions:
    ret = (p["curPrice"] / p["avgPrice"] - 1) * 100
    print(f"  {p['ticker']:12s} {p['cur']}{p['curPrice']:.2f}  {ret:+.1f}%  buyDates={p['buyDates']}")
