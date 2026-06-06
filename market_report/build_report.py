"""
build_report.py – Generate the weekly HTML market report.

Reads:
  data/mr_news.json
  data/mr_discord.json
  data/mr_market.json
  data/mr_earnings.json

Writes:
  reports/market-report-{YYYY-MM-DD}.html
  reports/index.html   (archive list)
"""

import glob
import json
import os
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_DIR    = "data"
REPORTS_DIR = "reports"


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_json(path: str, default):
    if not os.path.exists(path):
        print(f"  [INFO] {path} not found – using default")
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"  [WARN] Could not load {path}: {exc}")
        return default


# ── Formatters ────────────────────────────────────────────────────────────────

def fmt_number(val) -> str:
    """Format large numbers as $XX.XB / $XX.XM / $XX.XK."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    abs_v = abs(v)
    sign  = "-" if v < 0 else ""
    if abs_v >= 1e12:
        return f"{sign}${abs_v / 1e12:.1f}T"
    if abs_v >= 1e9:
        return f"{sign}${abs_v / 1e9:.1f}B"
    if abs_v >= 1e6:
        return f"{sign}${abs_v / 1e6:.1f}M"
    if abs_v >= 1e3:
        return f"{sign}${abs_v / 1e3:.1f}K"
    return f"{sign}${v:.2f}"


def fmt_pct(val, show_sign: bool = True) -> str:
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    sign = "+" if (show_sign and v >= 0) else ""
    return f"{sign}{v:.2f}%"


def pct_color(val) -> str:
    """Return CSS color class: 'pos', 'neg', or 'neutral'."""
    if val is None:
        return "neutral"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "neutral"
    if v > 0:
        return "pos"
    if v < 0:
        return "neg"
    return "neutral"


def source_badge(source: str) -> str:
    colors = {
        "WSJ":       "#0080FF",
        "FT":        "#E86850",
        "Bloomberg": "#F57C00",
        "Economist": "#C0392B",
        "Discord":   "#5865F2",
    }
    color = colors.get(source, "#555E6E")
    return (
        f'<span class="source-badge" style="background:{color}">'
        f'{source}</span>'
    )


def news_card(article: dict) -> str:
    title   = article.get("title",   "")
    summary = article.get("summary", "")
    link    = article.get("link",    "#")
    source  = article.get("source",  "")
    date    = article.get("date",    "")

    # Escape HTML entities in text
    def esc(s):
        return (s
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    badge = source_badge(source)
    link_attr = f'href="{esc(link)}" target="_blank" rel="noopener"' if link and link != "#" else 'href="#"'

    return f"""
    <div class="card news-card">
      <div class="card-meta">
        {badge}
        <span class="card-date">{esc(date)}</span>
      </div>
      <h3 class="card-title">{esc(title)}</h3>
      <p class="card-summary">{esc(summary)}</p>
      <a class="card-link" {link_attr}>Ler mais →</a>
    </div>"""


def discord_card(msg: dict) -> str:
    content = msg.get("content", "")
    author  = msg.get("author",  "")
    date    = msg.get("date",    "")
    embeds  = msg.get("embeds",  [])

    def esc(s):
        return (s
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    embeds_html = ""
    for emb in embeds:
        emb_title = esc(emb.get("title", ""))
        emb_url   = esc(emb.get("url", ""))
        emb_desc  = esc(emb.get("description", "")[:200])
        if emb_title or emb_desc:
            link_start = f'<a href="{emb_url}" target="_blank" rel="noopener">' if emb_url else ""
            link_end   = "</a>" if emb_url else ""
            embeds_html += f"""
        <div class="discord-embed">
          {link_start}<strong>{emb_title}</strong>{link_end}
          {"<br>" + emb_desc if emb_desc else ""}
        </div>"""

    return f"""
    <div class="card discord-card">
      <div class="card-meta">
        {source_badge("Discord")}
        <span class="card-author">{esc(author)}</span>
        <span class="card-date">{esc(date)}</span>
      </div>
      {"<p class='card-summary'>" + esc(content[:500]) + "</p>" if content.strip() else ""}
      {embeds_html}
    </div>"""


def render_index_table(indices: dict) -> str:
    if not indices:
        return '<p class="placeholder">Dados de índices não disponíveis.</p>'

    rows = ""
    for name, data in indices.items():
        close   = data.get("close")
        w_pct   = data.get("weekly_pct")
        cls     = pct_color(w_pct)
        rows += f"""
        <tr>
          <td>{name}</td>
          <td class="number">${close:,.2f}</td>
          <td class="number {cls}">{fmt_pct(w_pct)}</td>
        </tr>"""

    return f"""
    <table class="data-table">
      <thead><tr><th>Índice</th><th>Cotação</th><th>Var. Semana</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def render_mag7_table(mag7: list) -> str:
    if not mag7:
        return '<p class="placeholder">Dados MAG-7 não disponíveis.</p>'

    rows = ""
    for item in mag7:
        ticker   = item.get("ticker", "")
        name     = item.get("name", "")
        close    = item.get("close")
        w_pct    = item.get("weekly_pct")
        ytd_pct  = item.get("ytd_pct")
        w_cls    = pct_color(w_pct)
        ytd_cls  = pct_color(ytd_pct)
        rows += f"""
        <tr>
          <td><span class="ticker-badge">{ticker}</span> {name}</td>
          <td class="number">${close:,.2f}</td>
          <td class="number {w_cls}">{fmt_pct(w_pct)}</td>
          <td class="number {ytd_cls}">{fmt_pct(ytd_pct)}</td>
        </tr>"""

    return f"""
    <table class="data-table">
      <thead>
        <tr>
          <th>Empresa</th><th>Cotação</th>
          <th>Var. Semana</th><th>Var. YTD</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def render_movers_table(movers: list, title: str) -> str:
    if not movers:
        return f'<p class="placeholder">{title}: dados não disponíveis.</p>'

    rows = ""
    for item in movers:
        ticker = item.get("ticker", "")
        close  = item.get("close")
        w_pct  = item.get("weekly_pct")
        cls    = pct_color(w_pct)
        rows += f"""
        <tr>
          <td><span class="ticker-badge">{ticker}</span></td>
          <td class="number">${close:,.2f}</td>
          <td class="number {cls}">{fmt_pct(w_pct)}</td>
        </tr>"""

    return f"""
    <h4 class="subsection-title">{title}</h4>
    <table class="data-table">
      <thead><tr><th>Ticker</th><th>Cotação</th><th>Var. Semana</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def render_52w_lows_table(lows: list) -> str:
    if not lows:
        return '<p class="placeholder">Nenhuma ação perto do mínimo de 52 semanas.</p>'

    rows = ""
    for item in lows:
        ticker       = item.get("ticker", "")
        close        = item.get("close")
        low52        = item.get("52w_low")
        high52       = item.get("52w_high")
        pct_from_low = item.get("pct_from_low")
        rows += f"""
        <tr>
          <td><span class="ticker-badge">{ticker}</span></td>
          <td class="number">${close:,.2f}</td>
          <td class="number">${low52:,.2f}</td>
          <td class="number">${high52:,.2f}</td>
          <td class="number neg">{fmt_pct(pct_from_low)}</td>
        </tr>"""

    return f"""
    <h4 class="subsection-title">Perto do Mínimo de 52 Semanas</h4>
    <table class="data-table">
      <thead>
        <tr>
          <th>Ticker</th><th>Cotação</th>
          <th>Mín. 52s</th><th>Máx. 52s</th><th>% do Mínimo</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def render_earnings_card(company: dict) -> str:
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    ticker    = company.get("ticker", "")
    name      = company.get("name", ticker)
    fy        = company.get("fiscal_year_end", "")

    def metric_row(label: str, metric: dict | None, is_currency: bool = True) -> str:
        if not metric:
            return ""
        val  = metric.get("value")
        yoy  = metric.get("yoy_pct")
        cls  = pct_color(yoy)
        formatted = fmt_number(val) if is_currency else fmt_pct(val, show_sign=False)
        if label == "EPS":
            formatted = f"${val:.2f}" if val is not None else "N/A"
        return f"""
          <tr>
            <td>{label}</td>
            <td class="number">{formatted}</td>
            <td class="number {cls}">{fmt_pct(yoy)}</td>
          </tr>"""

    rows  = metric_row("Revenue",       company.get("revenue"))
    rows += metric_row("Net Income",    company.get("net_income"))
    rows += metric_row("EPS",           company.get("eps_basic"), is_currency=False)
    rows += metric_row("EBIT",          company.get("operating_income"))
    rows += metric_row("Total Assets",  company.get("total_assets"))

    if not rows.strip():
        return ""

    return f"""
    <div class="card earnings-card">
      <div class="card-meta">
        <span class="ticker-badge large">{esc(ticker)}</span>
        <span class="fiscal-year">FY {esc(fy)}</span>
      </div>
      <h3 class="card-title">{esc(name)}</h3>
      <table class="earnings-table">
        <thead><tr><th>Métrica</th><th>Valor</th><th>Var. YoY</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


