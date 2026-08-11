#!/usr/bin/env bash
# Betfair certs + credenciais para GitHub Actions (coleta live).
set -euo pipefail

mkdir -p certs

if [ -n "${BETFAIR_CERT_PEM:-}" ]; then
  printf '%s' "$BETFAIR_CERT_PEM" > certs/client-2048.crt
fi
if [ -n "${BETFAIR_KEY_PEM:-}" ]; then
  printf '%s' "$BETFAIR_KEY_PEM" > certs/client-2048.key
fi

if [ -f certs/client-2048.crt ] && [ -f certs/client-2048.key ]; then
  {
    echo "BETFAIR_USERNAME=${BETFAIR_USERNAME:-}"
    echo "BETFAIR_PASSWORD=${BETFAIR_PASSWORD:-}"
    echo "BETFAIR_APP_KEY=${BETFAIR_APP_KEY:-}"
    echo "BETFAIR_CERT_PATH=${GITHUB_WORKSPACE:-.}/certs"
    echo "BETFAIR_ENABLED=true"
  } >> .env
  echo "Betfair: certificados configurados"
else
  echo "Betfair: certificados ausentes — coleta usará odds FPT/simuladas"
fi
