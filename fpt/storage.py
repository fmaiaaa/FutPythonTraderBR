"""Política de persistência — dados só no GitHub Actions / Streamlit Cloud."""
from __future__ import annotations

import os


def persist_data_locally() -> bool:
    """True apenas em CI (ephemeral) ou Streamlit Cloud; False no PC do usuário."""
    if os.environ.get("FPT_PERSIST_LOCAL", "").lower() in ("1", "true", "yes"):
        return True
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("FPT_STREAMLIT_CLOUD"))


def is_github_actions() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS"))
