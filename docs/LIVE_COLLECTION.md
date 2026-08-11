# Coleta Live — GitHub Actions

Workflow: `.github/workflows/live-collect-weekend.yml`

## Cronograma (BRT)

| Quando | Ação |
|--------|------|
| Sábado 14:00 | Coleta 5h (1 tick/min por jogo in-play) |
| Domingo 14:00 | Coleta 5h |
| Domingo 23:30 | Finaliza: dataset + treino scalping + upload Drive |

Também: `workflow_dispatch` com modo `collect` ou `finalize`.

## O que é coletado

Por tick (60s), por jogo in-play:

- **Betfair:** back/lay H/E/A, matched, placar, minuto
- **SofaScore:** posse, chutes, SOT, xG, escanteios, pressão, momentum
- **SofaScore extra:** escalações (1× por jogo), incidentes, shotmap
- **Derivados:** delta pressão, movimento de odd

Persistência: `data/live_collection/YYYY-MM/YYYY-MM-DD/ticks_minute_*.csv`

## Drive

- `models/fpt-live-collection-latest.zip` — base completa acumulada
- Integrado ao action semanal (`weekend-saturday.yml`)

## Secrets GitHub necessários

| Secret | Obrigatório |
|--------|-------------|
| `FPT_API_KEY` | Sim |
| `GOOGLE_DRIVE_FOLDER_ID` | Sim (finalize/upload) |
| `GOOGLE_OAUTH_*` ou `GOOGLE_SERVICE_ACCOUNT_JSON` | Sim (Drive) |
| `BETFAIR_USERNAME` | Recomendado |
| `BETFAIR_PASSWORD` | Recomendado |
| `BETFAIR_APP_KEY` | Recomendado |
| `BETFAIR_CERT_PEM` | Recomendado (conteúdo do .crt) |
| `BETFAIR_KEY_PEM` | Recomendado (conteúdo do .key) |

Sem Betfair, a coleta usa odds FPT/simuladas — stats SofaScore continuam.

## Treino scalping

Após coleta: `data/models/scalping/scalping_classifier.joblib`

Features: `config/scalping_model.yaml`

Target: lucro BACK em +30s (`target_profitable_30s`)

## Comandos locais

```bash
python main.py collect-live 60 60    # 60 min, intervalo 60s
python main.py finalize-collection --upload-drive
```
