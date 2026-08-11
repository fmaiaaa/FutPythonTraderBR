# Operação online 24h — FutPythonTraderBR

## Perfil robusto (recomendado)

O perfil **`robust`** opera **somente nas 14 ligas tier 1** da watchlist, com base FPT validada. Ligas em probation (tier 3) e ligas fora da watchlist são bloqueadas no calendário e nas entradas.

```bat
python D:\FutPythonTraderBR\project\scripts\set_fpt_profile.py robust
python D:\FutPythonTraderBR\project\scripts\seed_robust_ranking.py
```

Ou use `scripts\choose_fpt_profile.bat` → opção **1**.

| Perfil | Uso |
|--------|-----|
| `robust` | Operação conservadora — só tier 1 |
| `watchlist` | 14 ligas + probation tier 3 (Kelly mínimo) |
| `all_leagues` | Todas ligas FPT do dia (scan pesado) |

---

## Consulta 24h na nuvem (GitHub Actions)

O workflow **`.github/workflows/live-pulse-24h.yml`** roda a cada **15 minutos**:

1. Scan live completo (perfil `robust`)
2. Grava snapshot em `data/live/YYYY-MM/snapshot_YYYY-MM-DD.json`
3. Publica no Google Drive:
   - `models/fpt-live-snapshot-latest.json`
   - `models/fpt-live-pulse-latest.json` (heartbeat)

### Secrets necessários (GitHub → Settings → Secrets)

| Secret | Obrigatório |
|--------|-------------|
| `FPT_API_KEY` | Sim |
| `GOOGLE_DRIVE_FOLDER_ID` | Sim (upload snapshot) |
| `GOOGLE_OAUTH_CLIENT_ID` | Sim |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Sim |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | Sim |
| `BETFAIR_*` | Recomendado (odds exchange) |

### Disparo manual

GitHub → Actions → **Pulse Live 24h** → Run workflow.

Local (teste):

```bat
set FPT_PROFILE=robust
python D:\FutPythonTraderBR\project\scripts\run_cloud_pulse.py
```

---

## Dashboard online (Streamlit Cloud)

1. Conecte o repositório no [Streamlit Cloud](https://share.streamlit.io)
2. Entry point: `streamlit_app.py`
3. Configure os Secrets (ver `docs/STREAMLIT_CLOUD.md`)
4. O bootstrap baixa automaticamente `fpt-live-snapshot-latest.json` do Drive quando não há snapshot local

---

## Operação local 24/7

Para operação completa (coleta + robô + dashboard) na sua máquina:

```bat
D:\FutPythonTraderBR\project\scripts\start_fpt_completo.bat
```

Escolha perfil **Robusto** no menu. Reinicie **FPT Operação** após mudar perfil.

---

## Arquivos principais

| Arquivo | Função |
|---------|--------|
| `data/live/runtime_profile.json` | Perfil ativo |
| `data/leagues/ranking.json` | Tier por liga |
| `data/live/cloud_pulse.json` | Último pulse (local) |
| Drive `fpt-live-snapshot-latest.json` | Snapshot para consulta remota |
