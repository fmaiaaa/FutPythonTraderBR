# Deploy Streamlit Cloud — Operação Live

**Arquitetura:** dados, modelos e PDFs ficam no **GitHub Actions + Google Drive**. O PC local não persiste nada.

## Arquivo principal

```
streamlit_app.py
```

## Passo a passo

1. Login em https://share.streamlit.io
2. **New app** → `fmaiaaa/FutPythonTraderBR` → branch `master`
3. **Main file:** `streamlit_app.py`
4. **Secrets:** copie `.streamlit/secrets.toml.example` preenchido

## Secrets

| Secret | Descrição |
|--------|-----------|
| `FPT_API_KEY` | futpythontrader.com.br/dashboard |
| `[google].oauth_*` | Mesmos valores dos GitHub Secrets (Drive) |
| `[google].drive_folder_id` | ID da pasta Drive |
| `[betfair].*` | Credenciais + cert_pem/key_pem |
| `[google].models_drive_file_id` | Opcional — auto-descobre `fpt-models-latest.zip` no Drive |
| `[google].oauth_*` + `drive_folder_id` | Baixa `fpt-merged-latest.zip` e modelos do Drive (sem FPT API) |

## Fluxo de dados

| O quê | Onde |
|-------|------|
| Rotina semanal (PDFs) | GitHub Actions sábado 07:00 → Google Drive |
| Modelos ML | `models/fpt-models-latest.zip` no Drive |
| Dados merged | `models/fpt-merged-latest.zip` no Drive |
| Live / odds | Streamlit Cloud (memória da sessão) |
| PC local | **Não persiste** ticks, alertas nem relatórios |

## Primeira execução na nuvem

1. Configure Secrets `[google]` (mesmos do GitHub) **ou** `FPT_API_KEY`
2. Rode **Relatorio Semanal Sabado** no GitHub Actions (gera PDFs + zips no Drive)
3. Recarregue o app Streamlit — boot baixa merged + modelos do Drive (~1 min)

## Local (opcional, só dev)

```powershell
streamlit run streamlit_app.py
```

Sem `.env` de Drive: PDFs aparecem só via links do Drive se OAuth estiver configurado.
