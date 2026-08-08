# Google Drive — Service Account

1. Acesse [Google Cloud Console](https://console.cloud.google.com/)
2. Crie projeto → APIs → ative **Google Drive API**
3. Credenciais → **Conta de serviço** → criar → baixar JSON
4. No Google Drive, crie pasta `FutPythonTrader-Semanal`
5. Compartilhe a pasta com o e-mail da service account como **Editor**:
   `futpythontrader@futpythontraderbr.iam.gserviceaccount.com`

## Local (.env)

```env
GOOGLE_APPLICATION_CREDENTIALS=C:/Users/kaleb/FutPythonTraderBR/credentials/google-service-account.json
GOOGLE_DRIVE_FOLDER=FutPythonTrader-Semanal
```

Ou cole o JSON inteiro em uma linha:
```env
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

## GitHub Actions (Secrets)

| Secret | Valor |
|--------|-------|
| `FPT_API_KEY` | Chave FPT |
| `THE_ODDS_API_KEY` | Opcional |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Conteúdo completo do JSON |
| `GOOGLE_DRIVE_FOLDER_ID` | Opcional — ID da pasta no Drive |

O workflow roda **todo sábado 07:00 BRT** e envia o PDF para a pasta.
