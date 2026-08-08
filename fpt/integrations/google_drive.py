"""Upload de relatorios para Google Drive (Service Account).



IMPORTANTE: Service Accounts nao tem quota de armazenamento propria.

Compartilhe a pasta `FutPythonTrader-Semanal` com o e-mail da SA como Editor

e defina GOOGLE_DRIVE_FOLDER_ID com o ID dessa pasta.

"""

from __future__ import annotations



import json

import os

from dataclasses import dataclass

from pathlib import Path



from ..client import ENV_PATH, DATA



FOLDER_NAME = os.environ.get("GOOGLE_DRIVE_FOLDER", "FutPythonTrader-Semanal")





@dataclass

class UploadResult:

    file_id: str

    name: str

    web_view_link: str | None = None





def _load_env_var(name: str) -> str:

    val = os.environ.get(name, "")

    if val or not ENV_PATH.exists():

        return val

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():

        line = line.strip()

        if line.startswith(f"{name}="):

            return line.split("=", 1)[1].strip().strip('"').strip("'")

    return ""





def _load_service_account_info() -> dict | None:

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "") or _load_env_var("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not raw:

        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "") or _load_env_var(

            "GOOGLE_APPLICATION_CREDENTIALS"

        )

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





def _build_drive_service():

    info = _load_service_account_info()

    if not info:

        return None, None

    try:

        from google.oauth2 import service_account

        from googleapiclient.discovery import build

    except ImportError:

        print("pip install google-api-python-client google-auth")

        return None, None

    scopes = ["https://www.googleapis.com/auth/drive.file"]

    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)

    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    return service, info





def _find_or_create_folder(service, parent_id: str, name: str) -> str:

    q = (

        f"name='{name}' and '{parent_id}' in parents "

        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"

    )

    res = service.files().list(

        q=q, fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,

    ).execute()

    files = res.get("files", [])

    if files:

        return files[0]["id"]

    folder = service.files().create(

        body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},

        fields="id",

        supportsAllDrives=True,

    ).execute()

    return folder["id"]





def resolve_history_folder(service, root_folder_id: str, saturday_iso: str) -> str:

    """Cria/busca YYYY-MM/YYYY-MM-DD dentro da pasta raiz."""

    month = saturday_iso[:7]

    day = saturday_iso[:10]

    month_id = _find_or_create_folder(service, root_folder_id, month)

    return _find_or_create_folder(service, month_id, day)





def get_root_folder_id(service) -> str | None:

    fid = (

        os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

        or _load_env_var("GOOGLE_DRIVE_FOLDER_ID")

    )

    if fid:

        return fid

    return _ensure_folder(service)


def verify_drive_folder_access() -> dict:
    """Testa se a SA consegue escrever na pasta configurada."""
    service, info = _build_drive_service()
    if not service or not info:
        return {"ok": False, "error": "credenciais_ausentes", "service_account": info.get("client_email") if info else None}

    sa_email = info.get("client_email", "")
    folder_id = get_root_folder_id(service)
    if not folder_id:
        return {"ok": False, "error": "folder_id_ausente", "service_account": sa_email}

    out = {"ok": False, "folder_id": folder_id, "service_account": sa_email}
    try:
        meta = service.files().get(
            fileId=folder_id,
            fields="id,name,capabilities,mimeType",
            supportsAllDrives=True,
        ).execute()
        caps = meta.get("capabilities") or {}
        out["folder_name"] = meta.get("name")
        out["can_add_children"] = caps.get("canAddChildren", False)
        out["can_edit"] = caps.get("canEdit", False)
        if not caps.get("canAddChildren") and not caps.get("canEdit"):
            out["error"] = "sem_permissao_editor"
            return out
        out["ok"] = True
        return out
    except Exception as ex:
        err = str(ex)
        out["error"] = err[:300]
        if "404" in err:
            out["hint"] = "Pasta não encontrada — confira GOOGLE_DRIVE_FOLDER_ID"
        elif "403" in err:
            out["hint"] = f"Compartilhe a pasta com {sa_email} como Editor"
        return out





