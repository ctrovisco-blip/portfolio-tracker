"""
Histórico completo de transações da Trading 212 → data/transactions.json

Fontes, por ordem de preferência:
  1. Export CSV pela API (/api/v0/history/exports): o extrato oficial, com a
     retenção na fonte, os encargos, os juros e os depósitos. Pedido em blocos
     de 1 ano (limite da T212) desde o último evento já guardado.
  2. Fallback JSON (/equity/history/orders com `fill`, /dividends,
     /transactions): sem juros e com o bruto dos dividendos estimado.
  3. CSVs exportados à mão em data/statements/*.csv (somam-se sempre).

O ficheiro é cumulativo: os eventos novos juntam-se aos que já existem
(deduplicados por ID). Também guarda o saldo de caixa em data/account.json.

Env: T212_API_KEY, T212_SECRET_KEY · HISTORY_MODE=auto|csv|api (default auto)
"""
import base64
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analytics import ledger  # noqa: E402

API_KEY = os.environ.get("T212_API_KEY", "")
API_SECRET = os.environ.get("T212_SECRET_KEY", "")
MODE = os.environ.get("HISTORY_MODE", "auto")
BASE = "https://live.trading212.com"
HEADERS = {
    "Authorization": "Basic " + base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode(),
    "User-Agent": "Mozilla/5.0 (portfolio-tracker)",
    "Accept": "application/json",
}
TX_PATH = "data/transactions.json"


def request(path, method="GET", body=None, retries=5):
    delays = [10, 30, 60, 90, 120]
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        h = dict(HEADERS)
        if data:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                print(f"  429 em {path}, a aguardar {delays[attempt]}s…")
                time.sleep(delays[attempt])
                continue
            raise


def paginate(path):
    items = []
    while path:
        data = request(path)
        items.extend(data.get("items", []))
        path = data.get("nextPagePath")
        if path:
            time.sleep(11)  # 6 pedidos/min nos endpoints de histórico
    return items


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_csv(since: datetime, until: datetime):
    events = []
    start = since
    while start < until:
        end = min(start + timedelta(days=365), until)
        print(f"  export CSV {start.date()} → {end.date()}")
        res = request("/api/v0/history/exports", "POST", {
            "dataIncluded": {"includeDividends": True, "includeInterest": True,
                             "includeOrders": True, "includeTransactions": True},
            "timeFrom": iso(start), "timeTo": iso(end)})
        rid = res.get("reportId")
        link = None
        for _ in range(24):  # até ~6 min
            time.sleep(15)
            reports = request("/api/v0/history/exports") or []
            rep = next((r for r in reports if r.get("reportId") == rid), None)
            if rep and rep.get("status") == "Finished" and rep.get("downloadLink"):
                link = rep["downloadLink"]
                break
            if rep and rep.get("status") in ("Failed", "Canceled"):
                raise RuntimeError(f"export {rid} {rep.get('status')}")
        if not link:
            raise RuntimeError(f"export {rid} não ficou pronto a tempo")
        with urllib.request.urlopen(link, timeout=60) as r:
            raw = r.read()
        text = raw.decode("utf-8-sig", errors="replace")
        evs = ledger.parse_t212_csv(text, source="t212-csv")
        # Diagnóstico sem dados pessoais: tamanho, cabeçalho e tipos de linha
        lines = text.splitlines()
        actions = Counter(row.get("Action", "?") for row in csv.DictReader(io.StringIO(text)))
        print(f"    {len(raw)} bytes · {max(len(lines) - 1, 0)} linhas no CSV · {len(evs)} eventos reconhecidos")
        print(f"    cabeçalho: {lines[0][:300] if lines else '(vazio)'}")
        if actions:
            print(f"    ações: {dict(actions)}")
        if lines and not evs and len(lines) > 1:
            print("::warning::o CSV tem linhas mas nenhuma foi reconhecida — verificar o formato das colunas")
        events.extend(evs)
        start = end
        if start < until:
            time.sleep(31)  # 1 export a cada 30 s
    return events


