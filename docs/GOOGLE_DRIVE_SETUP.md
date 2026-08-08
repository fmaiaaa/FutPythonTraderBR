# Google Drive — Service Account (obrigatório para CI)

Service Accounts **não têm quota de armazenamento**. Por isso os uploads falham com **403** se a pasta não for compartilhada.

## Passo a passo

1. [Google Cloud Console](https://console.cloud.google.com/) → projeto → **Google Drive API** ativada
2. **IAM → Service Accounts** → criar → baixar JSON
3. No **Google Drive pessoal**, crie a pasta `FutPythonTrader-Semanal`
4. Compartilhe a pasta com o e-mail da SA como **Editor**:
   **`futpythontrader@futpythontraderbr.iam.gserviceaccount.com`**
5. Copie o **ID da pasta** da URL: `https://drive.google.com/drive/folders/ESTE_ID`

   Sua pasta local (`.env`): `1Qs1vLDtyf1k61MdgqVcbvTtKr43KGeJn`

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
