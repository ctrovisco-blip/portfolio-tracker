"""
Gera o dashboard de "qualidade de entrada" por posição.

Lê:     data/positions.json + data/fundamentals.json + data/chart_data.json
        + data/entry_config.json (opcional — valores intrínsecos do utilizador)
Escreve: entry_dashboard.html

Modelo de score (0–100) por posição, três pilares:
  Valor      — margem de segurança vs. valor intrínseco (input do utilizador)
               + P/E vs. média histórica
  Rendimento — yield atual vs. mediana histórica + regra de Chowder
               (yield + CAGR do dividendo 5A) + penalização por payout
  Timing     — preço vs. MA50/MA200, RSI(14), distância ao máximo de 52 semanas

Pesos base 40/30/30, reponderados dinamicamente quando um pilar não se
aplica (ETFs → só timing; yield < 1.5% → rendimento com peso reduzido).
O score final e o detalhe são calculados em JS na própria página, para que
o input de valor intrínseco (guardado em localStorage) recalcule ao vivo.
"""
import json, os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))

def load(name, default=None):
    path = os.path.join(BASE, "data", name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)

positions    = load("positions.json", [])
fundamentals = load("fundamentals.json", {})
chart_data   = load("chart_data.json", {})
entry_config = load("entry_config.json", {}) or {}

CUR_YEAR = datetime.now().year


# ── Indicadores técnicos sobre a série de 1 ano ──────────────────────────────

def price_series_1y(ticker, cur_price):
    """Reconstrói preços absolutos a partir da série de % acumulada (1y)."""
    series = (chart_data.get("stocks", {}).get(ticker) or {}).get("1y")
    if not series or len(series) < 30:
        return None, None
    dates = sorted(series.keys())
    rel = [1 + series[d] / 100 for d in dates]
    scale = cur_price / rel[-1]
    return dates, [r * scale for r in rel]

def sma(prices, n):
    if len(prices) < n:
        return None
    return sum(prices[-n:]) / n

def rsi14(prices):
    if len(prices) < 30:
        return None
    gains, losses = 0.0, 0.0
    # Wilder: média simples nos primeiros 14, depois suavização
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    avg_g = sum(max(d, 0) for d in deltas[:14]) / 14
    avg_l = sum(max(-d, 0) for d in deltas[:14]) / 14
    for d in deltas[14:]:
        avg_g = (avg_g * 13 + max(d, 0)) / 14
        avg_l = (avg_l * 13 + max(-d, 0)) / 14
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


# ── Fundamentais ─────────────────────────────────────────────────────────────

def hist_median(hist, exclude_current_year=True):
    """Mediana dos valores históricos anuais (só anos completos)."""
    if not hist:
        return None
    vals = [v for y, v in hist.items()
            if v is not None and (not exclude_current_year or int(y) < CUR_YEAR)]
    if len(vals) < 3:
        return None
    vals.sort()
    n = len(vals)
    return vals[n//2] if n % 2 else (vals[n//2 - 1] + vals[n//2]) / 2

def pe_hist_avg(hist):
    """Mediana do P/E histórico. Filtra anos de lucros ~0 (P/E absurdo)
    que rebentariam uma média simples (ex.: Rolls-Royce 2022)."""
    if not hist:
        return None
    vals = sorted(v for v in hist.values() if v is not None and 0 < v < 200)
    if len(vals) < 2:
        return None
    n = len(vals)
    return vals[n//2] if n % 2 else (vals[n//2 - 1] + vals[n//2]) / 2


# ── Montar métricas por posição ──────────────────────────────────────────────

rows = []
for p in positions:
    t = p["ticker"]
    f = fundamentals.get(t, {}) or {}
    hist = f.get("history", {}) or {}
    cfg = entry_config.get(t, {}) or {}

    cur_price = p.get("curPrice")
    dates, prices = price_series_1y(t, cur_price) if cur_price else (None, None)

    ma50 = ma200 = rsi = hi52 = lo52 = None
    spark, spark_dates, buy_idx = [], [], []
    if prices:
        ma50, ma200 = sma(prices, 50), sma(prices, 200)
        rsi = rsi14(prices)
        hi52, lo52 = max(prices), min(prices)
        # Amostragem da sparkline (~90 pontos) + marcas de compra
        step = max(1, len(prices) // 90)
        idx_sampled = list(range(0, len(prices), step))
        if idx_sampled[-1] != len(prices) - 1:
            idx_sampled.append(len(prices) - 1)
        spark = [round(prices[i], 4) for i in idx_sampled]
        spark_dates = [dates[i] for i in idx_sampled]
        first_date = dates[0]
        for bd in p.get("buyDates", []):
            if bd >= first_date:
                # índice da amostra mais próxima da data de compra
                j = min(range(len(spark_dates)),
                        key=lambda k: abs((datetime.fromisoformat(spark_dates[k])
                                           - datetime.fromisoformat(bd)).days))
                buy_idx.append(j)

    sector = p.get("sector", "")
    is_etf  = "ETF" in sector or "ETC" in sector
    is_reit = "REIT" in sector

    rows.append({
        "ticker": t, "name": p.get("name", t), "sector": sector,
        "flag": p.get("flag", ""), "cur": p.get("cur", ""),
        "price": cur_price, "avgCost": p.get("avgPrice"),
        "qty": p.get("qty"), "ppl": p.get("ppl"),
        "isEtf": is_etf, "isReit": is_reit,
        "payoutUnreliable": is_reit or bool(cfg.get("payoutUnreliable")),
        "pe": f.get("pe"), "peAvg": pe_hist_avg(hist.get("pe")),
        "yield": f.get("divYield"),
        "yieldHist": hist_median(hist.get("divYield")),
        "divCagr": f.get("divCagr5y"), "payout": f.get("payoutRatio"),
        "fcfYield": f.get("fcfYield"),
        "ma50": ma50, "ma200": ma200, "rsi": rsi,
        "hi52": hi52, "lo52": lo52,
        "spark": spark, "sparkDates": spark_dates, "buyIdx": sorted(set(buy_idx)),
        "iv": cfg.get("intrinsicValue"),
        "ivNote": cfg.get("note"),
    })

payload = {
    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    "positions": rows,
}

with open(os.path.join(BASE, "entry_template.html"), encoding="utf-8") as f:
    template = f.read()

html = template.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))

out = os.path.join(BASE, "entry_dashboard.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

print(f"entry_dashboard.html gerado — {len(rows)} posições, {payload['generatedAt']}")
