"""Bootstrap Streamlit Cloud — secrets, certificados Betfair, dados e modelos."""
from __future__ import annotations

import os
import zipfile
from io import BytesIO
from pathlib import Path

import requests

from ..client import DATA, ROOT

CERT_DIR = ROOT / "certs"
MODEL_DIR = DATA / "models"
MERGED_PARQUET = DATA / "merged" / "brazil_male_all.parquet"

_ENV_KEYS = (
    "FPT_API_KEY",
    "BETFAIR_USERNAME",
    "BETFAIR_PASSWORD",
    "BETFAIR_APP_KEY",
    "BETFAIR_CERT_PATH",
    "BETFAIR_ENABLED",
    "GOOGLE_DRIVE_FOLDER_ID",
)


def _secrets_dict() -> dict:
    try:
        import streamlit as st

        if hasattr(st, "secrets") and len(st.secrets):
            return dict(st.secrets)
    except Exception:
        pass
    return {}


def apply_streamlit_secrets() -> None:
    """Copia st.secrets → os.environ e grava certificados Betfair."""
    secrets = _secrets_dict()
    if not secrets:
        return

    for key in _ENV_KEYS:
        if key in secrets:
            os.environ[key] = str(secrets[key])

    for section in ("betfair", "execution", "google"):
        block = secrets.get(section)
        if not isinstance(block, dict):
            continue
        prefix = section.upper()
        for k, v in block.items():
            os.environ[f"{prefix}_{k.upper()}"] = str(v)
            if section == "betfair":
                os.environ[f"BETFAIR_{k.upper()}"] = str(v)
            if section == "google":
                oauth_map = {
                    "OAUTH_CLIENT_ID": "GOOGLE_OAUTH_CLIENT_ID",
                    "OAUTH_CLIENT_SECRET": "GOOGLE_OAUTH_CLIENT_SECRET",
                    "OAUTH_REFRESH_TOKEN": "GOOGLE_OAUTH_REFRESH_TOKEN",
                    "DRIVE_FOLDER_ID": "GOOGLE_DRIVE_FOLDER_ID",
                }
                if k.upper() in oauth_map:
                    os.environ[oauth_map[k.upper()]] = str(v)

    # Certificados PEM inline (Streamlit Cloud não tem pasta certs/)
    cert_pem = secrets.get("BETFAIR_CERT_PEM") or secrets.get("betfair", {}).get("cert_pem", "")
    key_pem = secrets.get("BETFAIR_KEY_PEM") or secrets.get("betfair", {}).get("key_pem", "")
    if cert_pem and key_pem:
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        (CERT_DIR / "client-2048.crt").write_text(str(cert_pem).strip() + "\n", encoding="utf-8")
        (CERT_DIR / "client-2048.key").write_text(str(key_pem).strip() + "\n", encoding="utf-8")
        os.environ["BETFAIR_CERT_PATH"] = str(CERT_DIR)
        os.environ["BETFAIR_ENABLED"] = "true"

    if secrets.get("FPT_API_KEY"):
        os.environ.setdefault("BETFAIR_ENABLED", "true")

    os.environ["FPT_STREAMLIT_CLOUD"] = "1"


def _download_models_zip(url: str) -> bool:
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            zf.extractall(MODEL_DIR)
        return (MODEL_DIR / "model_outcome.joblib").exists()
    except Exception:
        return False


def _download_models_from_drive(file_id: str) -> bool:
    try:
        from googleapiclient.http import MediaIoBaseDownload
        from ..integrations.google_drive import _build_drive_service

        service, _ = _build_drive_service()
        if not service:
            return False
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        buf = BytesIO()
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            zf.extractall(MODEL_DIR)
        return (MODEL_DIR / "model_outcome.joblib").exists()
    except Exception:
        return False


def ensure_data_and_models(progress=None) -> tuple[bool, str]:
    """
    Garante merged + modelos. Retorna (ok, mensagem).
    progress: callable(str) opcional para UI.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    has_data = MERGED_PARQUET.exists() or (DATA / "merged" / "brazil_male_all.csv").exists()
    has_models = (MODEL_DIR / "model_outcome.joblib").exists()

    if has_data and has_models:
        return True, "Dados e modelos prontos."

    secrets = _secrets_dict()
    models_url = secrets.get("MODELS_ZIP_URL") or secrets.get("models_zip_url", "")
    google_block = secrets.get("google")
    models_drive_id = ""
    if isinstance(google_block, dict):
        models_drive_id = str(google_block.get("models_drive_file_id", "") or "")
    models_drive_id = models_drive_id or str(secrets.get("MODELS_DRIVE_FILE_ID") or secrets.get("models_drive_file_id") or "")

    if not has_models and models_drive_id:
        log("Baixando modelos do Google Drive...")
        if _download_models_from_drive(str(models_drive_id)):
            has_models = True

    if not has_models and models_url:
        log("Baixando modelos pré-treinados...")
        if _download_models_zip(str(models_url)):
            has_models = True

    if not has_data:
        log("Baixando dados FPT (watchlist)...")
        try:
            from ..downloader import download_incremental_weekly, merge_all

            download_incremental_weekly()
            merge_all()
            has_data = MERGED_PARQUET.exists()
        except Exception as ex:
            return False, f"Falha ao baixar dados: {ex}"

    if not has_models and has_data:
        log("Treinando modelos (primeira execução, ~5–10 min)...")
        try:
            from ..models.train import train_models
            from ..pipeline import load_merged

            train_models(load_merged())
            has_models = (MODEL_DIR / "model_outcome.joblib").exists()
        except Exception as ex:
            return False, f"Falha no treino: {ex}"

    if has_data and has_models:
        return True, "Ambiente pronto."
    return False, "Dados ou modelos ausentes — verifique FPT_API_KEY nos Secrets."


def cloud_bootstrap() -> None:
    """Entry point: secrets + dados. Chamar antes do live_app."""
    apply_streamlit_secrets()

    try:
        import streamlit as st

        if not MERGED_PARQUET.exists() or not (MODEL_DIR / "model_outcome.joblib").exists():
            with st.status("Inicializando FutPythonTrader Live...", expanded=True) as status:
                ok, msg = ensure_data_and_models(progress=status.write)
                if ok:
                    status.update(label="Pronto", state="complete")
                else:
                    status.update(label="Erro na inicialização", state="error")
                    st.error(msg)
                    st.info(
                        "Configure **FPT_API_KEY** nos Secrets do Streamlit Cloud. "
                        "Opcional: **MODELS_ZIP_URL** com zip dos .joblib para pular o treino."
                    )
                    st.stop()
    except ImportError:
        ensure_data_and_models()