# ── HTML template ─────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg:      #060A12;
  --bg2:     #0D1117;
  --bg3:     #161B22;
  --border:  #21262D;
  --text:    #E6EDF3;
  --text2:   #8B949E;
  --accent:  #3FB950;
  --pos:     #3FB950;
  --neg:     #F85149;
  --link:    #58A6FF;
  --radius:  8px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { scroll-behavior: smooth; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  font-size: 15px;
}

/* ── Nav ─────────────────────────────────────────────────────────────────── */
.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(6,10,18,0.95);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 0;
  height: 56px;
}

.nav-brand {
  font-weight: 700;
  font-size: 16px;
  color: var(--accent);
  text-decoration: none;
  margin-right: 32px;
  white-space: nowrap;
}

.nav-links {
  display: flex;
  gap: 4px;
  flex: 1;
  overflow-x: auto;
}

.nav-links a {
  color: var(--text2);
  text-decoration: none;
  padding: 6px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  white-space: nowrap;
  transition: color .15s, background .15s;
}

.nav-links a:hover {
  color: var(--text);
  background: var(--bg3);
}

.nav-date {
  font-size: 12px;
  color: var(--text2);
  margin-left: auto;
  white-space: nowrap;
}

/* ── Hero ────────────────────────────────────────────────────────────────── */
.hero {
  background: linear-gradient(135deg, #0D1117 0%, #060A12 60%);
  border-bottom: 1px solid var(--border);
  padding: 48px 24px 40px;
  text-align: center;
}

.hero-eyebrow {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 12px;
}

.hero h1 {
  font-size: clamp(24px, 4vw, 40px);
  font-weight: 800;
  letter-spacing: -.02em;
  margin-bottom: 8px;
}

.hero-sub {
  color: var(--text2);
  font-size: 14px;
}

/* ── Layout ──────────────────────────────────────────────────────────────── */
main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px 80px;
}

