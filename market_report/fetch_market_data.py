"""
fetch_market_data.py – Fetch weekly market data using yfinance.
Saves to data/mr_market.json.

Data fetched:
  - Index weekly change: S&P 500, Nasdaq 100, Dow Jones
  - MAG-7 weekly + YTD change
  - S&P 500 top 10 gainers / top 10 losers (weekly)
  - S&P 500 stocks within 3% of their 52-week low
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

try:
    import yfinance as yf
    import pandas as pd
except ImportError as exc:
    raise SystemExit(f"[ERROR] Missing dependency: {exc}. Run: pip install yfinance pandas") from exc


# ── Constants ─────────────────────────────────────────────────────────────────

INDICES = {
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "Dow Jones": "^DJI",
}

MAG7 = [
    ("AAPL",  "Apple"),
    ("MSFT",  "Microsoft"),
    ("GOOGL", "Alphabet"),
    ("AMZN",  "Amazon"),
    ("META",  "Meta Platforms"),
    ("NVDA",  "NVIDIA"),
    ("TSLA",  "Tesla"),
]

SP500_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
BATCH_SIZE = 200


# ── Helpers ───────────────────────────────────────────────────────────────────

def pct_change(new: float, old: float) -> float | None:
    if old and old != 0:
        return round((new - old) / abs(old) * 100, 2)
    return None


def weekly_pct(hist: "pd.DataFrame") -> float | None:
    """Compute (last_close - first_close) / first_close * 100 from a history df."""
    if hist is None or hist.empty or len(hist) < 2:
        return None
    close = hist["Close"]
    first = float(close.iloc[0])
    last  = float(close.iloc[-1])
    return pct_change(last, first)


def ytd_pct(ticker_obj) -> float | None:
    """Compute YTD % change for a ticker."""
    try:
        hist = ticker_obj.history(period="ytd", auto_adjust=True)
        if hist is None or hist.empty or len(hist) < 2:
            return None
        close = hist["Close"]
        first = float(close.iloc[0])
        last  = float(close.iloc[-1])
        return pct_change(last, first)
    except Exception:
        return None


# ── Fetch indices ─────────────────────────────────────────────────────────────

def fetch_indices() -> dict:
    print("Fetching index data...")
    result = {}
    tickers_str = " ".join(INDICES.values())
    try:
        data = yf.download(tickers_str, period="5d", auto_adjust=True, progress=False, group_by="ticker")
    except Exception as exc:
        print(f"  [WARN] Could not download index data: {exc}")
        return result

    for name, ticker in INDICES.items():
        try:
            if len(INDICES) == 1:
                hist = data
            else:
                hist = data[ticker] if ticker in data.columns.get_level_values(0) else None

            if hist is None or hist.empty:
                print(f"  [WARN] No data for {ticker}")
                continue

            close_series = hist["Close"].dropna()
            if len(close_series) < 2:
                continue
            last_close = float(close_series.iloc[-1])
            first_close = float(close_series.iloc[0])
            w_pct = pct_change(last_close, first_close)
            result[name] = {
                "ticker": ticker,
                "weekly_pct": w_pct,
                "close": round(last_close, 2),
            }
            print(f"  {name} ({ticker}): {last_close:.2f}  weekly={w_pct:+.2f}%")
        except Exception as exc:
            print(f"  [WARN] Could not process {ticker}: {exc}")

    return result


# ── Fetch MAG-7 ───────────────────────────────────────────────────────────────

def fetch_mag7() -> list:
    print("Fetching MAG-7 data...")
    tickers_str = " ".join(t for t, _ in MAG7)
    result = []

    try:
        data = yf.download(tickers_str, period="5d", auto_adjust=True, progress=False, group_by="ticker")
    except Exception as exc:
        print(f"  [WARN] Could not download MAG-7 data: {exc}")
        return result

    for ticker, name in MAG7:
        try:
            if len(MAG7) == 1:
                hist = data
            else:
                hist = data[ticker] if ticker in data.columns.get_level_values(0) else None

            if hist is None or hist.empty:
                print(f"  [WARN] No data for {ticker}")
                continue

            close_series = hist["Close"].dropna()
            if len(close_series) < 2:
                continue
            last_close = float(close_series.iloc[-1])
            first_close = float(close_series.iloc[0])
            w_pct = pct_change(last_close, first_close)

            # YTD
            t_obj = yf.Ticker(ticker)
            ytd = ytd_pct(t_obj)

            entry = {
                "ticker": ticker,
                "name": name,
                "close": round(last_close, 2),
                "weekly_pct": w_pct,
                "ytd_pct": ytd,
            }
            result.append(entry)
            print(f"  {ticker}: {last_close:.2f}  weekly={w_pct:+.2f}%  ytd={ytd:+.2f}%" if ytd else
                  f"  {ticker}: {last_close:.2f}  weekly={w_pct:+.2f}%")
        except Exception as exc:
            print(f"  [WARN] Could not process {ticker}: {exc}")

    # Sort by weekly_pct descending
    result.sort(key=lambda x: (x["weekly_pct"] is not None, x["weekly_pct"] or 0), reverse=True)
    return result


# ── Fetch S&P 500 tickers ─────────────────────────────────────────────────────

def get_sp500_tickers() -> list[str]:
    print("Fetching S&P 500 ticker list from Wikipedia...")
    try:
        tables = pd.read_html(SP500_WIKIPEDIA_URL)
        df = tables[0]
        tickers = df["Symbol"].tolist()
        # Normalize: BRK.B → BRK-B
        tickers = [str(t).replace(".", "-") for t in tickers]
        print(f"  Found {len(tickers)} S&P 500 tickers")
        return tickers
    except Exception as exc:
        print(f"  [WARN] Could not fetch S&P 500 tickers from Wikipedia: {exc}")
        # Fallback: return a minimal list
        return [t for t, _ in MAG7]


# ── Fetch S&P 500 movers ──────────────────────────────────────────────────────

def fetch_sp500_movers(tickers: list[str]) -> tuple[list, list]:
    """Return (top_10_gainers, top_10_losers) as lists of dicts."""
    print(f"Fetching S&P 500 weekly data for {len(tickers)} tickers (batch size {BATCH_SIZE})...")
    returns: dict[str, float] = {}
    closes: dict[str, float] = {}

    # Batch download
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        batch_str = " ".join(batch)
        print(f"  Batch {i // BATCH_SIZE + 1}: downloading {len(batch)} tickers...")
        try:
            data = yf.download(
                batch_str,
                period="5d",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
            )
        except Exception as exc:
            print(f"  [WARN] Batch {i // BATCH_SIZE + 1} failed: {exc}")
            continue

        if data.empty:
            continue

        for ticker in batch:
            try:
                if len(batch) == 1:
                    hist = data
                else:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    hist = data[ticker]

                close_s = hist["Close"].dropna()
                if len(close_s) < 2:
                    continue
                first = float(close_s.iloc[0])
                last  = float(close_s.iloc[-1])
                w_pct = pct_change(last, first)
                if w_pct is not None:
                    returns[ticker] = w_pct
                    closes[ticker] = round(last, 2)
            except Exception:
                continue

    print(f"  Got weekly returns for {len(returns)} tickers")
    if not returns:
        return [], []

    # Sort
    sorted_by_ret = sorted(returns.items(), key=lambda x: x[1], reverse=True)

    def _entry(ticker: str) -> dict:
        return {
            "ticker": ticker,
            "name": ticker,  # Name lookup via yf is slow; use ticker as name
            "close": closes.get(ticker, 0.0),
            "weekly_pct": round(returns[ticker], 2),
        }

    gainers = [_entry(t) for t, _ in sorted_by_ret[:10]]
    losers  = [_entry(t) for t, _ in sorted_by_ret[-10:][::-1]]
    return gainers, losers


# ── Fetch near-52-week lows ───────────────────────────────────────────────────

def fetch_near_52w_lows(tickers: list[str], threshold_pct: float = 3.0) -> list:
    """Return tickers within threshold_pct% of their 52-week low."""
    print(f"Checking {len(tickers)} tickers for near-52-week lows (threshold={threshold_pct}%)...")
    result = []

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            low52  = getattr(fi, "year_low",  None) or getattr(fi, "fifty_two_week_low",  None)
            high52 = getattr(fi, "year_high", None) or getattr(fi, "fifty_two_week_high", None)
            last   = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)

            if low52 is None or high52 is None or last is None:
                continue
            if low52 <= 0:
                continue

            pct_from_low = pct_change(last, low52)
            if pct_from_low is not None and pct_from_low <= threshold_pct:
                result.append({
                    "ticker": ticker,
                    "name": ticker,
                    "close": round(float(last), 2),
                    "52w_low":  round(float(low52), 2),
                    "52w_high": round(float(high52), 2),
                    "pct_from_low": round(float(pct_from_low), 2),
                })
        except Exception:
            continue

    result.sort(key=lambda x: x["pct_from_low"])
    print(f"  Found {len(result)} tickers near 52-week low")
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("data", exist_ok=True)

    indices  = fetch_indices()
    mag7     = fetch_mag7()
    sp500_tickers = get_sp500_tickers()
    gainers, losers = fetch_sp500_movers(sp500_tickers)
    near_lows = fetch_near_52w_lows(sp500_tickers)

    output = {
        "indices":      indices,
        "mag7":         mag7,
        "top_gainers":  gainers,
        "top_losers":   losers,
        "near_52w_low": near_lows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = os.path.join("data", "mr_market.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved market data to {out_path}")


if __name__ == "__main__":
    main()
