"""Upload de relatorios para Google Drive (Service Account)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..client import ENV_PATH, DATA

FOLDER_NAME = os.environ.get("GOOGLE_DRIVE_FOLDER", "FutPythonTrader-Semanal")


def _load_service_account_info() -> dict | None:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if cred_path and Path(cred_path).exists():
            return json.loads(Path(cred_path).read_text(encoding="utf-8"))
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                if line.startswith("GOOGLE_SERVICE_ACCOUNT_JSON="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val.startswith("{"):
                        return json.loads(val)
    else:
        if raw.startswith("{"):
            return json.loads(raw)
        p = Path(raw)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def upload_file(local_path: Path, folder_id: str | None = None) -> str | None:
    """Faz upload de um arquivo. Retorna file_id ou None."""
    info = _load_service_account_info()
    if not info:
        print("Google Drive: credenciais nao configuradas (GOOGLE_SERVICE_ACCOUNT_JSON)")
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("pip install google-api-python-client google-auth")
        return None

    scopes = ["https://www.googleapis.com/auth/drive.file"]
    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    target_folder = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID") or _ensure_folder(service)
    meta = {"name": local_path.name, "parents": [target_folder]}
    media = MediaFileUpload(str(local_path), resumable=True)
    created = service.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    link = created.get("webViewLink")
    print(f"Google Drive: upload OK -> {link}")
    return created.get("id")


def _ensure_folder(service) -> str:
    q = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(
        body={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        fields="id",
    ).execute()
    fid = folder["id"]
    print(f"Google Drive: pasta criada '{FOLDER_NAME}' ({fid})")
    (DATA / "google_drive_folder_id.txt").write_text(fid, encoding="utf-8")
    return fid
