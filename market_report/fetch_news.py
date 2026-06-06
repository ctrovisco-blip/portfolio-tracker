"""
fetch_news.py – Fetch news from RSS feeds and categorize into macro/earnings/business.
Saves to data/mr_news.json.
"""

import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

# ── RSS Feeds ────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    ("WSJ",        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("WSJ",        "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    ("WSJ",        "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml"),
    ("FT",         "https://www.ft.com/rss/home"),
    ("Bloomberg",  "https://feeds.bloomberg.com/markets/news.rss"),
    ("Bloomberg",  "https://feeds.bloomberg.com/economics/news.rss"),
    ("Bloomberg",  "https://feeds.bloomberg.com/technology/news.rss"),
    ("Economist",  "https://www.economist.com/finance-and-economics/rss.xml"),
    ("Economist",  "https://www.economist.com/business/rss.xml"),
    ("Economist",  "https://www.economist.com/leaders/rss.xml"),
]

# ── Keyword buckets ───────────────────────────────────────────────────────────

MACRO_KEYWORDS = [
    "fed", "federal reserve", "interest rate", "inflation", "cpi", "gdp",
    "jobs", "employment", "geopolit", "tariff", "oil", "commodit", "treasury",
    "recession", "central bank", "rate cut", "rate hike", "war", "sanctions",
    "opec", "gold", "monetary policy", "fiscal policy", "deficit", "debt",
    "unemployment", "payroll", "nonfarm", "yield", "bond", "dollar", "euro",
    "currency", "exchange rate", "pce", "fomc", "powell", "lagarde",
    "bank of england", "boe", "ecb", "imf", "world bank", "g7", "g20",
    "trade war", "import", "export", "supply chain", "energy", "natural gas",
    "crude", "brent", "wti", "ukraine", "russia", "china trade", "geopolitical",
    "political", "election", "government", "congress", "senate", "white house",
    "budget", "spending", "stimulus",
]

EARNINGS_KEYWORDS = [
    "earnings", "quarterly results", "q1", "q2", "q3", "q4", "revenue",
    "profit", "eps", "guidance", "beats", "misses", "net income", "results",
    "fiscal year", "annual report", "quarter", "beat estimates", "miss estimates",
    "raised guidance", "lowered guidance", "revenue growth", "profit margin",
    "operating income", "cash flow", "ebitda", "dividend", "buyback",
    "share repurchase", "10-k", "10-q", "sec filing",
]

BUSINESS_KEYWORDS = [
    "partnership", "deal", "merger", "acquisition", "launches", "ai",
    "artificial intelligence", "technology", "product", "expands", "funding",
    "ipo", "joint venture", "collaboration", "agreement", "contract",
    "investment", "startup", "venture capital", "private equity", "spin-off",
    "restructuring", "layoffs", "hiring", "ceo", "executive", "leadership",
    "innovation", "patent", "research", "development", "cloud", "software",
    "hardware", "semiconductor", "chip", "data center", "electric vehicle",
    "ev", "battery", "renewable", "solar", "wind", "biotech", "pharma",
    "drug approval", "fda", "clinical trial", "digital", "platform", "app",
    "subscription", "streaming", "ecommerce", "retail", "store",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

class _MLStripper(HTMLParser):
    """Strip HTML tags from text."""
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return "".join(self.fed)


def strip_html(text: str) -> str:
    s = _MLStripper()
    try:
        s.feed(text)
        return s.get_data()
    except Exception:
        return re.sub(r"<[^>]+>", "", text)


def clean_text(text: str, max_len: int = 300) -> str:
    text = strip_html(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def parse_date(date_str: str) -> datetime | None:
    """Parse RSS date string to aware datetime."""
    if not date_str:
        return None
    # Try RFC 2822 (most RSS feeds)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Try ISO 8601
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def categorize(title: str, summary: str) -> str | None:
    """Return 'macro', 'earnings', 'business', or None if no match."""
    text = (title + " " + summary).lower()
    # Earnings first (most specific)
    for kw in EARNINGS_KEYWORDS:
        if kw in text:
            return "earnings"
    for kw in MACRO_KEYWORDS:
        if kw in text:
            return "macro"
    for kw in BUSINESS_KEYWORDS:
        if kw in text:
            return "business"
    return None


def fetch_feed(source: str, url: str, cutoff: datetime, seen_links: set) -> list[dict]:
    """Fetch and parse one RSS feed. Returns list of article dicts."""
    articles = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; MarketReportBot/1.0; "
            "+https://github.com/portfolio-tracker)"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except Exception as exc:
        print(f"  [WARN] Could not fetch {url}: {exc}")
        return articles

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"  [WARN] Could not parse XML from {url}: {exc}")
        return articles

    # Support both RSS 2.0 (<channel><item>) and Atom (<entry>)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//atom:entry", ns)

    for item in items:
        def _text(tag: str, default: str = "") -> str:
            el = item.find(tag) or item.find(f"atom:{tag}", ns)
            if el is None:
                return default
            return (el.text or "").strip()

        title = _text("title")
        link = _text("link")
        # Atom <link> is an attribute
        if not link:
            link_el = item.find("atom:link", ns) or item.find("link")
            if link_el is not None:
                link = link_el.get("href", "") or (link_el.text or "")

        # Skip duplicates
        if link and link in seen_links:
            continue

        pub_date = _text("pubDate") or _text("published") or _text("updated")
        dt = parse_date(pub_date)
        if dt is None:
            # Include with today's date if we can't parse
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        if dt < cutoff:
            continue

        summary_raw = (
            _text("description")
            or _text("summary")
            or _text("content")
            or _text("atom:content", ns)
        )
        summary = clean_text(summary_raw)

        if not title:
            continue

        article = {
            "title": clean_text(title, 200),
            "summary": summary,
            "link": link,
            "source": source,
            "date": dt.strftime("%Y-%m-%d"),
        }
        if link:
            seen_links.add(link)
        articles.append(article)

    return articles


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("data", exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    print(f"Fetching news from {len(RSS_FEEDS)} feeds (cutoff: {cutoff.date()})...")

    buckets: dict[str, list[dict]] = {"macro": [], "earnings": [], "business": []}
    seen_links: set[str] = set()
    total = 0

    for source, url in RSS_FEEDS:
        print(f"  Fetching {source}: {url}")
        articles = fetch_feed(source, url, cutoff, seen_links)
        print(f"    → {len(articles)} articles")
        for art in articles:
            cat = categorize(art["title"], art["summary"])
            if cat:
                buckets[cat].append(art)
                total += 1

    # Sort each bucket by date descending
    for cat in buckets:
        buckets[cat].sort(key=lambda a: a["date"], reverse=True)

    print(f"\nTotal categorized: {total}")
    for cat, arts in buckets.items():
        print(f"  {cat}: {len(arts)} articles")

    out_path = os.path.join("data", "mr_news.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(buckets, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
