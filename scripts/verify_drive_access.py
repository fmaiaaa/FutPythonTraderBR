"""Verifica permissão da Service Account na pasta Google Drive."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpt.integrations.google_drive import verify_drive_folder_access


def main():
    result = verify_drive_folder_access()
    print("=== Verificação Google Drive ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    if not result.get("ok"):
        print("\nAÇÃO NECESSÁRIA:")
        print(f"  1. Abra a pasta no Drive (ID: {result.get('folder_id', '?')})")
        print(f"  2. Compartilhe com {result.get('service_account', '?')} como EDITOR")
        print("  3. Confirme GOOGLE_DRIVE_FOLDER_ID no .env e GitHub Secrets")
        sys.exit(1)
    print("\nOK — upload permitido.")


if __name__ == "__main__":
    main()
