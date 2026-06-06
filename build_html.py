"""
Builds the final index.html by injecting fresh JSON data into the template.
Reads:  portfolio-template.html + data/*.json
Writes: index.html
"""
import json, re, os
from datetime import datetime

print("Building index.html...")

with open("portfolio-template.html", encoding="utf-8") as f:
    html = f.read()

with open("data/positions.json",   encoding="utf-8") as f: positions   = json.load(f)
with open("data/chart_data.json",  encoding="utf-8") as f: chart_data  = json.load(f)
with open("data/fundamentals.json",encoding="utf-8") as f: fundamentals= json.load(f)
with open("data/fx.json",          encoding="utf-8") as f: fx_rates    = json.load(f)

# Compact JSON (no extra whitespace)
positions_js    = json.dumps(positions,    separators=(',',':'), ensure_ascii=False)
chart_data_js   = json.dumps(chart_data,   separators=(',',':'))
fundamentals_js = json.dumps(fundamentals, separators=(',',':'))
fx_js           = json.dumps(fx_rates,     separators=(',',':'))

updated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

# Replace placeholders
html = html.replace("/*__POSITIONS__*/",    positions_js)
html = html.replace("/*__CHART_DATA__*/",   chart_data_js)
html = html.replace("/*__FUNDAMENTALS__*/", fundamentals_js)
html = html.replace("/*__FX_RATES__*/",     fx_js)
html = html.replace("__UPDATED__",          updated)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"Done! index.html written ({len(html)//1024}KB)")
print(f"  Positions: {len(positions)}")
print(f"  Portfolio days (1y): {len(chart_data.get('portfolio', {}).get('1y', {}))}")
print(f"  Updated: {updated}")
