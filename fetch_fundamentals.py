"""
Fetch fundamental data via yfinance.
Reads:  data/positions.json + metadata.json
Writes: data/fundamentals.json
"""
import json, time, os
import yfinance as yf
from datetime import datetime

with open("data/positions.json", encoding="utf-8") as f:
    positions = json.load(f)
with open("metadata.json", encoding="utf-8") as f:
    METADATA = json.load(f)

def fmt_large(v):
    if v is None: return None
    v = float(v)
    if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
    if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6:  return f"{v/1e6:.1f}M"
    return str(round(v,2))

def sr(v, n=2):
    if v is None: return None
    try: return round(float(v), n)
    except: return None

def pct_dec(v, n=2):
    if v is None: return None
    try: return round(float(v)*100, n)
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
        recent = {y: v for y, v in annual.items() if y >= now-5}
        if len(recent) < 2: return None
        yrs = sorted(recent.keys())
        n = yrs[-1] - yrs[0]
        if n <= 0 or recent[yrs[0]] <= 0: return None
        return round(((recent[yrs[-1]]/recent[yrs[0]])**(1/n)-1)*100, 2)
    except: return None

def buyback_yield(t, mkt_cap):
    try:
        if not mkt_cap or mkt_cap <= 0: return None
        cf = t.cashflow
        if cf is None or cf.empty: return None
        for rname in ["Repurchase Of Capital Stock","Common Stock Payments"]:
            if rname in cf.index:
                amounts = [abs(float(cf.loc[rname, c])) for c in list(cf.columns)[:2]
                           if str(cf.loc[rname, c]) != "nan"]
                if amounts:
                    return round(sum(amounts)/len(amounts)/mkt_cap*100, 2)
        return None
    except: return None

results = {}
for p in positions:
    ticker = p["ticker"]
    yf_sym = METADATA.get(ticker, {}).get("yf")
    if yf_sym is None:
        print(f"SKIP {ticker}")
        results[ticker] = None
        continue
    print(f"Fetching {ticker} ({yf_sym})...")
    try:
        t = yf.Ticker(yf_sym)
        info = t.info
        mkt_cap = info.get("marketCap")
        dy = info.get("dividendYield")
        if dy is None:
            div_yield = pct_dec(info.get("trailingAnnualDividendYield"))
        elif dy > 0.2:
            div_yield = sr(dy)
        else:
            div_yield = pct_dec(dy)
        if div_yield == 0.0: div_yield = None
        fcf = info.get("freeCashflow")
        rev = info.get("totalRevenue")
        bb = buyback_yield(t, mkt_cap)
        sh = sr((div_yield or 0)+(bb or 0)) if (div_yield or bb) else None
        results[ticker] = {
            "marketCap":        fmt_large(mkt_cap),
            "totalDebt":        fmt_large(info.get("totalDebt")),
            "grossMargin":      pct_dec(info.get("grossMargins")),
            "pe":               sr(info.get("trailingPE") or info.get("forwardPE"), 1),
            "divYield":         div_yield,
            "buybackYield":     bb,
            "shareholderYield": sh,
            "payoutRatio":      pct_dec(info.get("payoutRatio")),
            "fcfRatio":         sr(fcf/rev*100) if fcf and rev and rev > 0 else None,
            "divCagr5y":        div_cagr_5y(t),
        }
        print(f"  PE={results[ticker][chr(112)+chr(101)]} div={results[ticker][chr(100)+chr(105)+chr(118)+chr(89)+chr(105)+chr(101)+chr(108)+chr(100)]}%")
    except Exception as e:
        print(f"  ERROR: {e}")
        results[ticker] = None
    time.sleep(0.3)

os.makedirs("data", exist_ok=True)
with open("data/fundamentals.json", "w") as f:
    json.dump(results, f)
print("Done!")