.section {
  margin-bottom: 64px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.section-number {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg);
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.section-header h2 {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -.01em;
}

/* ── Card grid ───────────────────────────────────────────────────────────── */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.card {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color .2s;
}

.card:hover {
  border-color: #444D56;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.source-badge {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: #fff;
  padding: 2px 8px;
  border-radius: 999px;
}

.card-date,
.card-author {
  font-size: 11px;
  color: var(--text2);
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--text);
}

.card-summary {
  font-size: 13px;
  color: var(--text2);
  flex: 1;
}

.card-link {
  font-size: 12px;
  color: var(--link);
  text-decoration: none;
  margin-top: auto;
  align-self: flex-start;
}
.card-link:hover { text-decoration: underline; }

/* Discord embed */
.discord-embed {
  background: var(--bg3);
  border-left: 3px solid #5865F2;
  padding: 8px 12px;
  border-radius: 0 4px 4px 0;
  font-size: 12px;
  color: var(--text2);
}
.discord-embed a { color: var(--link); text-decoration: none; }
.discord-embed a:hover { text-decoration: underline; }

/* ── Tables ──────────────────────────────────────────────────────────────── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-bottom: 24px;
}

.data-table th {
  text-align: left;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text2);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .05em;
  text-transform: uppercase;
  background: var(--bg2);
}

.data-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}

.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(255,255,255,.03); }

.data-table th:not(:first-child),
.data-table td.number {
  text-align: right;
}

/* ── Earnings ────────────────────────────────────────────────────────────── */
.earnings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.earnings-card .card-title {
  font-size: 15px;
  font-weight: 700;
}

