"""OAuth Drive → GitHub Secrets (sem salvar no .env local).

Uso:
  python scripts/setup_google_oauth_github.py --client-json "C:/Users/.../client_secret_....json"

Abre o navegador uma vez, grava refresh token + client_id/secret no GitHub via gh CLI.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCOPES = ["https://www.googleapis.com/auth/drive"]
DEFAULT_FOLDER_ID = "1Qs1vLDtyf1k61MdgqVcbvTtKr43KGeJn"
REPO = "fmaiaaa/FutPythonTraderBR"


def _gh_secret_set(name: str, value: str, repo: str) -> None:
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo, "--body", value],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"Erro ao definir secret {name}: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(proc.returncode)


def main() -> None:
    p = argparse.ArgumentParser(description="OAuth Drive → GitHub Secrets")
    p.add_argument("--client-json", required=True, help="Caminho do client_secret JSON do Google")
    p.add_argument("--folder-id", default=DEFAULT_FOLDER_ID, help="ID da pasta Drive")
    p.add_argument("--repo", default=REPO)
    args = p.parse_args()

    path = Path(args.client_json)
    if not path.exists():
        print(f"Arquivo nao encontrado: {path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    installed = data.get("installed") or data.get("web") or data
    client_id = installed["client_id"]
    client_secret = installed["client_secret"]

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Instale: pip install google-auth-oauthlib", file=sys.stderr)
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": installed.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": installed.get("token_uri", "https://oauth2.googleapis.com/token"),
            "redirect_uris": installed.get("redirect_uris", ["http://localhost"]),
        }
    }

    print("Abrindo navegador para autorizar Google Drive (uma vez)...")
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=0)
    if not creds.refresh_token:
        print("Sem refresh_token — revogue acesso em myaccount.google.com/permissions e tente de novo.", file=sys.stderr)
        sys.exit(1)

    repo = args.repo
    print(f"Gravando secrets em {repo} (via gh)...")
    _gh_secret_set("GOOGLE_OAUTH_CLIENT_ID", client_id, repo)
    _gh_secret_set("GOOGLE_OAUTH_CLIENT_SECRET", client_secret, repo)
    _gh_secret_set("GOOGLE_OAUTH_REFRESH_TOKEN", creds.refresh_token, repo)
    _gh_secret_set("GOOGLE_DRIVE_FOLDER_ID", args.folder_id, repo)

    print("\nOK — secrets no GitHub:")
    print("  GOOGLE_OAUTH_CLIENT_ID")
    print("  GOOGLE_OAUTH_CLIENT_SECRET")
    print("  GOOGLE_OAUTH_REFRESH_TOKEN")
    print("  GOOGLE_DRIVE_FOLDER_ID")
    print("\nNada foi salvo no .env local. Rode o workflow 'Upload Drive (manual)' para testar.")


if __name__ == "__main__":
    main()
