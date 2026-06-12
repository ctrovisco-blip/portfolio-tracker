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

def fetch_history(t, mkt_cap):
    try:
        result = {}
        fin = t.financials
        bs  = t.balance_sheet
        cf  = t.cashflow

        # Helper: get a row from a DataFrame by substring match
        def get_row(df, includes, excludes=()):
            if df is None or df.empty:
                return None
            for idx in df.index:
                s = str(idx)
                if any(inc in s for inc in includes) and not any(exc in s for exc in excludes):
                    return df.loc[idx]
            return None

        # Revenue
        rev_row = get_row(fin, ["Total Revenue", "Revenue"], ["Cost"])
        if rev_row is not None:
            revenue = {}
            for col in rev_row.index:
                try:
                    v = float(rev_row[col])
                    if v == v:  # not NaN
                        revenue[col.year] = v
                except:
                    pass
            if revenue:
                result["revenue"] = revenue

        # Gross Profit
        gp_row = get_row(fin, ["Gross Profit"])
        if gp_row is not None and rev_row is not None:
            gm = {}
            for col in gp_row.index:
                try:
                    gp = float(gp_row[col])
                    rv = float(rev_row[col]) if col in rev_row.index else float("nan")
                    if gp == gp and rv == rv and rv != 0:
                        gm[col.year] = round(gp / rv * 100, 2)
                except:
                    pass
            if gm:
                result["grossMargin"] = gm

        # Net Income
        ni_row = get_row(fin, ["Net Income"], ["Common"])
        if ni_row is None:
            ni_row = get_row(fin, ["Net Income"])
        if ni_row is not None and rev_row is not None:
            nm = {}
            for col in ni_row.index:
                try:
                    ni = float(ni_row[col])
                    rv = float(rev_row[col]) if col in rev_row.index else float("nan")
                    if ni == ni and rv == rv and rv != 0:
                        nm[col.year] = round(ni / rv * 100, 2)
                except:
                    pass
            if nm:
                result["netMargin"] = nm

        # ROE = Net Income / Stockholder Equity
        eq_row = get_row(bs, ["Stockholder", "Common Stock Equity", "Total Equity"])
        if ni_row is not None and eq_row is not None:
            roe = {}
            for col in ni_row.index:
                try:
                    ni = float(ni_row[col])
                    eq = float(eq_row[col]) if col in eq_row.index else float("nan")
                    if ni == ni and eq == eq and eq != 0:
                        roe[col.year] = round(ni / eq * 100, 2)
                except:
                    pass
            if roe:
                result["roe"] = roe

        # FCF Yield = Free Cash Flow / Market Cap
        if mkt_cap and mkt_cap > 0:
            fcf_row = get_row(cf, ["Free Cash Flow"])
            if fcf_row is not None:
                fcfy = {}
                for col in fcf_row.index:
                    try:
                        v = float(fcf_row[col])
                        if v == v:
                            fcfy[col.year] = round(v / mkt_cap * 100, 2)
                    except:
                        pass
                if fcfy:
                    result["fcfYield"] = fcfy

        # Net Income (absolute)
        if ni_row is not None:
            ni_abs = {}
            for col in ni_row.index:
                try:
                    v = float(ni_row[col])
                    if v == v:
                        ni_abs[col.year] = v
                except:
                    pass
            if ni_abs:
                result["netIncome"] = ni_abs

        # Total Debt (from balance sheet)
        debt_row = get_row(bs, ["Total Debt"])
        if debt_row is None:
            debt_row = get_row(bs, ["Long Term Debt"])
        if debt_row is not None:
            debt = {}
            for col in debt_row.index:
                try:
                    v = float(debt_row[col])
                    if v == v:
                        debt[col.year] = v
                except:
                    pass
            if debt:
                result["totalDebt"] = debt

        # Payout Ratio = Dividends Paid / Net Income
        div_paid_row = get_row(cf, ["Cash Dividends Paid", "Dividends Paid", "Common Stock Dividend Paid"])
        if div_paid_row is not None and ni_row is not None:
            pr = {}
            for col in div_paid_row.index:
                try:
                    d = abs(float(div_paid_row[col]))
                    n = float(ni_row[col]) if col in ni_row.index else float("nan")
                    if d == d and n == n and n > 0:
                        pr[col.year] = round(d / n * 100, 2)
                except:
                    pass
            if pr:
                result["payoutRatio"] = pr

        # Year-end prices (needed for P/E, div yield, buyback yield, market cap)
        price_by_year = {}
        try:
            ph = t.history(period="6y", interval="1mo")
            if ph is not None and not ph.empty:
                for yr in ph.index.year.unique():
                    yr_data = ph[ph.index.year == yr]
                    if not yr_data.empty:
                        price_by_year[yr] = float(yr_data["Close"].iloc[-1])
        except:
            pass

        # Historical shares outstanding
        shares_by_year = {}
        try:
            sf = t.get_shares_full(start="2018-01-01")
            if sf is not None and not sf.empty:
                for yr in sf.index.year.unique():
                    yr_data = sf[sf.index.year == yr]
                    if not yr_data.empty:
                        shares_by_year[yr] = float(yr_data.iloc[-1])
        except:
            pass
        # Fallback to current shares for all years if no history
        if not shares_by_year:
            try:
                cur_shares = t.info.get("sharesOutstanding")
                if cur_shares:
                    for yr in price_by_year:
                        shares_by_year[yr] = float(cur_shares)
            except:
                pass

        # Annual dividends per share
        annual_divs = {}
        try:
            divs = t.dividends
            if divs is not None and not divs.empty:
                for dt, amt in divs.items():
                    yr = dt.year
                    annual_divs[yr] = annual_divs.get(yr, 0) + float(amt)
        except:
            pass

        # Dividend Yield = annual DPS / year-end price
        if price_by_year and annual_divs:
            dy = {}
            for yr, div in annual_divs.items():
                if yr in price_by_year and price_by_year[yr] > 0:
                    dy[yr] = round(div / price_by_year[yr] * 100, 2)
            if dy:
                result["divYield"] = dy

        # P/E = year-end price / EPS (EPS = net income / shares)
        if price_by_year and ni_row is not None and shares_by_year:
            pe_h = {}
            for col in ni_row.index:
                yr = col.year
                try:
                    ni = float(ni_row[col])
                    price = price_by_year.get(yr)
                    shares = shares_by_year.get(yr) or (list(shares_by_year.values())[-1] if shares_by_year else None)
                    if ni == ni and ni > 0 and price and shares and shares > 0:
                        eps = ni / shares
                        pe_h[yr] = round(price / eps, 1)
                except:
                    pass
            if pe_h:
                result["pe"] = pe_h

        # Market Cap = shares * year-end price
        if price_by_year and shares_by_year:
            mc_h = {}
            for yr, price in price_by_year.items():
                shares = shares_by_year.get(yr)
                if shares:
                    mc_h[yr] = price * shares
            if mc_h:
                result["marketCap"] = mc_h

        # Buyback Yield = repurchase / market cap per year
        repurchase_row = get_row(cf, ["Repurchase Of Capital Stock", "Common Stock Payments"])
        if repurchase_row is not None and price_by_year and shares_by_year:
            bby = {}
            for col in repurchase_row.index:
                yr = col.year
                try:
                    buyback = abs(float(repurchase_row[col]))
                    price = price_by_year.get(yr)
                    shares = shares_by_year.get(yr) or (list(shares_by_year.values())[-1] if shares_by_year else None)
                    if buyback == buyback and price and shares:
                        mkt = price * shares
                        if mkt > 0:
                            bby[yr] = round(buyback / mkt * 100, 2)
                except:
                    pass
            if bby:
                result["buybackYield"] = bby

        # Shareholder Yield = Dividend Yield + Buyback Yield per year
        if "divYield" in result or "buybackYield" in result:
            dy_h = result.get("divYield", {})
            bb_h = result.get("buybackYield", {})
            all_years = set(dy_h) | set(bb_h)
            sh_h = {}
            for yr in all_years:
                total = (dy_h.get(yr) or 0) + (bb_h.get(yr) or 0)
                if total > 0:
                    sh_h[yr] = round(total, 2)
            if sh_h:
                result["shareholderYield"] = sh_h

        return result
    except:
        return {}


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
        # Revenue Growth YoY: comparar últimos dois anos de receita via financials
        rev_growth = None
        try:
            fin = t.financials
            if fin is not None and not fin.empty:
                rev_rows = [r for r in fin.index if "Revenue" in str(r) or "revenue" in str(r)]
                if rev_rows:
                    row = fin.loc[rev_rows[0]]
                    cols = [c for c in row.index if row[c] and str(row[c]) != "nan"]
                    if len(cols) >= 2:
                        r1, r0 = float(row[cols[0]]), float(row[cols[1]])
                        if r0 and r0 > 0:
                            rev_growth = round((r1/r0 - 1)*100, 2)
        except Exception:
            pass

        hist = fetch_history(t, mkt_cap)
        results[ticker] = {
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
            "fcfYield":         sr(fcf/mkt_cap*100) if fcf and mkt_cap and mkt_cap > 0 else None,
            "divCagr5y":        div_cagr_5y(t),
            "revenueGrowth":    rev_growth,
            "history":          hist,
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
