# Deploy Streamlit Cloud — Operação Live

## Arquivo principal

```
streamlit_app.py
```

No [share.streamlit.io](https://share.streamlit.io): **Main file path** = `streamlit_app.py`

## Passo a passo

1. Faça login em https://share.streamlit.io com GitHub
2. **New app** → repositório `fmaiaaa/FutPythonTraderBR` → branch `master`
3. **Main file:** `streamlit_app.py`
4. **Advanced settings → Secrets:** cole o conteúdo de `.streamlit/secrets.toml.example` preenchido
5. Deploy

## Secrets obrigatórios

| Secret | Descrição |
|--------|-----------|
| `FPT_API_KEY` | Chave em futpythontrader.com.br/dashboard |
| `[betfair].username` | E-mail Betfair BR |
| `[betfair].password` | Senha |
| `[betfair].app_key` | APP_KEY da aplicação |
| `[betfair].cert_pem` | Conteúdo de `client-2048.crt` |
| `[betfair].key_pem` | Conteúdo de `client-2048.key` |

## Primeira execução

Na nuvem não há `data/` nem modelos. O app:

1. Baixa dados FPT (watchlist)
2. Treina modelos (~5–10 min) **ou** usa `MODELS_ZIP_URL` se configurado

## Execução de ordens

Por padrão na nuvem: **paper mode** (simula, não aposta de verdade).

Para ordens reais (cuidado):

```toml
[execution]
enabled = true
paper_mode = false
auto_execute = false
```

## Local

```powershell
streamlit run streamlit_app.py
```

Use `.env` local em vez de Secrets.
