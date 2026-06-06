"""
fetch_earnings.py – Fetch 10-K/10-Q earnings data from SEC EDGAR.
Reads data/mr_news.json for earnings articles to determine which companies to look up.
Saves to data/mr_earnings.json.
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Well-known tickers ────────────────────────────────────────────────────────

WELL_KNOWN_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "JNJ", "V", "PG", "UNH", "HD", "BAC", "MA",
    "ABBV", "CVX", "XOM", "LLY", "AVGO", "COST", "MRK",
    "PEP", "KO", "ADBE", "CRM", "ACN", "MCD", "NFLX", "AMD",
]

WELL_KNOWN_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "NVDA": "NVIDIA Corporation",
    "TSLA": "Tesla Inc.",
    "JPM": "JPMorgan Chase & Co.",
    "JNJ": "Johnson & Johnson",
    "V": "Visa Inc.",
    "PG": "Procter & Gamble Co.",
    "UNH": "UnitedHealth Group Inc.",
    "HD": "The Home Depot Inc.",
    "BAC": "Bank of America Corporation",
    "MA": "Mastercard Incorporated",
    "ABBV": "AbbVie Inc.",
    "CVX": "Chevron Corporation",
    "XOM": "Exxon Mobil Corporation",
    "LLY": "Eli Lilly and Company",
    "AVGO": "Broadcom Inc.",
    "COST": "Costco Wholesale Corporation",
    "MRK": "Merck & Co. Inc.",
    "PEP": "PepsiCo Inc.",
    "KO": "The Coca-Cola Company",
    "ADBE": "Adobe Inc.",
    "CRM": "Salesforce Inc.",
    "ACN": "Accenture plc",
    "MCD": "McDonald's Corporation",
    "NFLX": "Netflix Inc.",
    "AMD": "Advanced Micro Devices Inc.",
}

SEC_BASE = "https://data.sec.gov"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _http_get(url: str, retries: int = 3) -> bytes | None:
    headers = {
        "User-Agent": "MarketReportBot/1.0 contact@portfolio-tracker.example.com",
        "Accept": "application/json",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 2 ** attempt
                print(f"  [WARN] Rate-limited ({url}), waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"  [WARN] HTTP {exc.code} for {url}: {exc.reason}")
            return None
        except Exception as exc:
            print(f"  [WARN] Request failed for {url}: {exc}")
            return None
    return None


def load_sec_cik_map() -> dict[str, str]:
    """Returns {TICKER: CIK_str} from SEC company_tickers.json."""
    print("Loading SEC CIK map...")
    raw = _http_get(SEC_TICKERS_URL)
    if not raw:
        print("  [WARN] Could not load SEC CIK map")
        return {}
    try:
        data = json.loads(raw)
        # Format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        mapping = {}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik    = str(entry.get("cik_str", ""))
            if ticker and cik:
                mapping[ticker] = cik
        print(f"  Loaded {len(mapping)} CIK mappings")
        return mapping
    except Exception as exc:
        print(f"  [WARN] Could not parse CIK map: {exc}")
        return {}


def extract_tickers_from_news(news_path: str, positions_path: str) -> list[str]:
    """Extract ticker symbols mentioned in earnings news articles."""
    # Build name→ticker map from positions + well-known list
    name_to_ticker: dict[str, str] = {}
    # Add well-known names
    for tk, name in WELL_KNOWN_NAMES.items():
        name_to_ticker[name.lower()] = tk
        # Also map short name (first word)
        short = name.split()[0].lower()
        if len(short) > 3:
            name_to_ticker[short] = tk

    # Load positions.json if available
    if os.path.exists(positions_path):
        try:
            with open(positions_path, encoding="utf-8") as f:
                positions = json.load(f)
            for pos in positions:
                tk   = str(pos.get("ticker", "")).upper()
                name = str(pos.get("name", ""))
                if tk and name:
                    name_to_ticker[name.lower()] = tk
        except Exception:
            pass

    # All tickers we can look up (well-known + positions)
    all_tickers = set(WELL_KNOWN_TICKERS)
    if os.path.exists(positions_path):
        try:
            with open(positions_path, encoding="utf-8") as f:
                positions = json.load(f)
            for pos in positions:
                tk = str(pos.get("ticker", "")).upper()
                if tk:
                    all_tickers.add(tk)
        except Exception:
            pass

    # Load earnings news
    found: set[str] = set()
    if not os.path.exists(news_path):
        print(f"  [WARN] {news_path} not found – using well-known tickers only")
        return sorted(WELL_KNOWN_TICKERS)

    try:
        with open(news_path, encoding="utf-8") as f:
            news = json.load(f)
        earnings_articles = news.get("earnings", [])
    except Exception as exc:
        print(f"  [WARN] Could not load {news_path}: {exc}")
        return sorted(WELL_KNOWN_TICKERS)

    for article in earnings_articles:
        text = (article.get("title", "") + " " + article.get("summary", "")).lower()
        # Match ticker symbols (2-5 uppercase letters) as words
        for ticker in all_tickers:
            if ticker.lower() in text:
                found.add(ticker)
        # Match company names
        for name_lc, ticker in name_to_ticker.items():
            if name_lc in text:
                found.add(ticker)

    if not found:
        print("  No specific companies found in earnings news; using well-known tickers")
        return sorted(WELL_KNOWN_TICKERS)

    print(f"  Found {len(found)} companies in earnings news: {sorted(found)}")
    return sorted(found)


def get_metric_annual(facts_gaap: dict, *keys: str) -> tuple[float | None, float | None]:
    """
    Try keys in order; return (latest_annual_value, prev_annual_value).
    Looks at 10-K filings only (form == '10-K').
    """
    for key in keys:
        concept = facts_gaap.get(key)
        if not concept:
            continue
        units = concept.get("units", {})
        # USD or shares
        for unit_key in ("USD", "shares", "USD/shares"):
            unit_data = units.get(unit_key, [])
            if not unit_data:
                continue
            # Filter to annual (10-K) filings
            annual = [
                entry for entry in unit_data
                if entry.get("form") in ("10-K", "20-F", "40-F")
                and entry.get("val") is not None
            ]
            if not annual:
                continue
            # Deduplicate by (end date, accn), keep latest accn per end date
            by_end: dict[str, dict] = {}
            for entry in annual:
                end = entry.get("end", "")
                existing = by_end.get(end)
                if existing is None or entry.get("accn", "") > existing.get("accn", ""):
                    by_end[end] = entry
            # Sort by end date descending
            sorted_entries = sorted(by_end.values(), key=lambda e: e.get("end", ""), reverse=True)
            if len(sorted_entries) >= 2:
                return float(sorted_entries[0]["val"]), float(sorted_entries[1]["val"])
            elif len(sorted_entries) == 1:
                return float(sorted_entries[0]["val"]), None
    return None, None


def yoy_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def make_metric(current: float | None, previous: float | None) -> dict | None:
    if current is None:
        return None
    return {
        "value": current,
        "prev": previous,
        "yoy_pct": yoy_pct(current, previous),
    }


# ── Main fetch for one ticker ─────────────────────────────────────────────────

def fetch_company(ticker: str, cik: str, cik_map: dict) -> dict | None:
    cik_padded = str(int(cik)).zfill(10)
    url = f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"
    print(f"  Fetching {ticker} (CIK {cik_padded})...")

    raw = _http_get(url)
    if not raw:
        return None
    time.sleep(0.2)

    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f"    [WARN] JSON parse error for {ticker}: {exc}")
        return None

    entity_name = data.get("entityName", WELL_KNOWN_NAMES.get(ticker, ticker))

    # Try us-gaap first, then ifrs-full
    facts_gaap = data.get("facts", {}).get("us-gaap") or data.get("facts", {}).get("ifrs-full", {})
    if not facts_gaap:
        print(f"    [WARN] No us-gaap/ifrs-full facts for {ticker}")
        return None

    revenue_cur, revenue_prev = get_metric_annual(
        facts_gaap,
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
    )
    ni_cur, ni_prev = get_metric_annual(facts_gaap, "NetIncomeLoss")
    eps_cur, eps_prev = get_metric_annual(facts_gaap, "EarningsPerShareBasic")
    ebit_cur, ebit_prev = get_metric_annual(facts_gaap, "OperatingIncomeLoss")
    assets_cur, assets_prev = get_metric_annual(facts_gaap, "Assets")

    # Determine fiscal year end from most recent 10-K revenue entry
    fiscal_year = ""
    for key in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss"):
        concept = facts_gaap.get(key)
        if not concept:
            continue
        for unit_data in concept.get("units", {}).values():
            annual = [e for e in unit_data if e.get("form") in ("10-K", "20-F", "40-F")]
            if annual:
                latest = max(annual, key=lambda e: e.get("end", ""))
                fiscal_year = latest.get("end", "")[:4]
                break
        if fiscal_year:
            break

    result = {
        "ticker": ticker,
        "name": entity_name,
        "cik": cik_padded,
        "fiscal_year_end": fiscal_year,
    }

    if make_metric(revenue_cur, revenue_prev):
        result["revenue"] = make_metric(revenue_cur, revenue_prev)
    if make_metric(ni_cur, ni_prev):
        result["net_income"] = make_metric(ni_cur, ni_prev)
    if make_metric(eps_cur, eps_prev):
        result["eps_basic"] = make_metric(eps_cur, eps_prev)
    if make_metric(ebit_cur, ebit_prev):
        result["operating_income"] = make_metric(ebit_cur, ebit_prev)
    if make_metric(assets_cur, assets_prev):
        result["total_assets"] = make_metric(assets_cur, assets_prev)

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("data", exist_ok=True)

    news_path      = os.path.join("data", "mr_news.json")
    positions_path = os.path.join("data", "positions.json")
    out_path       = os.path.join("data", "mr_earnings.json")

    tickers = extract_tickers_from_news(news_path, positions_path)
    print(f"Processing {len(tickers)} tickers...")

    cik_map = load_sec_cik_map()
    if not cik_map:
        print("[WARN] Empty CIK map – cannot fetch SEC data")
        with open(out_path, "w") as f:
            json.dump([], f)
        return

    results = []
    for ticker in tickers:
        cik = cik_map.get(ticker)
        if not cik:
            print(f"  [SKIP] No CIK found for {ticker}")
            continue
        entry = fetch_company(ticker, cik, cik_map)
        if entry:
            results.append(entry)

    print(f"\nFetched earnings data for {len(results)} companies")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
