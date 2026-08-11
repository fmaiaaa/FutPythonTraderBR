"""Grava perfil escolhido no menu .bat."""
from __future__ import annotations

import sys

from fpt.live.runtime_profile import PROFILES, profile_summary, save_profile


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python scripts/set_fpt_profile.py robust|watchlist|all_leagues")
        return 1
    name = sys.argv[1].strip().lower()
    if name not in PROFILES:
        print(f"Perfil invalido: {name}")
        print("Validos:", ", ".join(PROFILES))
        return 1
    path = save_profile(name)
    print(f"Perfil: {profile_summary(name)}")
    print(f"Salvo: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
