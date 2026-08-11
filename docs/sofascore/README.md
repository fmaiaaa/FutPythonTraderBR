# SofaScore — stats live (API não oficial)

Integração para enriquecer o monitor live com estatísticas in-play do [SofaScore](https://www.sofascore.com/), útil para scalping baseado em pressão (SOT, xG, momentum).

## Fontes consultadas

| Repositório | Uso |
|-------------|-----|
| [apdmatos/sofascore-api](https://github.com/apdmatos/sofascore-api) | Documentação de endpoints `/api/v1` |
| [LuiVLoureiro/Scrapping-Dados-Sofascore](https://github.com/LuiVLoureiro/Scrapping-Dados-Sofascore) | Scraping histórico (Selenium) — **não** usado para live |
| [pseudo-r/Public-Sofascore-API](https://github.com/pseudo-r/Public-Sofascore-API) | TLS fingerprint + rate limits |
| [Kirill52300/sofascore_api](https://github.com/Kirill52300/sofascore_api) | Padrão `curl_cffi` |

## O que dá para obter (gratuito, não oficial)

- Jogos do dia / live: `scheduled-events`, `events/live`
- Placar e status: `/event/{id}`
- **Estatísticas live**: posse, chutes, SOT, xG, escanteios, big chances
- **Gráfico de pressão**: `/event/{id}/graph` (`graphPoints`)
- Incidentes (gols, cartões): `/event/{id}/incidents`

Não há API key pública. O SofaScore usa proteção anti-bot (Cloudflare / TLS fingerprint). Requisições com `requests` puro tendem a retornar **403**.

## Configuração

Em `config/live.yaml`:

```yaml
sofascore:
  enabled: true
  fetch_in_play_only: true
  log_snapshots: true
  min_interval_seconds: 0.4
```

Dependência:

```bash
pip install curl_cffi
```

## Teste manual

```bash
python scripts/sofascore_probe.py --date 2025-08-09
python scripts/sofascore_probe.py --live
python scripts/sofascore_probe.py --event-id 9620324
```

## Dados persistidos

| Caminho | Conteúdo |
|---------|----------|
| `data/betfair/ticks/` | CSV com colunas `ss_*` (pressão, xG, etc.) |
| `data/sofascore/snapshots/` | JSONL por mês com snapshots completos |

## Rotulador para backtest scalping

Após acumular ticks durante jogos:

```bash
python scripts/label_tick_forward.py -o data/betfair/labeled_ticks.csv
```

Adiciona `back_home_fwd_10s`, `delta_back_home_30s`, etc.

## Limitações

- API **não documentada oficialmente** — pode mudar ou bloquear IPs/datacenters
- Respeite rate limit (`min_interval_seconds`)
- Termos de uso do SofaScore podem restringir scraping automatizado
- Índice de pressão é **heurístico**, não calibrado — use para sinais relativos + validação empírica

## Scalping PRESSURE_STEAM

Config em `config/live.yaml`:

```yaml
strategies:
  pressure_steam:
    enabled: true
    min_pressure_delta: 8.0
    min_dominance: 12.0
    steam_pct: 0.03

scalping:
  stake_pct: 0.005
  take_profit_pct: 0.015
  stop_loss_pct: 0.02
  timeout_seconds: 60
  auto_open_on_signal: false
  auto_execute_scalp: false
```

CLI backtest:

```bash
python main.py scalping-backtest
```

Alertas: `PRESSURE_STEAM` (entrada), `SCALP_EXIT` (TP/SL/timeout).

## Matching FPT ↔ SofaScore

Mesmo fuzzy match usado na Betfair (`home`/`away` + tokens). Se não encontrar, o jogo segue só com odds Betfair/FPT.
