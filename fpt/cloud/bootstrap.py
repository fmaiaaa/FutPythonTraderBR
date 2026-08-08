"""Bootstrap Streamlit Cloud — secrets, certificados Betfair, dados e modelos."""
from __future__ import annotations

import os
import zipfile
from io import BytesIO
from pathlib import Path

import requests

from ..client import DATA, ROOT, load_api_key
from ..integrations.google_drive import (
    MERGED_ZIP_NAME,
    MODELS_ZIP_NAME,
    download_drive_zip,
    find_drive_asset,
)

CERT_DIR = ROOT / "certs"
MODEL_DIR = DATA / "models"
MERGED_DIR = DATA / "merged"
MERGED_PARQUET = MERGED_DIR / "brazil_male_all.parquet"
GLOBAL_PARQUET = MERGED_DIR / "global_all.parquet"

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


def _has_merged_data() -> bool:
    paths = (
        MERGED_PARQUET,
        MERGED_DIR / "brazil_male_all.csv",
        GLOBAL_PARQUET,
        MERGED_DIR / "global_all.csv",
    )
    return any(p.exists() for p in paths)


def _has_models() -> bool:
    return (MODEL_DIR / "model_outcome.joblib").exists()


def _drive_oauth_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        and os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    )


def _fpt_api_key_ok() -> tuple[bool, str]:
    try:
        load_api_key()
        return True, ""
    except ValueError as ex:
        return False, str(ex)


def _download_models_zip(url: str) -> bool:
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(resp.content)) as zf:
            zf.extractall(MODEL_DIR)
        return _has_models()
    except Exception:
        return False


def _resolve_models_drive_id(secrets: dict) -> str:
    google_block = secrets.get("google")
    explicit = ""
    if isinstance(google_block, dict):
        explicit = str(google_block.get("models_drive_file_id", "") or "")
    explicit = explicit or str(secrets.get("MODELS_DRIVE_FILE_ID") or secrets.get("models_drive_file_id") or "")
    if explicit:
        return explicit
    asset = find_drive_asset(MODELS_ZIP_NAME)
    return asset["file_id"] if asset else ""


def _try_download_merged_from_drive() -> bool:
    asset = find_drive_asset(MERGED_ZIP_NAME)
    if not asset:
        return False
    return download_drive_zip(asset["file_id"], MERGED_DIR)


def _try_download_models_from_drive(file_id: str) -> bool:
    if not file_id:
        return False
    ok = download_drive_zip(file_id, MODEL_DIR)
    return ok and _has_models()


def _read_download_errors() -> str:
    err_path = DATA / "download_errors.txt"
    if err_path.exists():
        text = err_path.read_text(encoding="utf-8").strip()
        if text:
            return text[:800]
    return ""


def ensure_data_and_models(progress=None) -> tuple[bool, str]:
    """
    Garante merged + modelos. Retorna (ok, mensagem).
    Ordem: Drive (merged + modelos) → FPT API → treino local.
    """
    def log(msg: str):
        if progress:
            progress(msg)

    if _has_merged_data() and _has_models():
        return True, "Dados e modelos prontos."

    secrets = _secrets_dict()

    if not _has_merged_data() and _drive_oauth_configured():
        log("Baixando dados merged do Google Drive...")
        if _try_download_merged_from_drive():
            log("Dados merged OK.")

    if not _has_models():
        models_url = secrets.get("MODELS_ZIP_URL") or secrets.get("models_zip_url", "")
        models_drive_id = _resolve_models_drive_id(secrets)
        if models_drive_id:
            log("Baixando modelos do Google Drive...")
            if _try_download_models_from_drive(models_drive_id):
                log("Modelos OK.")
        elif models_url:
            log("Baixando modelos pré-treinados (URL)...")
            if _download_models_zip(str(models_url)):
                log("Modelos OK.")

    if not _has_merged_data():
        key_ok, key_err = _fpt_api_key_ok()
        if not key_ok:
            return False, (
                f"{key_err} "
                "Ou configure [google].oauth_* + drive_folder_id e rode o workflow semanal no GitHub "
                f"para publicar {MERGED_ZIP_NAME} no Drive."
            )
        log("Baixando dados FPT (watchlist)...")
        try:
            from ..downloader import download_incremental_weekly, merge_all

            stats = download_incremental_weekly()
            if not stats:
                err_detail = _read_download_errors()
                hint = err_detail or "Nenhuma liga baixada — verifique assinatura/API key FPT."
                return False, f"Falha ao baixar dados FPT: {hint}"
            merge_all()
            if not _has_merged_data():
                return False, "Merge concluído mas arquivos merged ausentes."
        except Exception as ex:
            err_detail = _read_download_errors()
            msg = f"Falha ao baixar dados: {ex}"
            if err_detail:
                msg += f" | Detalhes: {err_detail[:400]}"
            return False, msg

    if not _has_models() and _has_merged_data():
        log("Treinando modelos (primeira execução, ~5–10 min)...")
        try:
            from ..models.train import train_models
            from ..pipeline import load_merged

            train_models(load_merged())
        except Exception as ex:
            return False, f"Falha no treino: {ex}"

    if _has_merged_data() and _has_models():
        return True, "Ambiente pronto."

    missing = []
    if not _has_merged_data():
        missing.append("dados merged")
    if not _has_models():
        missing.append("modelos")
    return False, (
        f"Faltam: {', '.join(missing)}. "
        "Configure FPT_API_KEY nos Secrets OU google OAuth + drive_folder_id "
        "(workflow Relatorio Semanal Sabado no GitHub)."
    )


def cloud_bootstrap() -> None:
    """Entry point: secrets + dados. Chamar antes do live_app."""
    apply_streamlit_secrets()

    try:
        import streamlit as st

        if not _has_merged_data() or not _has_models():
            with st.status("Inicializando FutPythonTrader Live...", expanded=True) as status:
                ok, msg = ensure_data_and_models(progress=status.write)
                if ok:
                    status.update(label="Pronto", state="complete")
                else:
                    status.update(label="Erro na inicialização", state="error")
                    st.error(msg)
                    st.info(
                        "**Opção A:** `FPT_API_KEY` nos Secrets (dashboard FPT).\n\n"
                        "**Opção B (recomendado):** `[google]` com oauth_client_id, "
                        "oauth_client_secret, oauth_refresh_token, drive_folder_id — "
                        "depois rode **Relatorio Semanal Sabado** no GitHub Actions "
                        f"(publica {MERGED_ZIP_NAME} e {MODELS_ZIP_NAME} no Drive)."
                    )
                    with st.expander("Diagnóstico"):
                        key_ok, key_err = _fpt_api_key_ok()
                        st.write(f"FPT_API_KEY: {'OK' if key_ok else key_err}")
                        st.write(f"Google OAuth Drive: {'OK' if _drive_oauth_configured() else 'não configurado'}")
                    st.stop()
    except ImportError:
        ensure_data_and_models()
