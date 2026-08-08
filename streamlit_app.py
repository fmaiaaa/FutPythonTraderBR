"""
FutPythonTrader — Operação Live (Streamlit Cloud + local)

Deploy Streamlit Cloud:
  Main file: streamlit_app.py
  Secrets:   ver .streamlit/secrets.toml.example
"""
from fpt.cloud.bootstrap import cloud_bootstrap

cloud_bootstrap()

from live_app import main

main()