.earnings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin-top: 8px;
}

.earnings-table th {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text2);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .05em;
  text-transform: uppercase;
}

.earnings-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}

.earnings-table td:not(:first-child) { text-align: right; }
.earnings-table tr:last-child td { border-bottom: none; }

/* ── Badges ──────────────────────────────────────────────────────────────── */
.ticker-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  font-family: monospace;
  letter-spacing: .04em;
  background: var(--bg3);
  border: 1px solid var(--border);
  color: var(--accent);
  padding: 2px 7px;
  border-radius: 4px;
}

.ticker-badge.large {
  font-size: 13px;
  padding: 4px 10px;
}

.fiscal-year {
  font-size: 11px;
  color: var(--text2);
}

/* ── Color classes ───────────────────────────────────────────────────────── */
.pos { color: var(--pos); }
.neg { color: var(--neg); }
.neutral { color: var(--text2); }

/* ── Subsection ──────────────────────────────────────────────────────────── */
.subsection {
  margin-bottom: 32px;
}

.subsection-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text2);
  text-transform: uppercase;
  letter-spacing: .06em;
  margin-bottom: 12px;
  margin-top: 24px;
}

/* ── Placeholder ─────────────────────────────────────────────────────────── */
.placeholder {
  color: var(--text2);
  font-style: italic;
  padding: 16px 0;
}

/* ── Footer ──────────────────────────────────────────────────────────────── */
footer {
  border-top: 1px solid var(--border);
  padding: 24px;
  text-align: center;
  font-size: 12px;
  color: var(--text2);
  line-height: 1.8;
}

footer a { color: var(--link); text-decoration: none; }
footer a:hover { text-decoration: underline; }

