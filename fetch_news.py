"""
Fetch recent news for each portfolio ticker via yfinance.
Reads:  data/positions.json + metadata.json
Writes: data/news.json  →  {ticker: [{title, url, source, publishedAt}]}
"""
import json, os, time
from datetime import datetime, timezone

import yfinance as yf

with open("data/positions.json", encoding="utf-8") as f:
    positions = json.load(f)
with open("metadata.json", encoding="utf-8") as f:
    METADATA = json.load(f)

LIMIT = 10  # max articles per ticker

results = {}
for p in positions:
    ticker = p["ticker"]
    yf_sym = METADATA.get(ticker, {}).get("yf")
    if not yf_sym:
        print(f"SKIP {ticker}")
        results[ticker] = []
        continue
    print(f"News for {ticker} ({yf_sym})...")
    try:
        t = yf.Ticker(yf_sym)
        raw = t.news or []
        articles = []
        for item in raw[:LIMIT]:
            content = item.get("content", {})
            title   = content.get("title") or item.get("title") or ""
            url     = (content.get("canonicalUrl", {}) or {}).get("url") or \
                      (content.get("clickThroughUrl", {}) or {}).get("url") or \
                      item.get("link") or ""
            # Source
            provider = content.get("provider") or item.get("publisher") or {}
            source   = (provider.get("displayName") if isinstance(provider, dict) else provider) or ""
            # Timestamp
            pub_ts   = content.get("pubDate") or content.get("displayTime") or \
                       item.get("providerPublishTime")
            if isinstance(pub_ts, str):
                try:
                    # ISO format
                    pub_ts = int(datetime.fromisoformat(pub_ts.replace("Z","+00:00")).timestamp())
                except Exception:
                    pub_ts = None
            if not title or not url:
                continue
            articles.append({
                "title": title,
                "url":   url,
                "source": source,
                "ts":    pub_ts,  # unix timestamp or None
            })
        results[ticker] = articles
        print(f"  {len(articles)} articles")
    except Exception as e:
        print(f"  ERROR: {e}")
        results[ticker] = []
    time.sleep(0.3)

os.makedirs("data", exist_ok=True)
with open("data/news.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, separators=(",",":"))
print("Done!")
