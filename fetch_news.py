"""
Fetch recent news for portfolio + screener tickers via yfinance.
Reads:  data/positions.json + metadata.json + data/screener.json
Writes: data/news.json  →  {ticker: [{title, url, source, ts}]}
"""
import json, os, time
from datetime import datetime, timezone

import yfinance as yf

with open("data/positions.json", encoding="utf-8") as f:
    positions = json.load(f)
with open("metadata.json", encoding="utf-8") as f:
    METADATA = json.load(f)

screener = {}
if os.path.exists("data/screener.json"):
    with open("data/screener.json", encoding="utf-8") as f:
        screener = json.load(f)

LIMIT = 10  # max articles per ticker

# Build map: display_ticker → yf_symbol
to_fetch = {}
for p in positions:
    yf_sym = METADATA.get(p["ticker"], {}).get("yf")
    if yf_sym:
        to_fetch[p["ticker"]] = yf_sym

# Screener tickers are already yf symbols
for ticker in screener:
    if ticker not in to_fetch:          # avoid duplicates
        to_fetch[ticker] = ticker

existing = {}
if os.path.exists("data/news.json"):
    with open("data/news.json", encoding="utf-8") as f:
        existing = json.load(f)

results = dict(existing)

def parse_article(item):
    content = item.get("content", {})
    title   = content.get("title") or item.get("title") or ""
    url     = (content.get("canonicalUrl", {}) or {}).get("url") or \
              (content.get("clickThroughUrl", {}) or {}).get("url") or \
              item.get("link") or ""
    provider = content.get("provider") or item.get("publisher") or {}
    source   = (provider.get("displayName") if isinstance(provider, dict) else provider) or ""
    pub_ts   = content.get("pubDate") or content.get("displayTime") or \
               item.get("providerPublishTime")
    if isinstance(pub_ts, str):
        try:
            pub_ts = int(datetime.fromisoformat(pub_ts.replace("Z", "+00:00")).timestamp())
        except Exception:
            pub_ts = None
    if not title or not url:
        return None
    return {"title": title, "url": url, "source": source, "ts": pub_ts}

for display_ticker, yf_sym in to_fetch.items():
    print(f"News {display_ticker} ({yf_sym})...")
    try:
        t = yf.Ticker(yf_sym)
        raw = t.news or []
        articles = [a for a in (parse_article(i) for i in raw[:LIMIT]) if a]
        results[display_ticker] = articles
        print(f"  {len(articles)} articles")
    except Exception as e:
        print(f"  ERROR: {e}")
        results.setdefault(display_ticker, [])
    time.sleep(0.3)

os.makedirs("data", exist_ok=True)
with open("data/news.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, separators=(",", ":"))
print("Done!")