/* ── Responsive ──────────────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .nav { padding: 0 16px; }
  main { padding: 24px 16px 60px; }
  .hero { padding: 32px 16px; }
  .card-grid { grid-template-columns: 1fr; }
  .earnings-grid { grid-template-columns: 1fr; }
}
"""


def build_html(
    report_date: str,
    news: dict,
    discord_msgs: list,
    market: dict,
    earnings: list,
) -> str:
    today_display = datetime.strptime(report_date, "%Y-%m-%d").strftime("%d %B %Y")
    generated_at  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Section 1: Macro ─────────────────────────────────────────────────────
    macro_articles = news.get("macro", [])
    macro_cards = "".join(news_card(a) for a in macro_articles)
    if not macro_cards:
        macro_cards = '<p class="placeholder">Sem artigos macroeconómicos esta semana.</p>'

    discord_section = ""
    if discord_msgs:
        discord_cards = "".join(discord_card(m) for m in discord_msgs)
        discord_section = f"""
      <div class="subsection">
        <h4 class="subsection-title">AS Club — #as-news</h4>
        <div class="card-grid">
          {discord_cards}
        </div>
      </div>"""

    # ── Section 2: Earnings ──────────────────────────────────────────────────
    earnings_cards = "".join(render_earnings_card(c) for c in earnings if render_earnings_card(c))
    if not earnings_cards:
        earnings_section_body = '<p class="placeholder">Dados de resultados não disponíveis para esta semana.</p>'
    else:
        earnings_section_body = f'<div class="earnings-grid">{earnings_cards}</div>'

    # ── Section 3: Price Swings ───────────────────────────────────────────────
    indices_table = render_index_table(market.get("indices", {}))
    mag7_table    = render_mag7_table(market.get("mag7", []))
    gainers_table = render_movers_table(market.get("top_gainers", []), "Top 10 Gainers — S&amp;P 500")
    losers_table  = render_movers_table(market.get("top_losers",  []), "Top 10 Losers — S&amp;P 500")
    lows_table    = render_52w_lows_table(market.get("near_52w_low", []))

    # ── Section 4: Business ──────────────────────────────────────────────────
    biz_articles = news.get("business", [])
    biz_cards = "".join(news_card(a) for a in biz_articles)
    if not biz_cards:
        biz_cards = '<p class="placeholder">Sem notícias de negócios esta semana.</p>'

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Market Report — {report_date}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>

<!-- ── Navigation ── -->
<nav class="nav">
  <a class="nav-brand" href="index.html">📊 Market Reports</a>
  <div class="nav-links">
    <a href="#macro">Macro</a>
    <a href="#earnings">Earnings</a>
    <a href="#swings">Price Swings</a>
    <a href="#business">Business</a>
  </div>
  <span class="nav-date">{today_display}</span>
</nav>

<!-- ── Hero ── -->
<div class="hero">
  <p class="hero-eyebrow">Relatório Semanal de Mercado</p>
  <h1>Market Report — {today_display}</h1>
  <p class="hero-sub">Resumo da semana: macro, resultados, movimentos de preço e novidades empresariais</p>
</div>

<main>

  <!-- ────────────────────────────────────────────────────────────────────── -->
  <!-- 1. MACRO CONTEXT                                                       -->
  <!-- ────────────────────────────────────────────────────────────────────── -->
  <section id="macro" class="section">
    <div class="section-header">
      <div class="section-number">1</div>
      <h2>Contexto Macroeconómico</h2>
    </div>

    <div class="card-grid">
      {macro_cards}
    </div>
    {discord_section}
  </section>

  <!-- ────────────────────────────────────────────────────────────────────── -->
  <!-- 2. EARNINGS REPORTS                                                    -->
  <!-- ────────────────────────────────────────────────────────────────────── -->
  <section id="earnings" class="section">
    <div class="section-header">
      <div class="section-number">2</div>
      <h2>Earnings Reports</h2>
    </div>
    {earnings_section_body}
  </section>

  <!-- ────────────────────────────────────────────────────────────────────── -->
  <!-- 3. PRICE SWINGS                                                        -->
  <!-- ────────────────────────────────────────────────────────────────────── -->
  <section id="swings" class="section">
    <div class="section-header">
      <div class="section-number">3</div>
      <h2>Price Swings</h2>
    </div>

    <div class="subsection">
      <h4 class="subsection-title">Índices — Variação Semanal</h4>
      {indices_table}
    </div>

    <div class="subsection">
      <h4 class="subsection-title">MAG-7 — Variação Semanal &amp; YTD</h4>
      {mag7_table}
    </div>

    <div class="subsection">
      {gainers_table}
    </div>

    <div class="subsection">
      {losers_table}
    </div>

    <div class="subsection">
      {lows_table}
    </div>
  </section>

  <!-- ────────────────────────────────────────────────────────────────────── -->
  <!-- 4. BUSINESS UPDATE                                                     -->
  <!-- ────────────────────────────────────────────────────────────────────── -->
  <section id="business" class="section">
    <div class="section-header">
      <div class="section-number">4</div>
      <h2>Business Update</h2>
    </div>

    <div class="card-grid">
      {biz_cards}
    </div>
  </section>

</main>

<footer>
  <p>Gerado a {generated_at}</p>
  <p>
    Fontes: WSJ · FT · Bloomberg · The Economist · Discord · Yahoo Finance · SEC EDGAR
  </p>
  <p>
    <a href="index.html">← Arquivo de Relatórios</a>
  </p>
</footer>

</body>
</html>"""


# ── Archive index ─────────────────────────────────────────────────────────────

ARCHIVE_CSS = """
:root {
  --bg:     #060A12;
  --bg2:    #0D1117;
  --bg3:    #161B22;
  --border: #21262D;
  --text:   #E6EDF3;
  --text2:  #8B949E;
  --accent: #3FB950;
  --link:   #58A6FF;
  --radius: 8px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  font-size: 15px;
}
header {
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  padding: 32px 24px;
  text-align: center;
}
header h1 {
  font-size: 28px;
  font-weight: 800;
  color: var(--accent);
  margin-bottom: 6px;
}
header p { color: var(--text2); font-size: 14px; }
main { max-width: 800px; margin: 40px auto; padding: 0 24px 80px; }
h2 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text2);
  text-transform: uppercase;
  letter-spacing: .06em;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
th {
  text-align: left;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text2);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .05em;
  text-transform: uppercase;
  background: var(--bg2);
}
td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,.03); }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
footer {
  border-top: 1px solid var(--border);
  padding: 20px 24px;
  text-align: center;
  font-size: 12px;
  color: var(--text2);
}
"""


def build_archive_index(report_date: str, reports_dir: str) -> str:
    """Scan reports_dir for all market-report-*.html files and build the archive."""
    pattern = os.path.join(reports_dir, "market-report-*.html")
    files = sorted(glob.glob(pattern), reverse=True)

    rows = ""
    for filepath in files:
        filename = os.path.basename(filepath)
        # Extract date from filename: market-report-YYYY-MM-DD.html
        date_part = filename[len("market-report"):-len(".html")].lstrip("-")
        try:
            dt = datetime.strptime(date_part, "%Y-%m-%d")
            display_date = dt.strftime("%d %B %Y")
        except ValueError:
            display_date = date_part
        is_latest = "✦ Mais recente" if date_part == report_date else ""
        rows += f"""
        <tr>
          <td>{display_date} <small style="color:#8B949E">{is_latest}</small></td>
          <td><a href="{filename}">Ver relatório →</a></td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="2" style="color:#8B949E;font-style:italic">Sem relatórios ainda.</td></tr>'

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Market Reports Archive</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{ARCHIVE_CSS}</style>
</head>
<body>
<header>
  <h1>📊 Market Reports</h1>
  <p>Arquivo de relatórios semanais de mercado</p>
</header>
<main>
  <h2>Todos os relatórios</h2>
  <table>
    <thead>
      <tr><th>Data</th><th>Link</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</main>
<footer>Atualizado a {generated_at}</footer>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # Load all data with safe defaults
    news         = load_json(os.path.join(DATA_DIR, "mr_news.json"),    {"macro": [], "earnings": [], "business": []})
    discord_msgs = load_json(os.path.join(DATA_DIR, "mr_discord.json"), [])
    market       = load_json(os.path.join(DATA_DIR, "mr_market.json"),  {})
    earnings     = load_json(os.path.join(DATA_DIR, "mr_earnings.json"), [])

    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_file    = os.path.join(REPORTS_DIR, f"market-report-{report_date}.html")
    index_file  = os.path.join(REPORTS_DIR, "index.html")

    print(f"Building report for {report_date}...")
    print(f"  Macro articles:   {len(news.get('macro', []))}")
    print(f"  Earnings articles:{len(news.get('earnings', []))}")
    print(f"  Business articles:{len(news.get('business', []))}")
    print(f"  Discord messages: {len(discord_msgs)}")
    print(f"  Earnings data:    {len(earnings)} companies")
    indices = market.get("indices", {})
    print(f"  Market indices:   {len(indices)}")

    html = build_html(report_date, news, discord_msgs, market, earnings)

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report written to {out_file}")

    # Build archive index AFTER writing the new report (so it appears in the list)
    archive_html = build_archive_index(report_date, REPORTS_DIR)
    with open(index_file, "w", encoding="utf-8") as f:
        f.write(archive_html)
    print(f"Archive index written to {index_file}")


if __name__ == "__main__":
    main()