def fetch_api():
    print("  ordens (com execução)…")
    orders = paginate("/api/v0/equity/history/orders?limit=50")
    print(f"    {len(orders)}")
    time.sleep(11)
    print("  dividendos…")
    divs = paginate("/api/v0/equity/history/dividends?limit=50")
    print(f"    {len(divs)}")
    time.sleep(11)
    print("  movimentos de caixa…")
    txs = paginate("/api/v0/equity/history/transactions?limit=50")
    print(f"    {len(txs)}")
    return ledger.parse_t212_api(orders, divs, txs)


def main():
    existing = ledger.load_transactions(TX_PATH)
    manual = ledger.load_statement_dir("data/statements")
    print(f"Ledger atual: {len(existing)} eventos · CSV manuais: {len(manual)}")

    now = datetime.now(timezone.utc)
    # Incremental só quando o ledger já vem do extrato CSV; se veio da API JSON
    # (fallback), pede-se o histórico completo para o substituir pelo extrato.
    csv_events = [e for e in existing if e.get("source") == "t212-csv"]
    if csv_events:
        last = max(e["time"] for e in csv_events)
        since = datetime.fromisoformat(last[:19]).replace(tzinfo=timezone.utc) - timedelta(days=10)
    else:
        since = None
    if since is None:
        # primeiro arranque: desde a ordem mais antiga conhecida (orders.json) − 30 dias
        first = "2015-01-01T00:00:00"
        if os.path.exists("data/orders.json"):
            with open("data/orders.json", encoding="utf-8") as f:
                ords = json.load(f)
            if ords:
                first = min(o.get("createdAt", first) for o in ords)
        since = datetime.fromisoformat(first[:19]).replace(tzinfo=timezone.utc) - timedelta(days=30)

    fetched, used = [], None
    if API_KEY and MODE in ("auto", "csv"):
        try:
            fetched = fetch_csv(since, now)
            used = "csv"
            if not fetched and not existing:
                # Um primeiro export sem nenhum evento não é credível: usa a API JSON
                print("  Export CSV sem eventos — a tentar a API JSON")
                used = None
        except Exception as e:
            print(f"  Export CSV falhou: {e}")
    if API_KEY and not used and MODE in ("auto", "api"):
        try:
            fetched = fetch_api()
            used = "api"
        except Exception as e:
            print(f"  API JSON falhou: {e}")

    if used == "csv" and fetched:
        # O extrato substitui os eventos da API JSON na janela que cobre
        # (os IDs das duas fontes são diferentes e duplicariam os eventos).
        since_d = since.date().isoformat()
        before = len(existing)
        existing = [e for e in existing if not (e.get("source") == "t212-api" and e["date"] >= since_d)]
        if before != len(existing):
            print(f"  {before - len(existing)} eventos da API substituídos pelo extrato CSV")

    merged = ledger.merge_events(existing, fetched, manual)
    ledger.save_transactions(merged, TX_PATH, meta={
        "updated": iso(now), "fonte": used or "sem-api", "eventos": len(merged)})
    print(f"Guardado {TX_PATH}: {len(merged)} eventos (fonte nova: {used or 'nenhuma'})")

    if API_KEY:
        try:
            cash = request("/api/v0/equity/account/cash")
            with open("data/account.json", "w", encoding="utf-8") as f:
                json.dump({"updated": iso(now), **(cash or {})}, f)
            print(f"  caixa: {cash.get('free')} € livre")
        except Exception as e:
            print(f"  Caixa: {e}")

    if not merged:
        motivo = ("as chaves T212 não estão definidas" if not API_KEY
                  else "o export CSV e a API não devolveram eventos (ver as linhas acima)")
        print(f"::warning::ledger vazio — {motivo}. Também podes pôr extratos CSV em data/statements/")


if __name__ == "__main__":
    main()
