# FutPythonTrader BR — Operação campeonatos masculinos

Pipeline Python usando a [API FutPythonTrader](https://futpythontrader.com.br/api-docs) para baixar, consolidar e analisar **todos os campeonatos masculinos do Brasil** disponíveis na plataforma.

## Campeonatos incluídos (6 ligas × múltiplas temporadas)

| Slug | Campeonato | Temporadas |
|------|-----------|------------|
| `serie-a-betano` | Brasileirão Série A | 2021–2026 |
| `serie-b` | Série B | 2021–2026 |
| `serie-b-superbet` | Série B Superbet | 2026 |
| `serie-c` | Série C | 2021–2026 |
| `serie-d` | Série D | 2021–2026 |
| `copa-betano-do-brasil` | Copa do Brasil | 2021–2026 |

**Total: 31 bases** (~milhares de partidas com odds, xG, escanteios, etc.)

> A API **não inclui estaduais** (Carioca, Paulista, Mineiro...) — apenas competições nacionais listadas acima.

## Setup (2 min)

```bash
cd C:\Users\kaleb\FutPythonTraderBR
pip install -r requirements.txt
copy .env.example .env
# Edite .env e cole sua FPT_API_KEY do dashboard
```

## Comandos

```bash
python main.py list              # ver campeonatos
python main.py download-all      # baixa TUDO (~5-10 min)
python main.py merge             # consolida em data/merged/
python main.py resumo            # stats por campeonato
python main.py jogos             # jogos de hoje
python main.py operacao          # operação diária completa
python main.py analise Flamengo Palmeiras
python main.py dashboard         # painel Streamlit
```

## Operação diária

1. `python main.py operacao` — busca jogos do dia + cruza com histórico BR
2. Gera `data/daily/operacao_YYYY-MM-DD.txt` com:
   - Forma recente dos times (V/E/D, Over 2.5, BTTS)
   - Confronto direto (H2H)
   - Sugestão de mercado (Over/Under/BTTS)

## Dados disponíveis por partida

Odds 1X2, Over/Under, escanteios, xG, xGOT, posse, chutes, cartões, faltas — ver [documentação completa](https://futpythontrader.com.br/api-docs).

## Operação Live (fim de semana)

```bash
streamlit run streamlit_app.py    # local
python main.py live                 # atalho
```

**Streamlit Cloud:** main file = `streamlit_app.py` — veja [docs/STREAMLIT_CLOUD.md](docs/STREAMLIT_CLOUD.md)


### Pipeline completo

```
175+ features FPT → HistGradientBoosting → calibração → φ dinâmico → ¼Kelly → ENTER/SKIP
```

**Features geradas automaticamente:**
- Forma rolling (5/10/20 jogos): gols, xG, chutes, escanteios, cartões, posse, BTTS, Over 2.5
- **Agenda cruzada**: dias de descanso, jogos em 7/14/21 dias, troca de campeonato (ex: Copa quarta + Série A sábado)
- H2H, posição na tabela (proxy por pontos), odds implícitas de todos mercados FPT
- Stats FT e HT históricos por time

**Dois modelos:**
| Modelo | Target | Uso |
|--------|--------|-----|
| Modelo 1 | 1X2 (H/D/A) | Probabilidade + odd justa + φ |
| Modelo 2 | Lucro no HT | Kelly sobre o trade (não vitória FT) |

### Saída de cada operação

```
PROBABILIDADE ESTIMADA:     58.2%
ODD JUSTA:                  1.718
φ SEGURANCA:                1.095  (ajustado pelo erro de calibração)
ODD MINIMA ENTRADA:         1.881
ODD MERCADO:                2.100
EDGE:                       +6.5 p.p.
LUCRO ESTIMADO (HT):        +3.2%
KELLY CHEIO:                8.1%
¼ KELLY:                    2.0%
% DA BANCA:                 1.0% (= R$ 10.00)
```

### Comandos

```bash
python main.py download-all     # baixar bases FPT
python main.py treinar          # treinar ML (~175 features, minutos)
python main.py avaliar Flamengo Palmeiras 2.10 home
python main.py scan             # entradas do dia
python main.py dashboard
```

### φ dinâmico

φ não é fixo — é calculado por faixa de probabilidade usando o **erro de calibração** (ECE):
- Se o modelo diz 60% mas historicamente acerta 54% nessa faixa → φ sobe
- `odd_minima = odd_justa × φ`

### Kelly

```
f* = (b×p - q) / b     onde b = odd_efetiva - 1, p = P(lucro no HT)
stake = min(¼ × f* × confiança, 1% banca)
```

## Rotina semanal (sábado + domingo) — **somente GitHub Actions**

**Watchlist (13 competições):** Série A/B, Copa do Brasil, Libertadores, Sul-Americana, LaLiga, Serie A ITA, Eredivisie, Bundesliga, Ligue 1, Liga Portugal, Premier League, Primera Nacional.

Todo **sábado às 07:00 BRT** o workflow gera PDFs, envia ao **Google Drive** e publica artefatos no GitHub:

- **Workflow:** [.github/workflows/weekend-saturday.yml](.github/workflows/weekend-saturday.yml) — cron `0 10 * * 6` (07:00 BRT)
- **Disparo manual:** [GitHub Actions](https://github.com/fmaiaaa/FutPythonTraderBR/actions) → *Relatorio Semanal Sabado*
- **PDFs:** pasta `FutPythonTraderBR` no Drive (`GOOGLE_DRIVE_FOLDER_ID`)
- **Modelos ML:** `models/fpt-models-latest.zip` no Drive (para Streamlit Cloud)

> **Não use agendador local** — `python main.py fim-de-semana` está bloqueado fora do CI.

## Operação Live (Streamlit Cloud)

Monitor in-time sábado/domingo: placares Betfair, odds back/lay, alertas ML, PDFs via **Google Drive**.

**Deploy:** [share.streamlit.io](https://share.streamlit.io) → `streamlit_app.py` — veja [docs/STREAMLIT_CLOUD.md](docs/STREAMLIT_CLOUD.md)

Secrets: `FPT_API_KEY`, `[google].oauth_*`, `[betfair].*` — copie de `.streamlit/secrets.toml.example`

Repositório: https://github.com/fmaiaaa/FutPythonTraderBR

