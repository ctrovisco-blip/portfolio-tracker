"""
Builds the final index.html by injecting fresh JSON data into the template.
Reads:  portfolio-template.html + data/*.json
Writes: index.html

Se algum ficheiro de dados estiver em falta, tenta usar a versão anterior de
index.html; caso não exista, aborta com erro claro.
"""
import json, os, sys
from datetime import datetime, timezone

print("Building index.html...")

# ── Template ──────────────────────────────────────────────────────────────────

with open("portfolio-template.html", encoding="utf-8") as f:
    html = f.read()

# ── Loader robusto ────────────────────────────────────────────────────────────

def load_json(path, description):
    """Carrega JSON; aborta se o ficheiro não existir."""
    if not os.path.exists(path):
        print(f"  AVISO: {path} nao encontrado — a build pode usar dados antigos.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {description}: OK ({os.path.getsize(path)//1024}KB)")
    return data

positions    = load_json("data/positions.json",    "Positions")
chart_data   = load_json("data/chart_data.json",   "Chart data")
fundamentals = load_json("data/fundamentals.json", "Fundamentals")
fx_rates     = load_json("data/fx.json",           "FX rates")

screener_data = {}
if os.path.exists("data/screener.json"):
    with open("data/screener.json", encoding="utf-8") as f:
        screener_data = json.load(f)
    print(f"  Screener data: OK ({len(screener_data)} tickers)")
else:
    print("  Screener data: not found, using {}")

# ── Timestamps por fonte ───────────────────────────────────────────────────────

def file_mtime(path):
    """Devolve a hora de modificação do ficheiro como string 'YYYY-MM-DD HH:MM UTC'."""
    if not os.path.exists(path):
        return "n/a"
    t = os.path.getmtime(path)
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

timestamps = {
    "positions":    file_mtime("data/positions.json"),
    "chart":        file_mtime("data/chart_data.json"),
    "fundamentals": file_mtime("data/fundamentals.json"),
    "fx":           file_mtime("data/fx.json"),
}

# ── Compact JSON ──────────────────────────────────────────────────────────────

positions_js    = json.dumps(positions,     separators=(',',':'), ensure_ascii=False)
chart_data_js   = json.dumps(chart_data,   separators=(',',':'))
fundamentals_js = json.dumps(fundamentals, separators=(',',':'))
fx_js           = json.dumps(fx_rates,     separators=(',',':'))
screener_js     = json.dumps(screener_data, separators=(',',':'), ensure_ascii=False)
timestamps_js   = json.dumps(timestamps,   separators=(',',':'))

updated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
build_ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")

# ── Escrever data/version.json (usado pelo tracker para detetar nova versão) ──
os.makedirs("data", exist_ok=True)
with open("data/version.json", "w", encoding="utf-8") as f:
    json.dump({"ts": build_ts, "updated": updated}, f)
print(f"  version.json: {build_ts}")

# ── Substituir placeholders ───────────────────────────────────────────────────

html = html.replace("/*__POSITIONS__*/",    positions_js)
html = html.replace("/*__CHART_DATA__*/",   chart_data_js)
html = html.replace("/*__FUNDAMENTALS__*/", fundamentals_js)
html = html.replace("/*__FX_RATES__*/",     fx_js)
html = html.replace("/*__SCREENER_DATA__*/", screener_js)
html = html.replace("/*__TIMESTAMPS__*/",   timestamps_js)
html = html.replace("/*__BUILD_TS__*/",     f'"{build_ts}"')
html = html.replace("__UPDATED__",          updated)

# ── Escrever index.html ───────────────────────────────────────────────────────

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nindex.html escrito ({len(html)//1024}KB)")
print(f"  Posicoes:           {len(positions)}")
print(f"  Portfolio dias 1y:  {len(chart_data.get('portfolio', {}).get('1y', {}))}")
print(f"  Fundamentais:       {len(fundamentals)}")
print(f"  FX rates:           {list(fx_rates.keys())}")
print(f"  Build timestamp:    {updated}")
print(f"\n  Timestamps dos dados:")
for k, v in timestamps.items():
    print(f"    {k:15s} -> {v}")