def upload_file(

    local_path: Path,

    folder_id: str | None = None,

    history_date: str | None = None,

) -> str | None:

    """Faz upload. Retorna file_id ou None."""

    result = upload_file_detailed(local_path, folder_id, history_date)

    return result.file_id if result else None





def upload_file_detailed(

    local_path: Path,

    folder_id: str | None = None,

    history_date: str | None = None,

) -> UploadResult | None:

    """Upload com link webViewLink."""

    service, info = _build_drive_service()

    if not service or not info:

        print("Google Drive: credenciais nao configuradas (GOOGLE_SERVICE_ACCOUNT_JSON)")

        return None



    from googleapiclient.http import MediaFileUpload



    root_folder = folder_id or get_root_folder_id(service)

    if not root_folder:

        print("Google Drive: pasta raiz nao encontrada — defina GOOGLE_DRIVE_FOLDER_ID")

        return None



    target_folder = root_folder

    if history_date:

        target_folder = resolve_history_folder(service, root_folder, history_date)

        print(f"Google Drive: pasta historico {history_date[:7]}/{history_date[:10]}")



    meta = {"name": local_path.name, "parents": [target_folder]}

    media = MediaFileUpload(str(local_path), resumable=True)

    try:

        created = service.files().create(

            body=meta,

            media_body=media,

            fields="id,webViewLink,webContentLink",

            supportsAllDrives=True,

        ).execute()

        link = created.get("webViewLink")

        print(f"Google Drive: upload OK -> {link}")

        return UploadResult(

            file_id=created["id"],

            name=local_path.name,

            web_view_link=link,

        )

    except Exception as ex:

        err = str(ex)

        email = info.get("client_email", "service-account")

        if "storageQuotaExceeded" in err or "403" in err:

            print(

                f"Google Drive: falha 403 — compartilhe a pasta FutPythonTrader-Semanal "

                f"com {email} como Editor e use GOOGLE_DRIVE_FOLDER_ID=<id_da_pasta>"

            )

        else:

            print(f"Google Drive: erro — {ex}")

        return None





def upload_weekend_folder(report_dir: Path, saturday_iso: str) -> dict:

    """

    Sobe todos PDF/CSV/TXT de um fim de semana.

    Salva drive_links.json no report_dir para o Streamlit.

    """

    report_dir = Path(report_dir)

    if not report_dir.exists():

        print(f"Google Drive: pasta inexistente {report_dir}")

        return {"uploaded": [], "errors": ["dir_not_found"]}



    patterns = ("*.pdf", "*.csv", "*.txt", "*.json")

    files: list[Path] = []

    for pat in patterns:

        files.extend(sorted(report_dir.glob(pat)))

    # evita re-upload do proprio drive_links

    files = [f for f in files if f.name != "drive_links.json"]



    uploaded = []

    errors = []

    for f in files:

        res = upload_file_detailed(f, history_date=saturday_iso)

        if res:

            uploaded.append({

                "name": res.name,

                "file_id": res.file_id,

                "web_view_link": res.web_view_link,

                "local_path": str(f),

            })

        else:

            errors.append(f.name)



    manifest = {

        "saturday": saturday_iso,

        "uploaded": uploaded,

        "errors": errors,

        "service_account_hint": "Compartilhe pasta com SA como Editor + GOOGLE_DRIVE_FOLDER_ID",

    }

    manifest_path = report_dir / "drive_links.json"

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Google Drive: {len(uploaded)}/{len(files)} arquivos | manifest: {manifest_path}")

    return manifest





def _ensure_folder(service) -> str | None:

    q = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"

    res = service.files().list(

        q=q, fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,

    ).execute()

    files = res.get("files", [])

    if files:

        return files[0]["id"]

    try:

        folder = service.files().create(

            body={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},

            fields="id",

            supportsAllDrives=True,

        ).execute()

        fid = folder["id"]

        print(f"Google Drive: pasta criada '{FOLDER_NAME}' ({fid})")

        print("  AVISO: SA nao tem quota — compartilhe pasta existente e use GOOGLE_DRIVE_FOLDER_ID")

        (DATA / "google_drive_folder_id.txt").write_text(fid, encoding="utf-8")

        return fid

    except Exception as ex:

        print(f"Google Drive: nao foi possivel criar pasta — {ex}")

        return None


