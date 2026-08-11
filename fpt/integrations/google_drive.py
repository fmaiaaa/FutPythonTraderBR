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
from ..storage import persist_data_locally



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


DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _load_oauth_credentials():
    """OAuth com refresh token — recomendado para Gmail pessoal (SA nova nao tem quota)."""
    refresh = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", "") or _load_env_var("GOOGLE_OAUTH_REFRESH_TOKEN")
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "") or _load_env_var("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "") or _load_env_var("GOOGLE_OAUTH_CLIENT_SECRET")
    if not (refresh and client_id and client_secret):
        return None
    try:
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None
    return Credentials(
        token=None,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=DRIVE_SCOPES,
    )


def _build_drive_service():
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("pip install google-api-python-client google-auth")
        return None, None

    oauth_creds = _load_oauth_credentials()
    if oauth_creds is not None:
        service = build("drive", "v3", credentials=oauth_creds, cache_discovery=False)
        return service, {"auth": "oauth", "client_email": "oauth-user"}

    info = _load_service_account_info()
    if not info:
        return None, None

    try:
        from google.oauth2 import service_account
    except ImportError:
        print("pip install google-api-python-client google-auth")
        return None, None

    creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
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


def _find_folder(service, parent_id: str, name: str) -> str | None:
    q = (
        f"name='{name}' and '{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = service.files().list(
        q=q, fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def get_history_folder_id(service, root_folder_id: str, saturday_iso: str) -> str | None:
    """Busca pasta YYYY-MM/YYYY-MM-DD sem criar."""
    month_id = _find_folder(service, root_folder_id, saturday_iso[:7])
    if not month_id:
        return None
    return _find_folder(service, month_id, saturday_iso[:10])


def list_folder_files(service, folder_id: str, *, pdf_only: bool = False) -> list[dict]:
    q = f"'{folder_id}' in parents and trashed=false"
    if pdf_only:
        q += " and mimeType='application/pdf'"
    res = service.files().list(
        q=q,
        fields="files(id,name,mimeType,webViewLink,webContentLink,modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        orderBy="name",
    ).execute()
    return [
        {
            "name": f.get("name", ""),
            "file_id": f.get("id", ""),
            "web_view_link": f.get("webViewLink"),
            "mime_type": f.get("mimeType"),
            "modified_time": f.get("modifiedTime"),
        }
        for f in res.get("files", [])
    ]


def list_weekend_drive_reports(saturday_iso: str) -> list[dict]:
    """Lista PDFs do fim de semana no Google Drive (fonte principal fora do CI)."""
    service, _ = _build_drive_service()
    if not service:
        return []
    root = get_root_folder_id(service)
    if not root:
        return []
    day_id = get_history_folder_id(service, root, saturday_iso)
    if not day_id:
        return []
    return [f for f in list_folder_files(service, day_id, pdf_only=True) if f.get("name", "").endswith(".pdf")]


def upload_models_bundle(models_dir: Path | None = None) -> dict | None:
    """Envia zip dos modelos para Drive/models/ (GitHub Actions → Streamlit Cloud)."""
    import zipfile
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload

    models_dir = models_dir or (DATA / "models")
    joblib_files = list(models_dir.glob("*.joblib"))
    scalping_dir = models_dir / "scalping"
    if scalping_dir.is_dir():
        joblib_files.extend(scalping_dir.glob("*.joblib"))
    meta = models_dir / "meta.json"
    scalp_meta = scalping_dir / "meta.json" if scalping_dir.is_dir() else None
    if not joblib_files:
        return None

    service, _ = _build_drive_service()
    if not service:
        return None
    root = get_root_folder_id(service)
    if not root:
        return None

    models_folder = _find_or_create_folder(service, root, "models")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in joblib_files:
            arc = p.relative_to(models_dir).as_posix()
            zf.write(p, arc)
        if meta.exists():
            zf.write(meta, meta.name)
        if scalp_meta and scalp_meta.exists():
            zf.write(scalp_meta, f"scalping/{scalp_meta.name}")
    buf.seek(0)

    media = MediaIoBaseUpload(buf, mimetype="application/zip", resumable=False)
    for fname in ("fpt-models-latest.zip",):
        q = f"name='{fname}' and '{models_folder}' in parents and trashed=false"
        existing = service.files().list(q=q, fields="files(id)", supportsAllDrives=True).execute().get("files", [])
        body = {"name": fname, "parents": [models_folder]}
        if existing:
            updated = service.files().update(
                fileId=existing[0]["id"], media_body=media, fields="id,webViewLink", supportsAllDrives=True,
            ).execute()
            return {"file_id": updated["id"], "web_view_link": updated.get("webViewLink"), "name": fname}
        created = service.files().create(
            body=body, media_body=media, fields="id,webViewLink", supportsAllDrives=True,
        ).execute()
        return {"file_id": created["id"], "web_view_link": created.get("webViewLink"), "name": fname}
    return None


MERGED_ZIP_NAME = "fpt-merged-latest.zip"
MODELS_ZIP_NAME = "fpt-models-latest.zip"
DRIVE_ASSETS_FOLDER = "models"


def _find_folder_id(service, parent_id: str, name: str) -> str | None:
    q = (
        f"name='{name}' and '{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = service.files().list(
        q=q, fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def find_drive_asset(filename: str, subfolder: str = DRIVE_ASSETS_FOLDER) -> dict | None:
    """Localiza zip de modelos/dados no Drive (OAuth ou SA)."""
    service, _ = _build_drive_service()
    if not service:
        return None
    root = get_root_folder_id(service)
    if not root:
        return None
    folder_id = _find_folder_id(service, root, subfolder)
    if not folder_id:
        return None
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    res = service.files().list(
        q=q,
        fields="files(id,name,webViewLink,modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if not files:
        return None
    f = files[0]
    return {
        "file_id": f["id"],
        "name": f.get("name", filename),
        "web_view_link": f.get("webViewLink"),
    }


def _download_drive_file_bytes(file_id: str) -> bytes | None:
    try:
        from googleapiclient.http import MediaIoBaseDownload
        from io import BytesIO

        service, _ = _build_drive_service()
        if not service:
            return None
        buf = BytesIO()
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()
    except Exception:
        return None


def download_drive_zip(file_id: str, extract_dir: Path) -> bool:
    """Baixa zip do Drive e extrai para extract_dir."""
    import zipfile
    from io import BytesIO

    raw = _download_drive_file_bytes(file_id)
    if not raw:
        return False
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        zf.extractall(extract_dir)
    return True


def upload_merged_bundle(merged_dir: Path | None = None) -> dict | None:
    """Envia zip merged (global + BR) para Drive/models/ — Streamlit Cloud."""
    import zipfile
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload

    merged_dir = merged_dir or (DATA / "merged")
    candidates = [
        merged_dir / "global_all.parquet",
        merged_dir / "global_all.csv",
        merged_dir / "brazil_male_all.parquet",
        merged_dir / "brazil_male_all.csv",
    ]
    files = [p for p in candidates if p.exists()]
    if not files:
        return None

    service, _ = _build_drive_service()
    if not service:
        return None
    root = get_root_folder_id(service)
    if not root:
        return None

    assets_folder = _find_or_create_folder(service, root, DRIVE_ASSETS_FOLDER)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.name)
    buf.seek(0)

    media = MediaIoBaseUpload(buf, mimetype="application/zip", resumable=False)
    q = f"name='{MERGED_ZIP_NAME}' and '{assets_folder}' in parents and trashed=false"
    existing = service.files().list(q=q, fields="files(id)", supportsAllDrives=True).execute().get("files", [])
    body = {"name": MERGED_ZIP_NAME, "parents": [assets_folder]}
    if existing:
        updated = service.files().update(
            fileId=existing[0]["id"], media_body=media, fields="id,webViewLink", supportsAllDrives=True,
        ).execute()
        return {"file_id": updated["id"], "web_view_link": updated.get("webViewLink"), "name": MERGED_ZIP_NAME}
    created = service.files().create(
        body=body, media_body=media, fields="id,webViewLink", supportsAllDrives=True,
    ).execute()
    return {"file_id": created["id"], "web_view_link": created.get("webViewLink"), "name": MERGED_ZIP_NAME}


LIVE_COLLECTION_ZIP = "fpt-live-collection-latest.zip"
LIVE_SNAPSHOT_NAME = "fpt-live-snapshot-latest.json"
LIVE_PULSE_NAME = "fpt-live-pulse-latest.json"


def _upload_json_asset(name: str, payload: dict) -> dict | None:
    from googleapiclient.http import MediaIoBaseUpload
    from io import BytesIO

    service, _ = _build_drive_service()
    if not service:
        return None
    root = get_root_folder_id(service)
    if not root:
        return None
    assets_folder = _find_or_create_folder(service, root, DRIVE_ASSETS_FOLDER)
    raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    media = MediaIoBaseUpload(BytesIO(raw), mimetype="application/json", resumable=False)
    q = f"name='{name}' and '{assets_folder}' in parents and trashed=false"
    existing = service.files().list(q=q, fields="files(id)", supportsAllDrives=True).execute().get("files", [])
    body = {"name": name, "parents": [assets_folder]}
    if existing:
        updated = service.files().update(
            fileId=existing[0]["id"], media_body=media, fields="id,webViewLink", supportsAllDrives=True,
        ).execute()
        return {"file_id": updated["id"], "web_view_link": updated.get("webViewLink"), "name": name}
    created = service.files().create(
        body=body, media_body=media, fields="id,webViewLink", supportsAllDrives=True,
    ).execute()
    return {"file_id": created["id"], "web_view_link": created.get("webViewLink"), "name": name}


def upload_live_snapshot_bundle(snapshot_path: Path | None = None) -> dict | None:
    """Publica snapshot live do dia no Drive (consulta 24h / Streamlit Cloud)."""
    from datetime import date

    today = date.today().isoformat()
    path = snapshot_path or (DATA / "live" / today[:7] / f"snapshot_{today}.json")
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    payload["cloud_uploaded"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    result = _upload_json_asset(LIVE_SNAPSHOT_NAME, payload)
    if result:
        from ..live.cloud_pulse import read_cloud_pulse

        pulse = read_cloud_pulse()
        if pulse:
            _upload_json_asset(LIVE_PULSE_NAME, pulse)
    return result


def download_live_snapshot_from_drive() -> bool:
    """Baixa snapshot live mais recente do Drive para data/live/."""
    from datetime import date

    asset = find_drive_asset(LIVE_SNAPSHOT_NAME)
    if not asset:
        return False
    raw = _download_drive_file_bytes(asset["file_id"])
    if not raw:
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    today = date.today().isoformat()
    out_dir = DATA / "live" / today[:7]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"snapshot_{today}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def upload_live_collection_bundle(collection_dir: Path | None = None) -> dict | None:
    """Zip data/live_collection/ → Drive/models/fpt-live-collection-latest.zip"""
    import zipfile
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload

    collection_dir = collection_dir or (DATA / "live_collection")
    if not collection_dir.exists():
        return None

    files: list[Path] = []
    for pat in ("**/*.csv", "**/*.json", "**/*.parquet", "**/*.jsonl"):
        files.extend(collection_dir.glob(pat))
    if not files:
        return None

    service, _ = _build_drive_service()
    if not service:
        return None
    root = get_root_folder_id(service)
    if not root:
        return None

    assets_folder = _find_or_create_folder(service, root, DRIVE_ASSETS_FOLDER)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            arc = p.relative_to(collection_dir).as_posix()
            zf.write(p, arc)
    buf.seek(0)

    media = MediaIoBaseUpload(buf, mimetype="application/zip", resumable=False)
    q = f"name='{LIVE_COLLECTION_ZIP}' and '{assets_folder}' in parents and trashed=false"
    existing = service.files().list(q=q, fields="files(id)", supportsAllDrives=True).execute().get("files", [])
    body = {"name": LIVE_COLLECTION_ZIP, "parents": [assets_folder]}
    if existing:
        updated = service.files().update(
            fileId=existing[0]["id"], media_body=media, fields="id,webViewLink", supportsAllDrives=True,
        ).execute()
        return {"file_id": updated["id"], "web_view_link": updated.get("webViewLink"), "name": LIVE_COLLECTION_ZIP}
    created = service.files().create(
        body=body, media_body=media, fields="id,webViewLink", supportsAllDrives=True,
    ).execute()
    return {"file_id": created["id"], "web_view_link": created.get("webViewLink"), "name": LIVE_COLLECTION_ZIP}


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



    media = MediaFileUpload(str(local_path), resumable=True)

    try:
        q = (
            f"name='{local_path.name}' and '{target_folder}' in parents "
            f"and trashed=false"
        )
        existing = service.files().list(
            q=q, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute().get("files", [])

        if existing:
            updated = service.files().update(
                fileId=existing[0]["id"],
                media_body=media,
                fields="id,webViewLink,webContentLink",
                supportsAllDrives=True,
            ).execute()
            link = updated.get("webViewLink")
            print(f"Google Drive: atualizado -> {link}")
            return UploadResult(
                file_id=updated["id"],
                name=local_path.name,
                web_view_link=link,
            )

        meta = {"name": local_path.name, "parents": [target_folder]}

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

        if "storageQuotaExceeded" in err or "do not have storage quota" in err.lower():
            print(
                "Google Drive: falha 403 — Service Accounts criadas apos abr/2025 nao tem quota. "
                "Use OAuth (GOOGLE_OAUTH_*) ou Google Workspace Shared Drive. "
                "Veja docs/GOOGLE_DRIVE_SETUP.md"
            )
        elif "403" in err:
            print(
                f"Google Drive: falha 403 — compartilhe a pasta com {email} como Editor "
                "ou configure OAuth (GOOGLE_OAUTH_REFRESH_TOKEN)."
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

        if persist_data_locally():
            (DATA / "google_drive_folder_id.txt").write_text(fid, encoding="utf-8")

        return fid

    except Exception as ex:

        print(f"Google Drive: nao foi possivel criar pasta — {ex}")

        return None


