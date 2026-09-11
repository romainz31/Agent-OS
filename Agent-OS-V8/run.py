from __future__ import annotations

import os
import requests


API_URL = os.getenv("AGENTOS_API_URL", "http://127.0.0.1:8765").rstrip("/")


def main() -> None:
    print("=" * 64)
    print("AGENT-OS V8.0 — CLI")
    print("=" * 64)
    try:
        health = requests.get(API_URL + "/api/health", timeout=3)
        health.raise_for_status()
    except Exception as exc:
        print(f"Serveur inaccessible : {exc}")
        print("Lance d'abord : python -u .\\api_server.py")
        return
    data = health.json()
    print(f"Connecté à {data.get('name', 'Paul')} / V{data.get('version', '?')}")
    print("Tape quit pour fermer cette CLI.\n")
    while True:
        try:
            text = input("TOI > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"quit", "exit"}:
            break
        if not text:
            continue
        try:
            response = requests.post(API_URL + "/api/chat", json={"message": text}, timeout=240)
            response.raise_for_status()
            print("\nPAUL >")
            print(response.json().get("response", ""))
            print()
        except Exception as exc:
            print(f"\nERREUR > {exc}\n")
    print("CLI fermée. Le serveur peut continuer à tourner.")


if __name__ == "__main__":
    main()
