from __future__ import annotations

import os
import time
from typing import Any

import requests


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
AGENTOS_API_URL = os.getenv("AGENTOS_API_URL", "http://127.0.0.1:8765").rstrip("/")


def tg(method: str, **payload: Any) -> dict[str, Any]:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN est vide.")
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        json=payload,
        timeout=65,
    )
    response.raise_for_status()
    return response.json()


def send_message(chat_id: int, text: str) -> None:
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    for chunk in chunks:
        tg("sendMessage", chat_id=chat_id, text=chunk)


def ask_paul(text: str) -> str:
    response = requests.post(
        AGENTOS_API_URL + "/api/chat",
        json={"message": text},
        timeout=240,
    )
    response.raise_for_status()
    return str(response.json().get("response", ""))


def main() -> None:
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN manquant. Ajoute-le dans .env ou PowerShell.")
        return
    offset = 0
    print("Agent-OS V8 — Telegram bridge actif.")
    while True:
        try:
            data = tg("getUpdates", offset=offset, timeout=50, allowed_updates=["message"])
            for update in data.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                message = update.get("message") or {}
                text = str(message.get("text") or "").strip()
                chat = message.get("chat") or {}
                sender = message.get("from") or {}
                chat_id = int(chat.get("id", 0) or 0)
                user_id = str(sender.get("id", ""))
                if not text or not chat_id:
                    continue
                if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
                    continue
                try:
                    send_message(chat_id, ask_paul(text))
                except Exception as exc:
                    send_message(chat_id, f"Erreur Agent-OS : {exc}")
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Telegram : {exc}")
            time.sleep(3)


if __name__ == "__main__":
    main()
