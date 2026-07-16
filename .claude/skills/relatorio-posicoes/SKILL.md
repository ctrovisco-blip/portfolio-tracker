---
name: relatorio-posicoes
description: Gera o relatório de avaliação das posições do portfolio Trading212 — performance, peso, valor, fundamentais, rendimento, riscos e veredicto qualitativo por posição. Produz um Artifact HTML interactivo e um markdown versionado em reports/. Usar quando o utilizador pedir o relatório de posições / avaliação do portfolio.
---

# Relatório de Avaliação de Posições

Gera duas saídas a partir dos dados já commitados em `data/` (actualizados pelo
workflow `update.yml`):

1. **Artifact HTML interactivo** (privado) — actualizar SEMPRE o mesmo URL:
   `https://claude.ai/code/artifact/3be4500a-6652-4f4f-9e2d-951eef0616e4`
   (passar como `url` na ferramenta Artifact; favicon `📊`, manter).
2. **Markdown versionado** — `reports/relatorio_posicoes_YYYY-MM-DD.md`,
   commitado e enviado para o branch de trabalho da sessão.

Idioma: português europeu (pré-acordo, como o resto do repositório).
Números em formato pt-PT (vírgula decimal, € prefixado).

## Passos

1. **Verificar frescura dos dados**: `git log -1 --format='%ci' -- data/positions.json`.
   Se tiverem mais de ~24h, avisar o utilizador e perguntar se quer despoletar o
   workflow `update.yml` no GitHub Actions primeiro (não despoletar sem perguntar).

2. **Calcular métricas**:
   `python3 .claude/skills/relatorio-posicoes/report_metrics.py > /tmp/metrics.json`
   O JSON traz `summary`, `positions` (ordenadas por valor) e `ytd` (séries
   carteira + S&P 500). Ler o cabeçalho do script antes de alterar convenções.

3. **Escrever os veredictos** (a parte qualitativa, nova em cada execução).
   Para cada posição: `{"light": "verde|amarelo|vermelho", "tag": "2-4 palavras", "text": "3-5 frases"}`.
   Critérios:
   - `verde` — posição a cumprir o seu papel (núcleo, income, hedge, momentum) sem sinais de alerta;
   - `amarelo` — algo a vigiar: peso excessivo, momentum do título fraco vs mercado, negócio em declínio, posição sem massa crítica;
   - `vermelho` — exige decisão: perda com tese em dúvida, entrada em avaliação extrema, tendência fortemente negativa.
   O texto deve citar números concretos do metrics.json (P/L, YTD vs S&P 500,
   yield, payout, nº de compras/DCA, vendas parciais) e dizer o que observar a
   seguir — leitura de dados, nunca recomendação de compra/venda.

4. **Montar o HTML**: usar `.claude/skills/relatorio-posicoes/template.html`,
   substituindo `__DATA__` por um JSON com:
   - `summary`, `positions`, `ytd` (do metrics.json), `verdicts` (passo 3);
   - `asofLong` = `summary.asofLong` do metrics.json (já em hora de Lisboa);
   - `notes.currency` e `notes.concentration` (1-2 frases cada, com os números actuais);
   - `risks` (3-6 itens HTML `<b>Título.</b> explicação`) e `conclusions` (3-6 itens HTML).
   Publicar com a ferramenta Artifact usando o `url` acima. Se o template for
   alterado, validar a paleta com a skill dataviz e re-renderizar antes de publicar.

5. **Escrever o markdown** com a mesma estrutura do HTML:
   resumo executivo → alocação/concentração → tabela geral → ficha por posição
   (com veredicto 🟢/🟡/🔴) → rendimento → riscos → conclusões → metodologia.
   Referência de formato: `reports/relatorio_posicoes_2026-07-16.md`.
   Commit + push para o branch da sessão (nunca directamente para main).

6. **Resumo final ao utilizador**: link do Artifact, caminho do markdown, e
   3-5 destaques do que mudou desde o relatório anterior (comparar com o
   `reports/relatorio_posicoes_*.md` mais recente, se existir).

## Ressalvas obrigatórias (incluir sempre no relatório)

- A série "carteira" (3m/YTD/1a) é a composição **actual** projectada no
  histórico (backtest), não o retorno real da conta.
- Dividendos são **estimativas** (yield actual × valor), não valores recebidos.
- Custo-base = valor − P/L da T212 (inclui efeito cambial); o valor bruto de
  compras em `orders.json` está incompleto e não deve ser usado.
- YTD/1 ano por título referem-se à listagem detida (listagens EUR de empresas
  US incluem efeito cambial).
- O relatório não constitui recomendação de investimento.
