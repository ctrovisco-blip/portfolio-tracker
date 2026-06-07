"""
Generate a weekly market report as a self-contained HTML file.
Reads:  data/positions.json, data/chart_data.json, data/fx.json, metadata.json
Writes: weekly_report.html
"""
import json
from datetime import datetime, timedelta

# ── Load data ────────────────────────────────────────────────────────────────
with open("data/positions.json", encoding="utf-8") as f:
    positions = json.load(f)
with open("data/chart_data.json", encoding="utf-8") as f:
    chart_data = json.load(f)
with open("data/fx.json", encoding="utf-8") as f:
    FX = json.load(f)
with open("metadata.json", encoding="utf-8") as f:
    metadata = json.load(f)

try:
    with open("data/fundamentals.json", encoding="utf-8") as f:
        fundamentals = json.load(f)
except Exception:
    fundamentals = {}

generated_at = datetime.utcnow()

# ── Helpers ──────────────────────────────────────────────────────────────────
def pos_value_eur(p):
    return p.get("qty", 0) * p.get("curPrice", 0) * FX.get(p.get("cur", "€"), 1.0)

def weekly_perf_from_3mo(series_3mo):
    """
    Derive weekly % change from a normalized 3mo series.
    The series stores % relative to the first price of the 3mo period,
    so we compute: ((1 + end/100) / (1 + start/100) - 1) * 100.
    'start' is the last date that is >=8 calendar days before the last date.
    """
    if not series_3mo:
        return None
    dates = sorted(series_3mo.keys())
    if len(dates) < 3:
        return None
    last_dt = datetime.strptime(dates[-1], "%Y-%m-%d")
    cutoff  = (last_dt - timedelta(days=8)).strftime("%Y-%m-%d")
    before  = [d for d in dates if d <= cutoff]
    if not before:
        return None
    end_pct   = series_3mo[dates[-1]]
    start_pct = series_3mo[before[-1]]
    return round(((1 + end_pct / 100) / (1 + start_pct / 100) - 1) * 100, 2)

def ytd_perf_from_series(series_ytd):
    if not series_ytd:
        return None
    dates = sorted(series_ytd.keys())
    return round(series_ytd[dates[-1]], 2) if dates else None

# ── Compute metrics ──────────────────────────────────────────────────────────
total_value = sum(pos_value_eur(p) for p in positions)

port_weekly = weekly_perf_from_3mo(chart_data.get("portfolio", {}).get("3mo", {}))
port_ytd    = ytd_perf_from_series(chart_data.get("portfolio", {}).get("ytd", {}))

BENCH_LABELS = {"SP500": "S&P 500", "NASDAQ": "NASDAQ", "DAX": "DAX", "FTSE100": "FTSE 100"}
benchmarks = {}
for idx_name in BENCH_LABELS:
    idx_data = chart_data.get("indexes", {}).get(idx_name, {})
    benchmarks[idx_name] = {
        "weekly": weekly_perf_from_3mo(idx_data.get("3mo", {})),
        "ytd":    ytd_perf_from_series(idx_data.get("ytd", {})),
    }

# Per-stock metrics
stock_perfs = []
for p in positions:
    ticker   = p["ticker"]
    val_eur  = pos_value_eur(p)
    s3mo     = chart_data.get("stocks", {}).get(ticker, {}).get("3mo", {})
    sytd     = chart_data.get("stocks", {}).get(ticker, {}).get("ytd", {})
    stock_perfs.append({
        "ticker":  ticker,
        "name":    p["name"],
        "flag":    p["flag"],
        "sector":  p["sector"],
        "weekly":  weekly_perf_from_3mo(s3mo),
        "ytd":     ytd_perf_from_series(sytd),
        "ppl":     p.get("ppl", 0),
        "val_eur": val_eur,
        "weight":  round(val_eur / total_value * 100, 1) if total_value else 0,
    })

stock_perfs.sort(key=lambda x: x["val_eur"], reverse=True)

with_weekly = [s for s in stock_perfs if s["weekly"] is not None]
gainers = sorted(with_weekly, key=lambda x: -x["weekly"])[:5]
losers  = sorted(with_weekly, key=lambda x:  x["weekly"])[:5]

# Sector aggregation
sector_data = {}
for s in stock_perfs:
    sec = s["sector"]
    if sec not in sector_data:
        sector_data[sec] = {"val": 0, "w_perf": 0, "w_sum": 0}
    sector_data[sec]["val"] += s["val_eur"]
    if s["weekly"] is not None:
        sector_data[sec]["w_perf"] += s["weekly"] * s["val_eur"]
        sector_data[sec]["w_sum"]  += s["val_eur"]

sector_rows_data = []
for sec, d in sorted(sector_data.items(), key=lambda x: -x[1]["val"]):
    weekly = round(d["w_perf"] / d["w_sum"], 2) if d["w_sum"] else None
    sector_rows_data.append({
        "sector": sec,
        "val":    d["val"],
        "weight": round(d["val"] / total_value * 100, 1) if total_value else 0,
        "weekly": weekly,
    })

