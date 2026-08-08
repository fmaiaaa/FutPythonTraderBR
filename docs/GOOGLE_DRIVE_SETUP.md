# Google Drive — OAuth (Gmail pessoal) ou Service Account

Desde **abr/2025**, Service Accounts **novas** não têm quota de armazenamento e **não conseguem fazer upload** em pastas do Meu Drive pessoal — mesmo compartilhadas. O compartilhamento continua necessário para a SA **ler** a pasta, mas o upload exige **OAuth** (recomendado) ou **Google Workspace Shared Drive**.

## Opção A — OAuth (recomendado para @gmail.com)

1. [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services → OAuth consent screen** (External) → adicionar escopo `drive`
2. **Credentials → Create OAuth client ID → Desktop app**
3. No `.env`:

```env
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REFRESH_TOKEN=...
GOOGLE_DRIVE_FOLDER_ID=1Qs1vLDtyf1k61MdgqVcbvTtKr43KGeJn
```

4. Gerar refresh token (uma vez):

```powershell
python scripts/get_google_oauth_token.py
```

5. GitHub Secrets (Settings → Secrets → Actions):

| Secret | Valor |
|--------|-------|
| `GOOGLE_OAUTH_CLIENT_ID` | do JSON OAuth |
| `GOOGLE_OAUTH_CLIENT_SECRET` | do JSON OAuth |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | gerado uma vez (script abaixo) |
| `GOOGLE_DRIVE_FOLDER_ID` | `1Qs1vLDtyf1k61MdgqVcbvTtKr43KGeJn` |

**Sem salvar no PC** — rode uma vez (abre navegador, grava só no GitHub):

```powershell
pip install google-auth-oauthlib
python scripts/setup_google_oauth_github.py --client-json "C:\Users\kaleb\Downloads\client_secret_....json"
```

## Opção B — Service Account (Shared Drive / contas antigas)

1. Google Cloud → **Google Drive API** ativada
2. **IAM → Service Accounts** → JSON em `credentials/google-service-account.json`
3. Compartilhe a pasta com **`futpythontrader@futpythontraderbr.iam.gserviceaccount.com`** como **Editor**
4. Para Gmail pessoal: upload **só funciona** se a SA foi criada **antes de abr/2025**; caso contrário use OAuth acima

## Verificar antes do CI

```powershell
python scripts/verify_drive_access.py
```

Se retornar erro 403, a pasta **não está compartilhada** com a Service Account.

## `.env` local

```env
GOOGLE_APPLICATION_CREDENTIALS=C:/Users/kaleb/FutPythonTraderBR/credentials/google-service-account.json
GOOGLE_DRIVE_FOLDER_ID=ID_DA_PASTA_COMPARTILHADA
GOOGLE_DRIVE_FOLDER=FutPythonTrader-Semanal
```

## GitHub Secrets

| Secret | Valor |
|--------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Conteúdo completo do JSON |
| `GOOGLE_DRIVE_FOLDER_ID` | ID da pasta compartilhada |

## Estrutura no Drive

```
FutPythonTrader-Semanal/
  2026-08/
    2026-08-08/
      FutPythonTrader_brasileirao_serie_a_....pdf
      ModeloEval_2026-08-08.pdf
      betfair_analise_2026-08-08.xlsx   # ticks odds (se live rodou no fim de semana)
      drive_links.json
      ...
```

## Verificar upload

```powershell
python -c "
from pathlib import Path
from fpt.integrations.google_drive import upload_weekend_folder
from fpt.weekend import weekend_report_dir
from fpt.calendar import weekend_window
s,_=weekend_window()
upload_weekend_folder(weekend_report_dir(s), str(s))
"
```

O arquivo `drive_links.json` é gerado na pasta do relatório e usado pelo Streamlit para links de download.
