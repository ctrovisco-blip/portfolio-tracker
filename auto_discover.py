"""
auto_discover.py — Auto-discovers new T212 positions not yet in t212_map.json / metadata.json.
Deve correr ANTES de fetch_positions.py no workflow.

Para cada ticker T212 desconhecido:
1. Chama a API de instrumentos do T212 → nome, moeda, exchange, ISIN
2. Deriva display ticker (shortName do T212)
3. Deriva símbolo Yahoo Finance (shortName + sufixo de exchange)
4. Valida com yfinance; obtém sector
5. Actualiza data/t212_map.json e metadata.json
"""
import json, os, time, base64, urllib.request

API_KEY    = os.environ.get("T212_API_KEY", "")
API_SECRET = os.environ.get("T212_SECRET_KEY", "")
BASIC      = base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
HEADERS    = {
    "Authorization": f"Basic {BASIC}",
    "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept":        "application/json",
}
BASE = "https://live.trading212.com"

def get_t212(path, retries=5):
    delays = [10, 30, 60, 120, 180]
    for attempt in range(retries):
        req = urllib.request.Request(BASE + path, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = delays[attempt]
                print(f"  Rate limit (429), aguardando {wait}s antes de retry {attempt + 1}/{retries - 1}...")
                time.sleep(wait)
            else:
                raise

# ── Carregar ficheiros existentes ─────────────────────────────────────────────
os.makedirs("data", exist_ok=True)

t212_map_path = "data/t212_map.json"
with open(t212_map_path, encoding="utf-8") as f:
    t212_map = json.load(f)

with open("metadata.json", encoding="utf-8") as f:
    metadata = json.load(f)

# ── Verificar se há tickers desconhecidos no portfolio actual ─────────────────
print("Verificando portfolio para novos tickers...")
try:
    portfolio = get_t212("/api/v0/equity/portfolio")
except Exception as e:
    print(f"  Erro ao obter portfolio: {e}")
    exit(0)

unknown = [p["ticker"] for p in portfolio if p["ticker"] not in t212_map]

if not unknown:
    print("  Nenhum ticker novo — nada a descobrir.")
    exit(0)

print(f"  {len(unknown)} ticker(s) novo(s) encontrado(s): {unknown}")

# ── Buscar lista de todos os instrumentos T212 ────────────────────────────────
print("A obter lista de instrumentos T212 (pode demorar alguns segundos)...")
try:
    instruments_raw = get_t212("/api/v0/equity/metadata/instruments")
    inst_map = {i["ticker"]: i for i in instruments_raw}
    print(f"  {len(inst_map)} instrumentos carregados")
except Exception as e:
    print(f"  Erro ao obter instrumentos: {e}")
    exit(0)

# ── Tabelas de mapeamento ─────────────────────────────────────────────────────

# Moeda T212 → símbolo display
CUR_MAP = {
    "EUR": "€", "USD": "$", "GBX": "p", "GBP": "p", "CAD": "C$",
}

# Exchange T212 id → (sufixo Yahoo Finance, nome display, emoji bandeira)
EXCH_MAP = {
    "XETA":   (".DE", "Xetra",            ""),   # bandeira via ISIN
    "XETR":   (".DE", "Xetra",            ""),
    "NYSE":   ("",    "NYSE",             "🇺🇸"),
    "NQUS":   ("",    "NASDAQ",           "🇺🇸"),
    "NASDAQ": ("",    "NASDAQ",           "🇺🇸"),
    "LSE":    (".L",  "LSE",              "🇬🇧"),
    "LSEX":   (".L",  "LSE",              "🇬🇧"),
    "LISB":   (".LS", "Euronext Lisboa",  "🇵🇹"),
    "AMSE":   (".AS", "Euronext AMS",     ""),   # bandeira via ISIN
    "XPAR":   (".PA", "Euronext Paris",   "🇫🇷"),
    "XMIL":   (".MI", "Milan",            "🇮🇹"),
    "TSX":    (".TO", "Toronto",          "🇨🇦"),
    "XTSE":   (".TO", "Toronto",          "🇨🇦"),
}

# Prefixo ISIN (país) → emoji bandeira
ISIN_FLAG = {
    "US": "🇺🇸", "GB": "🇬🇧", "PT": "🇵🇹", "DE": "🇩🇪", "FR": "🇫🇷",
    "NL": "🇳🇱", "IE": "🇮🇪", "CA": "🇨🇦", "IT": "🇮🇹", "ES": "🇪🇸",
    "CH": "🇨🇭", "SE": "🇸🇪", "DK": "🇩🇰", "NO": "🇳🇴", "FI": "🇫🇮",
    "BE": "🇧🇪", "AT": "🇦🇹", "JP": "🇯🇵", "KR": "🇰🇷", "AU": "🇦🇺",
}

# Sector yfinance → sector da carteira (PT)
SECTOR_MAP = {
    "Technology":               "Tech & AI",
    "Communication Services":   "Tech & AI",
    "Healthcare":               "Healthcare",
    "Consumer Staples":         "Consumer Staples",
    "Consumer Discretionary":   "Luxo & Automóvel",
    "Energy":                   "Energia",
    "Industrials":              "Defesa & Aeroespacial",
    "Real Estate":              "REIT",
    "Utilities":                "Energia",
    "Financial Services":       "Outro",
    "Basic Materials":          "Outro",
}

# ── yfinance disponível? ──────────────────────────────────────────────────────
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False
    print("  yfinance não disponível — sectores vão ser 'Outro'")

def validate_yf(sym):
    """Devolve True se o símbolo tem dados válidos no Yahoo Finance."""
    if not HAS_YF:
        return True
    try:
        info = yf.Ticker(sym).info
        return bool(info.get("regularMarketPrice") or
                    info.get("currentPrice") or
                    info.get("navPrice"))
    except:
        return False

def get_yf_info(sym):
    """Devolve (sector_yf, full_name) do Yahoo Finance."""
    if not HAS_YF:
        return None, None
    try:
        info = yf.Ticker(sym).info
        return info.get("sector"), info.get("longName") or info.get("shortName")
    except:
        return None, None

# ── Processar cada ticker desconhecido ────────────────────────────────────────
added = 0
for t212_ticker in unknown:
    print(f"\nA processar: {t212_ticker}")

    inst = inst_map.get(t212_ticker)
    if not inst:
        print(f"  Não encontrado na lista de instrumentos — a saltar")
        continue

    short_name    = inst.get("shortName", "").strip()
    full_name     = inst.get("name", short_name).strip()
    isin          = inst.get("isin", "")
    currency_code = inst.get("currencyCode", "USD")
    exchanges     = inst.get("exchanges", [])
    exch_id       = exchanges[0].get("id", "") if exchanges else ""
    inst_type     = inst.get("type", "STOCK")

    if not short_name:
        short_name = t212_ticker.replace("_EQ", "").replace("_", "")

    # Display ticker = shortName em maiúsculas
    display_ticker = short_name.upper().replace(" ", "-")

    # Moeda
    cur = CUR_MAP.get(currency_code, "$")

    # Exchange info
    exch_yf_suffix, exch_display, flag = EXCH_MAP.get(exch_id, ("", exch_id, ""))

    # Bandeira via ISIN se não determinada pela exchange
    if not flag and isin:
        flag = ISIN_FLAG.get(isin[:2], "🌍")

    # ── Símbolo Yahoo Finance ──────────────────────────────────────────────
    yf_sym = short_name + exch_yf_suffix

    # Para acções Xetra (suffixo .DE): Yahoo Finance tem dados limitados;
    # tentar primeiro sem sufixo (listagem US/principal)
    if exch_yf_suffix == ".DE":
        if validate_yf(short_name):
            yf_sym = short_name
            print(f"  Xetra: usando símbolo US '{short_name}' (Yahoo Finance tem melhor data)")
        elif validate_yf(yf_sym):
            print(f"  Xetra: usando '{yf_sym}'")
        else:
            print(f"  Atenção: não foi possível validar '{yf_sym}' — usando mesmo assim")
    else:
        if not validate_yf(yf_sym):
            # Tentar sem sufixo como fallback
            if exch_yf_suffix and validate_yf(short_name):
                yf_sym = short_name
            else:
                print(f"  Atenção: não foi possível validar '{yf_sym}' no Yahoo Finance")

    # ── Sector e nome completo via yfinance ───────────────────────────────
    yf_sector, yf_name = get_yf_info(yf_sym)
    if yf_name and len(yf_name) > len(full_name):
        full_name = yf_name  # usar nome mais completo do Yahoo

    if inst_type in ("ETF", "ETC"):
        sector = "ETF / ETC"
    else:
        sector = SECTOR_MAP.get(yf_sector, "Outro")

    # ── Actualizar mapas ──────────────────────────────────────────────────
    t212_map[t212_ticker] = display_ticker

    if display_ticker not in metadata:
        metadata[display_ticker] = {
            "name":     full_name,
            "sector":   sector,
            "flag":     flag,
            "exchange": exch_display,
            "cur":      cur,
            "yf":       yf_sym,
        }
        print(f"  ✓ ADICIONADO: {display_ticker} | {full_name} | yf={yf_sym} | sector={sector}")
    else:
        print(f"  Já existe em metadata.json: {display_ticker} — a manter")

    added += 1
    time.sleep(0.5)

# ── Guardar ficheiros actualizados ────────────────────────────────────────────
if added > 0:
    with open(t212_map_path, "w", encoding="utf-8") as f:
        json.dump(t212_map, f, ensure_ascii=False, indent=2)
    with open("metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"\n✓ {added} nova(s) posição(ões) adicionada(s) a t212_map.json e metadata.json")
else:
    print("\nNenhuma posição nova adicionada.")