# ── Format helpers ────────────────────────────────────────────────────────────
def fmt_pct(v, plus=True):
    if v is None:
        return '<span class="na">—</span>'
    cls  = "pos" if v > 0 else ("neg" if v < 0 else "neu")
    sign = "+" if v > 0 and plus else ""
    return f'<span class="{cls}">{sign}{v:.2f}%</span>'

def fmt_eur(v):
    return f"€{v:,.0f}"

# ── Week label ────────────────────────────────────────────────────────────────
today          = generated_at.date()
week_start     = today - timedelta(days=today.weekday())
week_end       = week_start + timedelta(days=4)
week_label     = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"

# ── HTML fragments ────────────────────────────────────────────────────────────
def bench_rows_html():
    rows = [f"""<tr class="portfolio-row">
          <td><strong>Carteira</strong></td>
          <td>{fmt_pct(port_weekly)}</td>
          <td>{fmt_pct(port_ytd)}</td>
        </tr>"""]
    for k, label in BENCH_LABELS.items():
        b = benchmarks[k]
        rows.append(f"""<tr>
          <td>{label}</td>
          <td>{fmt_pct(b['weekly'])}</td>
          <td>{fmt_pct(b['ytd'])}</td>
        </tr>""")
    return "\n".join(rows)

def mover_cards_html(stocks, cls):
    cards = []
    for s in stocks:
        sign = "+" if s["weekly"] > 0 else ""
        pcls = "pos" if s["weekly"] > 0 else "neg"
        cards.append(f"""<div class="mover-card {cls}">
            <div class="mover-flag">{s['flag']}</div>
            <div class="mover-info">
              <div class="mover-ticker">{s['ticker']}</div>
              <div class="mover-name">{s['name']}</div>
            </div>
            <div class="mover-perf {pcls}">{sign}{s['weekly']:.2f}%</div>
          </div>""")
    return "\n".join(cards)

def holdings_rows_html():
    rows = []
    for s in stock_perfs:
        rows.append(f"""<tr>
          <td>{s['flag']} <strong>{s['ticker']}</strong></td>
          <td>{s['name']}</td>
          <td><span class="sector-tag">{s['sector']}</span></td>
          <td class="num">{fmt_eur(s['val_eur'])}</td>
          <td class="num">{s['weight']:.1f}%</td>
          <td class="num">{fmt_pct(s['weekly'])}</td>
          <td class="num">{fmt_pct(s['ppl'])}</td>
        </tr>""")
    return "\n".join(rows)

def sector_table_html():
    rows = []
    for s in sector_rows_data:
        rows.append(f"""<tr>
          <td>{s['sector']}</td>
          <td class="num">{fmt_eur(s['val'])}</td>
          <td class="num">{s['weight']:.1f}%</td>
          <td class="num">{fmt_pct(s['weekly'])}</td>
        </tr>""")
    return "\n".join(rows)

