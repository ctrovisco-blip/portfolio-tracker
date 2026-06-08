"""
Fetch fundamental data for arbitrary tickers (screener).
Env vars:
  TICKERS  — comma-separated ticker symbols, e.g. "AAPL,MSFT,NVDA"
  MODE     — "add" (default) or "replace"
Writes: data/screener.json
"""
import json, time, os, sys
import yfinance as yf
from datetime import datetime, timezone

COUNTRY_FLAG = {
    "United States": "🇺🇸", "United Kingdom": "🇬🇧", "Germany": "🇩🇪",
    "France": "🇫🇷", "Portugal": "🇵🇹", "Netherlands": "🇳🇱", "Canada": "🇨🇦",
    "Japan": "🇯🇵", "China": "🇨🇳", "Australia": "🇦🇺", "Switzerland": "🇨🇭",
    "Sweden": "🇸🇪", "Denmark": "🇩🇰", "Norway": "🇳🇴", "Spain": "🇪🇸",
    "Italy": "🇮🇹", "Belgium": "🇧🇪", "Ireland": "🇮🇪", "Taiwan": "🇹🇼",
    "South Korea": "🇰🇷", "India": "🇮🇳", "Brazil": "🇧🇷",
}


def fmt_large(v):
    if v is None: return None
    v = float(v)
    if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
    if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6:  return f"{v/1e6:.1f}M"
    return str(round(v, 2))


def sr(v, n=2):
    if v is None: return None
    try: return round(float(v), n)
    except: return None


def pct_dec(v, n=2):
    if v is None: return None
    try: return round(float(v) * 100, n)
    except: return None


def div_cagr_5y(t):
    try:
        divs = t.dividends
        if divs is None or len(divs) < 4: return None
        annual = {}
        for dt, amt in divs.items():
            annual.setdefault(dt.year, 0)
            annual[dt.year] += float(amt)
        now = datetime.now().year
        recent = {y: v for y, v in annual.items() if y >= now - 5}
        if len(recent) < 2: return None
        yrs = sorted(recent.keys())
        n = yrs[-1] - yrs[0]
        if n <= 0 or recent[yrs[0]] <= 0: return None
        return round(((recent[yrs[-1]] / recent[yrs[0]]) ** (1 / n) - 1) * 100, 2)
    except: return None


def buyback_yield(t, mkt_cap):
    try:
        if not mkt_cap or mkt_cap <= 0: return None
        cf = t.cashflow
        if cf is None or cf.empty: return None
        for rname in ["Repurchase Of Capital Stock", "Common Stock Payments"]:
            if rname in cf.index:
                amounts = [abs(float(cf.loc[rname, c])) for c in list(cf.columns)[:2]
                           if str(cf.loc[rname, c]) != "nan"]
                if amounts:
                    return round(sum(amounts) / len(amounts) / mkt_cap * 100, 2)
        return None
    except: return None


def rev_growth(t):
    try:
        fin = t.financials
        if fin is None or fin.empty: return None
        rev_rows = [r for r in fin.index if "Revenue" in str(r) or "revenue" in str(r)]
        if not rev_rows: return None
        row = fin.loc[rev_rows[0]]
        cols = [c for c in row.index if row[c] and str(row[c]) != "nan"]
        if len(cols) < 2: return None
        r1, r0 = float(row[cols[0]]), float(row[cols[1]])
        if r0 and r0 > 0:
            return round((r1 / r0 - 1) * 100, 2)
    except: return None


tickers_env = os.environ.get("TICKERS", "").strip()
mode = os.environ.get("MODE", "add").strip().lower()

if not tickers_env:
    print("No TICKERS env var — nothing to do.")
    sys.exit(0)

tickers = [t.strip().upper() for t in tickers_env.split(",") if t.strip()]
print(f"Mode: {mode} | Tickers: {tickers}")

os.makedirs("data", exist_ok=True)
existing = {}
if mode == "add" and os.path.exists("data/screener.json"):
    with open("data/screener.json", encoding="utf-8") as f:
        existing = json.load(f)
    print(f"  Loaded {len(existing)} existing tickers")

results = dict(existing)
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

for ticker in tickers:
    print(f"Fetching {ticker}...")
    try:
        t = yf.Ticker(ticker)
        info = t.info
        name = info.get("longName") or info.get("shortName")
        if not name:
            print(f"  SKIP: no data found for {ticker}")
            continue

        mkt_cap = info.get("marketCap")
        dy = info.get("dividendYield")
        if dy is None:
            div_yield = pct_dec(info.get("trailingAnnualDividendYield"))
        elif dy > 0.2:
            div_yield = sr(dy)
        else:
            div_yield = pct_dec(dy)
        if div_yield == 0.0:
            div_yield = None

        fcf = info.get("freeCashflow")
        bb = buyback_yield(t, mkt_cap)
        sh = sr((div_yield or 0) + (bb or 0)) if (div_yield or bb) else None
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")

        results[ticker] = {
            "name":             name,
            "sector":           info.get("sector") or "—",
            "flag":             COUNTRY_FLAG.get(info.get("country", ""), "🌍"),
            "exchange":         info.get("exchange") or "—",
            "currency":         info.get("currency") or "USD",
            "curPrice":         sr(price, 2),
            "marketCap":        fmt_large(mkt_cap),
            "totalDebt":        fmt_large(info.get("totalDebt")),
            "grossMargin":      pct_dec(info.get("grossMargins")),
            "netMargin":        pct_dec(info.get("profitMargins")),
            "pe":               sr(info.get("trailingPE") or info.get("forwardPE"), 1),
            "roe":              pct_dec(info.get("returnOnEquity")),
            "divYield":         div_yield,
            "buybackYield":     bb,
            "shareholderYield": sh,
            "payoutRatio":      pct_dec(info.get("payoutRatio")),
            "fcfYield":         sr(fcf / mkt_cap * 100) if fcf and mkt_cap and mkt_cap > 0 else None,
            "divCagr5y":        div_cagr_5y(t),
            "revenueGrowth":    rev_growth(t),
            "fetchedAt":        now_str,
        }
        print(f"  OK: {name} @ {price} {info.get('currency', '')}")
    except Exception as e:
        print(f"  ERROR: {e}")
    time.sleep(0.3)

with open("data/screener.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False)
print(f"\nDone! Saved {len(results)} tickers to data/screener.json")
