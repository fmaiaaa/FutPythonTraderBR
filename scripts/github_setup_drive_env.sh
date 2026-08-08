#!/usr/bin/env bash
# Monta .env do Drive a partir de secrets do GitHub Actions (OAuth preferido).
set -euo pipefail

: "${GOOGLE_DRIVE_FOLDER_ID:?GOOGLE_DRIVE_FOLDER_ID ausente}"

{
  echo "GOOGLE_DRIVE_FOLDER=FutPythonTrader-Semanal"
  echo "GOOGLE_DRIVE_FOLDER_ID=${GOOGLE_DRIVE_FOLDER_ID}"
} >> .env

if [ -n "${GOOGLE_OAUTH_REFRESH_TOKEN:-}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_ID:-}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_SECRET:-}" ]; then
  {
    echo "GOOGLE_OAUTH_CLIENT_ID=${GOOGLE_OAUTH_CLIENT_ID}"
    echo "GOOGLE_OAUTH_CLIENT_SECRET=${GOOGLE_OAUTH_CLIENT_SECRET}"
    echo "GOOGLE_OAUTH_REFRESH_TOKEN=${GOOGLE_OAUTH_REFRESH_TOKEN}"
  } >> .env
  echo "Drive auth: OAuth (GitHub Secrets)"
elif [ -n "${GOOGLE_SERVICE_ACCOUNT_JSON:-}" ]; then
  mkdir -p credentials
  echo "$GOOGLE_SERVICE_ACCOUNT_JSON" > credentials/google-service-account.json
  echo "GOOGLE_APPLICATION_CREDENTIALS=credentials/google-service-account.json" >> .env
  echo "Drive auth: Service Account (legado — upload pode falhar em SA nova)"
else
  echo "::error::Configure GOOGLE_OAUTH_* ou GOOGLE_SERVICE_ACCOUNT_JSON nos GitHub Secrets"
  exit 1
fi
