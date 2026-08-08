# Tutorial Betfair BR — FutPythonTrader

Integração baseada em [api-betfair-tutorial](https://github.com/AraujoDavies/api-betfair-tutorial) (Davies Araújo).

## Configuração

1. Certificados em `certs/` (já copiados do seu Downloads):
   - `client-2048.crt`
   - `client-2048.key`

2. Edite `.env`:

```env
BETFAIR_USERNAME=seu_email_betfair
BETFAIR_PASSWORD=sua_senha
BETFAIR_APP_KEY=sua_app_key
BETFAIR_CERT_PATH=C:/Users/kaleb/FutPythonTraderBR/certs
BETFAIR_ENABLED=true
```

3. Teste de login:

```powershell
python main.py betfair login
python main.py betfair esportes
python main.py betfair odds "Flamengo" "Palmeiras"
```

## Endpoints (Brasil regulamentado)

| Serviço | URL |
|---------|-----|
| Login certificado | `identitysso-cert.betfair.bet.br` |
| API Exchange | `api.betfair.bet.br` |

## Código no projeto

| Arquivo | Função |
|---------|--------|
| `fpt/integrations/betfair/client.py` | Login + JSON-RPC |
| `fpt/trading/market_betfair.py` | Provider de odds Match Odds |
| `docs/betfair/tutorial.ipynb` | Notebook original adaptado |

## Links

- [Vídeo tutorial](https://youtu.be/1F4uwZhkYPU)
- [Doc login bot](https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687915/Non-Interactive+bot+login)

## Segurança

Nunca commite `.env`, `certs/*.key` ou `certs/*.crt`. Estão no `.gitignore`.