# ── Full HTML ────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Weekly Report — {week_label}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0d1117; color: #c9d1d9; line-height: 1.6; font-size: 15px;
    }}
    .container {{ max-width: 920px; margin: 0 auto; padding: 40px 20px 60px; }}

    /* Header */
    .header {{ text-align: center; margin-bottom: 44px; }}
    .header h1 {{ font-size: 2rem; font-weight: 800; color: #f0f6fc; letter-spacing: -0.5px; }}
    .header .subtitle {{ color: #8b949e; margin-top: 4px; font-size: 0.9rem; }}
    .header .week-badge {{
      display: inline-block; margin-top: 14px;
      background: #161b22; border: 1px solid #30363d;
      border-radius: 20px; padding: 5px 20px;
      font-size: 0.9rem; color: #8b949e;
    }}

    /* Section */
    section {{ margin-bottom: 40px; }}
    .section-title {{
      font-size: 0.78rem; font-weight: 600; color: #8b949e;
      text-transform: uppercase; letter-spacing: 0.1em;
      margin-bottom: 14px; padding-bottom: 8px;
      border-bottom: 1px solid #21262d;
    }}

    /* Summary cards */
    .summary-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
    .summary-card {{
      background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 20px;
    }}
    .summary-card .label {{
      font-size: 0.75rem; color: #8b949e; text-transform: uppercase;
      letter-spacing: 0.07em; margin-bottom: 8px;
    }}
    .summary-card .value {{ font-size: 1.6rem; font-weight: 700; color: #f0f6fc; }}
    .summary-card .sub {{ font-size: 0.8rem; color: #6e7681; margin-top: 4px; }}

    /* Tables */
    .table-wrap {{ border: 1px solid #30363d; border-radius: 10px; overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; background: #161b22; }}
    th {{
      text-align: left; padding: 10px 14px;
      font-size: 0.75rem; color: #8b949e;
      text-transform: uppercase; letter-spacing: 0.06em;
      background: #0d1117; border-bottom: 1px solid #21262d;
    }}
    td {{ padding: 10px 14px; font-size: 0.88rem; border-bottom: 1px solid #21262d; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #1c2128; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .portfolio-row td {{ font-weight: 700; background: #1c2128; }}
    .sector-tag {{
      display: inline-block; font-size: 0.75rem; padding: 2px 8px;
      background: #21262d; border-radius: 4px; color: #8b949e;
    }}

    /* Movers */
    .movers-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .movers-col .col-label {{
      font-size: 0.8rem; font-weight: 600; color: #8b949e;
      text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 10px;
    }}
    .mover-cards {{ display: flex; flex-direction: column; gap: 8px; }}
    .mover-card {{
      display: flex; align-items: center; gap: 12px;
      background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px 14px;
    }}
    .mover-card.gainer {{ border-left: 3px solid #3fb950; }}
    .mover-card.loser  {{ border-left: 3px solid #f85149; }}
    .mover-flag {{ font-size: 1.4rem; flex-shrink: 0; }}
    .mover-info {{ flex: 1; min-width: 0; }}
    .mover-ticker {{ font-weight: 700; font-size: 0.9rem; color: #f0f6fc; }}
    .mover-name {{ font-size: 0.78rem; color: #8b949e; white-space: nowrap;
                  overflow: hidden; text-overflow: ellipsis; }}
    .mover-perf {{ font-weight: 700; font-size: 1rem; flex-shrink: 0; }}

    /* Colours */
    .pos {{ color: #3fb950; }}
    .neg {{ color: #f85149; }}
    .neu {{ color: #8b949e; }}
    .na  {{ color: #30363d; }}

    /* Footer */
    .footer {{ margin-top: 48px; text-align: center; font-size: 0.78rem; color: #6e7681; }}
    .footer a {{ color: #58a6ff; text-decoration: none; }}

    @media (max-width: 600px) {{
      .summary-grid {{ grid-template-columns: 1fr 1fr; }}
      .movers-grid  {{ grid-template-columns: 1fr; }}
      th, td        {{ padding: 8px 10px; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <header class="header">
    <h1>Weekly Market Report</h1>
    <div class="subtitle">Independência Financeira · Portfolio Overview</div>
    <div class="week-badge">📅 {week_label}</div>
  </header>

  <!-- Portfolio snapshot -->
  <section>
    <div class="section-title">Snapshot da Carteira</div>
    <div class="summary-grid">
      <div class="summary-card">
        <div class="label">Valor Total</div>
        <div class="value">{fmt_eur(total_value)}</div>
        <div class="sub">{len(positions)} posições</div>
      </div>
      <div class="summary-card">
        <div class="label">Performance Semanal</div>
        <div class="value">{fmt_pct(port_weekly)}</div>
        <div class="sub">vs semana anterior</div>
      </div>
      <div class="summary-card">
        <div class="label">Performance YTD</div>
        <div class="value">{fmt_pct(port_ytd)}</div>
        <div class="sub">desde 1 Jan {today.year}</div>
      </div>
    </div>
  </section>

  <!-- Benchmarks -->
  <section>
    <div class="section-title">Carteira vs Índices</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Índice</th><th>Semanal</th><th>YTD</th></tr></thead>
        <tbody>{bench_rows_html()}</tbody>
      </table>
    </div>
  </section>

  <!-- Movers -->
  <section>
    <div class="section-title">Maiores Movimentos da Semana</div>
    <div class="movers-grid">
      <div class="movers-col">
        <div class="col-label">🟢 Top Gainers</div>
        <div class="mover-cards">{mover_cards_html(gainers, 'gainer')}</div>
      </div>
      <div class="movers-col">
        <div class="col-label">🔴 Top Losers</div>
        <div class="mover-cards">{mover_cards_html(losers, 'loser')}</div>
      </div>
    </div>
  </section>

  <!-- All holdings -->
  <section>
    <div class="section-title">Todas as Posições</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Nome</th>
            <th>Sector</th>
            <th class="num">Valor</th>
            <th class="num">Peso</th>
            <th class="num">Semanal</th>
            <th class="num">P&amp;L Total</th>
          </tr>
        </thead>
        <tbody>{holdings_rows_html()}</tbody>
      </table>
    </div>
  </section>

  <!-- Sectors -->
  <section>
    <div class="section-title">Performance por Sector</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Sector</th><th class="num">Valor</th><th class="num">Peso</th><th class="num">Semanal</th></tr>
        </thead>
        <tbody>{sector_table_html()}</tbody>
      </table>
    </div>
  </section>

  <div class="footer">
    Gerado em {generated_at.strftime('%Y-%m-%d %H:%M UTC')} ·
    Dados via <a href="https://www.trading212.com">Trading212</a> &amp; Yahoo Finance
  </div>

</div>
</body>
</html>"""

with open("weekly_report.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Done — weekly_report.html ({len(html):,} bytes)")
