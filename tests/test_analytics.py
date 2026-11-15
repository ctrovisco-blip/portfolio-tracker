"""Testes dos motores de análise com dados sintéticos de resultado conhecido.
Correr: python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analytics import dividends, fiscal_pt, ledger, performance  # noqa: E402
from analytics.prices import PriceBook  # noqa: E402
from analytics.util import xirr  # noqa: E402

CFG = fiscal_pt.load_config(os.path.join(ROOT, "data", "fiscal_config.json"))

CSV = """Action,Time,ISIN,Ticker,Name,Notes,ID,No. of shares,Price / share,Currency (Price / share),Exchange rate,Result,Currency (Result),Total,Currency (Total),Withholding tax,Currency (Withholding tax),Currency conversion fee,Currency (Currency conversion fee),Stamp duty reserve tax,Currency (Stamp duty reserve tax)
Deposit,2024-01-02 10:00:00,,,,,D1,,,,,,,1000.00,EUR,,,,,,
Market buy,2024-01-03 15:00:00,US0000000001,AAA,Alpha Inc,,O1,10,50.00,USD,1.10,,,455.98,EUR,,,1.13,EUR,,
Market buy,2024-01-04 09:00:00,GB0000000002,BBB,Beta PLC,,O2,100,200.00,GBX,0.86,,,233.72,EUR,,,,,1.16,GBP
Dividend (Dividend),2024-03-15 12:00:00,US0000000001,AAA,Alpha Inc,,,10,1.00,USD,1.08,,,7.87,EUR,1.50,USD,,,,
Interest on cash,2024-03-31 23:00:00,,,,,I1,,,,,,,0.55,EUR,,,,,,
Market sell,2024-04-10 15:00:00,US0000000001,AAA,Alpha Inc,,O3,4,60.00,USD,1.07,40.00,EUR,223.43,EUR,,,0.56,EUR,,
Withdrawal,2024-05-01 10:00:00,,,,,W1,,,,,,,100.00,EUR,,,,,,
"""


def ev(type_, d, key="X", qty=0.0, total=0.0, fees=0.0, **kw):
    e = {"id": f"{type_}{d}{key}{qty}", "date": d, "time": d + "T12:00:00", "type": type_,
         "isin": key, "ticker": key, "name": kw.pop("name", key), "qty": qty, "totalEur": total,
         "feesEur": fees, "source": "test"}
    e.update(kw)
    return e


class TestXirr(unittest.TestCase):
    def test_simple_year(self):
        r = xirr([(date(2021, 1, 1), -1000), (date(2022, 1, 1), 1100)])
        self.assertAlmostEqual(r, 0.10, places=6)

    def test_no_sign_change(self):
        self.assertIsNone(xirr([(date(2021, 1, 1), -1), (date(2022, 1, 1), -1)]))


class TestLedgerCsv(unittest.TestCase):
    def setUp(self):
        self.evs = ledger.parse_t212_csv(CSV)

    def test_types(self):
        self.assertEqual([e["type"] for e in self.evs],
                         ["DEPOSIT", "BUY", "BUY", "DIVIDEND", "INTEREST", "SELL", "WITHDRAWAL"])

    def test_fees_and_fx(self):
        buy_us, buy_gb = self.evs[1], self.evs[2]
        self.assertAlmostEqual(buy_us["feesEur"], 1.13)
        self.assertEqual(buy_gb["priceCcy"], "GBp")
        self.assertAlmostEqual(buy_gb["feesEur"], 1.16 / 0.86, places=4)

    def test_dividend_gross(self):
        d = self.evs[3]
        self.assertAlmostEqual(d["withholdingEur"], 1.5 / 1.08, places=4)
        self.assertAlmostEqual(d["grossEur"], 7.87 + 1.5 / 1.08, places=4)

    def test_merge_dedup(self):
        merged = ledger.merge_events(self.evs, self.evs)
        self.assertEqual(len(merged), len(self.evs))

    def test_merge_keeps_identical_same_source(self):
        a = dict(self.evs[1], id="X1"); b = dict(self.evs[1], id="X2")
        self.assertEqual(len(ledger.merge_events([a, b])), 2)

    def test_merge_csv_wins_over_api(self):
        api = dict(self.evs[1], id="999", source="t212-api")
        merged = ledger.merge_events([api], self.evs)
        self.assertEqual(len(merged), len(self.evs))
        self.assertTrue(all(e["source"] != "t212-api" for e in merged))

    def test_time_utc_header_and_card_actions(self):
        csv2 = (CSV.replace("Action,Time,", "Action,Time (UTC),", 1)
                + "Spending cashback,2024-05-02 10:00:00,,,,,C1,,,,,,,0.09,EUR,,,,,,\n"
                + "Card debit,2024-05-03 10:00:00,,,,,C2,,,,,,,12.00,EUR,,,,,,\n"
                + "Card credit,2024-05-04 10:00:00,,,,,C3,,,,,,,5.00,EUR,,,,,,\n"
                + "Dividend (Dividend manufactured payment),2024-05-05 10:00:00,US0000000001,AAA,Alpha Inc,,,6,0.5,USD,1.08,,,2.36,EUR,0.45,USD,,,,\n")
        evs = ledger.parse_t212_csv(csv2)
        types = [e["type"] for e in evs]
        self.assertEqual(len(evs), len(self.evs) + 4)
        self.assertEqual(types[-4:], ["CASHBACK", "WITHDRAWAL", "DEPOSIT", "DIVIDEND"])

    def test_api_interest_types(self):
        evs = ledger.parse_t212_api(transactions=[
            {"type": "INTEREST_ON_FREE_CASH", "amount": 0.01, "dateTime": "2024-10-14T00:00:00Z", "reference": "r1"},
            {"type": "LENDING_INTEREST", "amount": 0.2, "dateTime": "2024-10-15T00:00:00Z", "reference": "r2"}])
        self.assertEqual([e["type"] for e in evs], ["INTEREST", "INTEREST"])

    def test_quantities(self):
        q = ledger.quantities_at_end(self.evs)
        self.assertAlmostEqual(q["US0000000001"], 6)
        self.assertAlmostEqual(q["GB0000000002"], 100)


class TestForeignCurrency(unittest.TestCase):
    def test_usd_settled_trade_converted(self):
        from analytics.prices import convert_foreign_totals
        row = ("Market sell,2026-11-05 15:00:00,US0000000001,AAA,Alpha Inc,,S9,2,124.85,USD,1.00,,,249.70,USD,,,,,,\n")
        evs = ledger.parse_t212_csv(CSV + row)
        sell = evs[-1]
        self.assertEqual(sell["fxPending"], "USD")
        hist = {"fx": {"USD": {"2026-11-05": 1.10}}}
        conv, warns = convert_foreign_totals(evs, hist)
        self.assertAlmostEqual(conv[-1]["totalEur"], 249.70 / 1.10, places=4)
        self.assertEqual(conv[-1]["nativeTotal"], 249.70)
        self.assertNotIn("fxPending", conv[-1])
        self.assertEqual(conv[1]["totalEur"], evs[1]["totalEur"])  # EUR fica igual
        self.assertFalse(warns)

    def test_missing_rate_warns(self):
        from analytics.prices import convert_foreign_totals
        e = {"id": "x", "date": "2026-11-05", "type": "INTEREST", "totalEur": 1.0, "fxPending": "USD"}
        conv, warns = convert_foreign_totals([e], {"fx": {}})
        self.assertTrue(warns)


class TestFiscal(unittest.TestCase):
    def test_tiers(self):
        r = fiscal_pt.TaxRules(CFG)
        self.assertEqual(r.tier(date(2023, 1, 1), date(2024, 12, 31))[1], 0.0)
        self.assertEqual(r.tier(date(2022, 1, 1), date(2024, 12, 31))[1], 0.10)
        self.assertEqual(r.tier(date(2018, 1, 1), date(2024, 12, 31))[1], 0.20)
        self.assertEqual(r.tier(date(2010, 1, 1), date(2024, 12, 31))[1], 0.30)
        # vendas antes de 29/06/2024: sem exclusão
        self.assertEqual(r.tier(date(2010, 1, 1), date(2024, 6, 1))[1], 0.0)

    def test_fifo_and_tax(self):
        evs = [
            ev("BUY", "2021-01-04", "A", 10, 1000.0, fees=1.0, name="Alpha Inc"),
            ev("BUY", "2023-06-01", "A", 10, 1200.0, name="Alpha Inc"),
            ev("SELL", "2024-07-01", "A", 15, 2250.0, name="Alpha Inc"),
        ]
        book = PriceBook({}, evs)
        f = fiscal_pt.compute(evs, book, date(2024, 12, 31), CFG)
        y = next(r for r in f["byYear"] if r["ano"] == 2024)
        # lote 1: 10 u, custo 1000, venda 1500 → +500 (2–5 anos, exclusão 10%)
        # lote 2: 5 u,  custo 600,  venda 750  → +150 (< 2 anos)
        self.assertAlmostEqual(y["netRealizedEur"], 650.0, places=2)
        self.assertAlmostEqual(y["irsRealizedEur"], (500 * 0.9 + 150) * 0.28, places=2)
        lots = f["lotesAbertos"]
        self.assertEqual(len(lots), 1)
        self.assertAlmostEqual(lots[0]["qty"], 5)
        self.assertAlmostEqual(lots[0]["costEur"], 600.0, places=2)
        self.assertEqual(lots[0]["nextTierDate"], "2025-06-01")

    def test_losses_offset_and_carry(self):
        evs = [ev("BUY", "2024-01-02", "A", 10, 1000.0), ev("SELL", "2024-09-02", "A", 10, 800.0),
               ev("BUY", "2024-01-02", "B", 10, 1000.0), ev("SELL", "2024-09-03", "B", 10, 1100.0)]
        f = fiscal_pt.compute(evs, PriceBook({}, evs), date(2024, 12, 31), CFG)
        y = f["byYear"][0]
        self.assertEqual(y["irsRealizedEur"], 0)
        self.assertAlmostEqual(y["prejuizoAReportarEur"], 100.0)

    def test_dividend_credit(self):
        r = fiscal_pt.TaxRules(CFG)
        self.assertAlmostEqual(r.dividend_irs(100, 15, "US")[0], 13.0)
        self.assertAlmostEqual(r.dividend_irs(100, 25, "CA")[0], 13.0)  # crédito limitado a 15%
        self.assertAlmostEqual(r.dividend_irs(100, 0, "GB")[0], 28.0)
        self.assertAlmostEqual(r.dividend_irs(100, 28, "PT")[0], 0.0)

    def test_withholding_recovery(self):
        evs = [
            ev("DIVIDEND", "2026-03-01", "CA0000000001", 10, 11.73, grossEur=15.64, withholdingEur=3.91),
            # dividendo suíço: parte tributada + parte isenta (não dilui a taxa)
            ev("DIVIDEND", "2026-04-23", "CH0000000001", 1, 0.45, grossEur=0.652, withholdingEur=0.202),
            ev("DIVIDEND", "2026-04-23", "CH0000000001", 1, 0.69, grossEur=0.69, withholdingEur=0.0),
            ev("DIVIDEND", "2026-05-20", "IT0000000001", 1, 1.78, grossEur=2.41, withholdingEur=0.63),
            ev("DIVIDEND", "2026-06-01", "US0000000001", 1, 8.5, grossEur=10.0, withholdingEur=1.5),   # excluído
            ev("DIVIDEND", "2026-06-01", "PT0000000001", 1, 0.65, grossEur=1.0, withholdingEur=0.35),  # excluído
        ]
        r = fiscal_pt.withholding_recovery(evs, CFG, date(2026, 11, 15),
                                           {"CA-2026": {"estado": "pedido", "atualizado": "2026-11-15"}})
        by = {l["id"]: l for l in r["linhas"]}
        self.assertEqual(set(by), {"CA-2026", "CH-2026", "IT-2026"})
        self.assertAlmostEqual(by["CA-2026"]["recuperarEur"], 1.56, places=2)
        self.assertEqual(by["CA-2026"]["prazo"], "2028-12-31")
        self.assertEqual(by["CA-2026"]["estado"], "pedido")
        self.assertAlmostEqual(by["CH-2026"]["recuperarEur"], 0.202 - 0.15 * 0.652, places=2)
        self.assertEqual(by["IT-2026"]["prazo"], "2030-05-20")  # 48 meses após o pagamento
        self.assertEqual(by["IT-2026"]["estado"], "por_reclamar")

    def test_oversell_warning(self):
        evs = [ev("SELL", "2024-09-02", "A", 1, 10.0)]
        f = fiscal_pt.compute(evs, PriceBook({}, evs), date(2024, 12, 31), CFG)
        self.assertTrue(f["avisos"])

    def test_split(self):
        evs = [ev("BUY", "2024-01-02", "A", 10, 1000.0),
               ev("SPLIT_OUT", "2024-06-10", "A", 10, 0.0),
               ev("SPLIT_IN", "2024-06-10", "A", 40, 0.0),
               ev("SELL", "2024-09-02", "A", 40, 1200.0)]
        f = fiscal_pt.compute(evs, PriceBook({}, evs), date(2024, 12, 31), CFG)
        self.assertAlmostEqual(f["byYear"][0]["netRealizedEur"], 200.0)


def flat_history(days, prices, bench=None):
    closes = {k: {d.isoformat(): p(d) for d in days} for k, p in prices.items()}
    h = {"instruments": {k: {"symbol": k, "ccy": "EUR", "closes": v, "divs": {}} for k, v in closes.items()},
         "fx": {"USD": {d.isoformat(): 1.0 for d in days}}, "benchmarks": {}}
    for b in ("SPY", "QQQ", "URTH"):
        h["benchmarks"][b] = {"ccy": "EUR", "closes": {d.isoformat(): (bench(d) if bench else 100.0) for d in days}}
    return h


class TestPerformance(unittest.TestCase):
    def test_twr_neutral_to_flows(self):
        start = date(2024, 1, 1)
        days = [start + timedelta(days=i) for i in range(400)]
        # preço sobe de 100 para 110 a meio; reforço grande depois da subida
        price = lambda d: 100.0 if d < date(2024, 6, 1) else 110.0
        evs = [ev("DEPOSIT", "2024-01-02", None, total=1000.0),
               ev("BUY", "2024-01-02", "A", 10, 1000.0),
               ev("DEPOSIT", "2024-07-01", None, total=11000.0),
               ev("BUY", "2024-07-01", "A", 100, 11000.0)]
        book = PriceBook(flat_history(days, {"A": price}), evs)
        p = performance.compute(evs, book, date(2025, 1, 31))
        self.assertAlmostEqual(p["totais"]["twrPct"], 10.0, places=2)
        # dinheiro: 12 000 depositados, valem 12 100 → +100
        self.assertAlmostEqual(p["totais"]["totalReturnEur"], 100.0, places=2)
        self.assertLess(p["totais"]["irrPct"], p["totais"]["cagrPct"])

    def test_benchmark_replica(self):
        start = date(2024, 1, 1)
        days = [start + timedelta(days=i) for i in range(200)]
        evs = [ev("DEPOSIT", "2024-01-02", None, total=1000.0), ev("BUY", "2024-01-02", "A", 10, 1000.0)]
        book = PriceBook(flat_history(days, {"A": lambda d: 100.0}, bench=lambda d: 100 + (d - start).days * 0.1), evs)
        p = performance.compute(evs, book, date(2024, 7, 1))
        rep = p["seInvestidoNoIndice"]["spy"]
        expected = 1000 * ((100 + (date(2024, 7, 1) - start).days * 0.1) / (100 + 1 * 0.1)) - 1000
        self.assertAlmostEqual(rep["eur"], expected, places=0)

    def test_weekly_beta(self):
        import math
        start = date(2024, 1, 1)
        days = [start + timedelta(days=i) for i in range(400)]
        bench = lambda d: 100 * math.exp(0.02 * math.sin((d - start).days / 9.0) + 0.0003 * (d - start).days)
        price = lambda d: 100 * (bench(d) / 100) ** 2  # retorno ≈ 2× o do índice
        evs = [ev("DEPOSIT", "2024-01-02", None, total=1000.0), ev("BUY", "2024-01-02", "A", 10, 1000.0)]
        p = performance.compute(evs, PriceBook(flat_history(days, {"A": price}, bench=bench), evs), date(2025, 1, 31))
        self.assertAlmostEqual(p["risco"]["beta"], 2.0, delta=0.1)

    def test_drawdown(self):
        start = date(2024, 1, 1)
        days = [start + timedelta(days=i) for i in range(120)]
        price = lambda d: 100.0 if d < date(2024, 2, 1) else (80.0 if d < date(2024, 3, 1) else 120.0)
        evs = [ev("DEPOSIT", "2024-01-02", None, total=1000.0), ev("BUY", "2024-01-02", "A", 10, 1000.0)]
        p = performance.compute(evs, PriceBook(flat_history(days, {"A": price}), evs), date(2024, 4, 15))
        self.assertAlmostEqual(p["risco"]["maxDrawdownPct"], -20.0, places=2)


class TestDividends(unittest.TestCase):
    def test_forecast_quarterly(self):
        today = date(2025, 1, 15)
        divs = {}
        d = date(2019, 2, 10)
        while d < today:
            divs[d.isoformat()] = 0.25 if d.year < 2024 else 0.30
            d += timedelta(days=91)
        hist = {"instruments": {"A": {"symbol": "A", "ccy": "USD", "closes": {"2025-01-14": 40.0}, "divs": divs}},
                "fx": {"USD": {"2025-01-14": 1.0}}, "benchmarks": {}}
        evs = [ev("BUY", "2023-01-02", "A", 100, 3000.0),
               ev("DIVIDEND", "2024-05-01", "A", 100, 25.5, grossEur=30.0, withholdingEur=4.5)]
        book = PriceBook(hist, evs)
        op = {"A": {"qty": 100, "costEur": 3000.0, "valueEur": 4000.0, "ticker": "A", "name": "A", "isin": "US1", "display": "A"}}
        out = dividends.compute(evs, book, today, op)
        f = out["previsao"]["posicoes"][0]
        self.assertEqual(f["frequency"], 4)
        self.assertAlmostEqual(f["estimatedAnnualIncomeEur"], 120.0, places=1)
        self.assertAlmostEqual(f["withholdingRateAppliedPct"], 15.0, places=1)
        self.assertAlmostEqual(f["yieldOnCostPct"], 4.0, places=1)
        self.assertEqual(out["recebido"]["totalNetEur"], 25.5)
        self.assertTrue(out["previsao"]["calendario"])


if __name__ == "__main__":
    unittest.main()
