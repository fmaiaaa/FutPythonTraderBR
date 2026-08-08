"""Gera refresh token OAuth para upload no Drive (Gmail pessoal).

1. Google Cloud Console → APIs → OAuth client ID (Desktop app)
2. Baixe client_secret JSON ou copie client_id + client_secret para .env
3. Rode: python scripts/get_google_oauth_token.py
4. Cole GOOGLE_OAUTH_REFRESH_TOKEN no .env e GitHub Secrets
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCOPES = ["https://www.googleapis.com/auth/drive"]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Instale: pip install google-auth-oauthlib")
        sys.exit(1)

    client_id = input("GOOGLE_OAUTH_CLIENT_ID: ").strip()
    client_secret = input("GOOGLE_OAUTH_CLIENT_SECRET: ").strip()
    if not client_id or not client_secret:
        print("client_id e client_secret obrigatorios.")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n=== Cole no .env e GitHub Secrets ===")
    print(f"GOOGLE_OAUTH_CLIENT_ID={client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
