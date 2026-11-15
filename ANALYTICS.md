# Desempenho · Fiscal · Dividendos

Três separadores do dashboard calculados a partir do histórico completo de transações.

## Fluxo de dados

| Passo | Script | Produz |
|---|---|---|
| Histórico da Trading 212 (export CSV pela API; fallback JSON; CSVs manuais em `data/statements/`) | `fetch_history.py` | `data/transactions.json`, `data/account.json` |
| Preços diários, dividendos por ação, câmbios e benchmarks (Yahoo) | `fetch_price_history.py` | `data/price_history.json`, `data/symbol_map.json` |
| Motores de cálculo | `build_analytics.py` | `data/analytics.json` |
| Dashboard | `build_html.py` + `analytics_views.jsx` | `index.html` |

No workflow **Update Portfolio Data**, o histórico e os preços correm às 21:30 UTC, ao sábado e nas execuções manuais. Os testes e a análise correm em todas as execuções.

## Motores (`analytics/`)

- **performance.py**: IRR (das posições e da conta), TWR (só títulos, fluxos ao fecho), CAGR, YTD, volatilidade, Sharpe, Sortino, drawdown máximo, Calmar, beta, alpha ajustado, capturas, matriz mensal, sazonalidade, ano a ano contra S&P 500, Nasdaq 100 e MSCI World, a réplica "o mesmo dinheiro no índice", os máximos, e o resultado e o IRR por posição.
- **fiscal_pt.py**: FIFO por lote com encargos; saldo anual a 28% com a exclusão da Lei 31/2024 (10/20/30% aos 2/5/8 anos); correção monetária das ações com mais de 24 meses; IRS de dividendos com crédito por convenção; juros; "se vendesses tudo hoje"; otimização por perdas; rascunho das linhas dos Anexos J e G.
- **dividends.py**: os recebidos (exatos, por ano, mês e posição, com a variação anual) e a previsão (frequência, rendimento anual, próximo ex-dividendo, yield, yield sobre o custo, crescimento, estabilidade, payout).

## Correções manuais

- **Símbolo errado ou em falta no Yahoo**: editar `data/symbol_map.json` (`"ISIN": "SIMBOLO"`, ou `null` para ignorar).
- **Parâmetros fiscais**: `data/fiscal_config.json` tem a taxa, os escalões, os coeficientes da correção monetária (portaria anual), as taxas das convenções e a região (Açores).
- **Extratos antigos**: exportar o CSV na app da Trading 212 e colocá-lo em `data/statements/`.

## Testes

```
python -m unittest discover -s tests -v
```

Os valores fiscais são uma estimativa informativa. O câmbio usado é o da corretora; a AT usa o do Banco de Portugal.
