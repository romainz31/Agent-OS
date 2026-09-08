from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agentos.client import (
    AgentOSClient,
    AgentOSClientError,
    AgentOSUnavailable,
)


TELEGRAM_MESSAGE_LIMIT = 3900
MISSION_RE = re.compile(
    r"\bM-\d{1,6}\b",
    flags=re.IGNORECASE,
)


class TelegramAPIError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(
        self,
        token: str,
    ) -> None:
        self.token = str(
            token
        ).strip()

        if not self.token:
            raise ValueError(
                "Token Telegram vide."
            )

        self.base_url = (
            "https://api.telegram.org/bot"
            + self.token
        )

    def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 35.0,
    ) -> Any:
        data = None

        if payload:
            clean_payload = {}

            for key, value in payload.items():
                if value is None:
                    continue

                if isinstance(
                    value,
                    (dict, list),
                ):
                    clean_payload[key] = json.dumps(
                        value,
                        ensure_ascii=False,
                    )
                elif isinstance(value, bool):
                    clean_payload[key] = (
                        "true"
                        if value
                        else "false"
                    )
                else:
                    clean_payload[key] = str(
                        value
                    )

            data = urlencode(
                clean_payload
            ).encode("utf-8")

        request = Request(
            f"{self.base_url}/{method}",
            data=data,
            headers={
                "Content-Type": (
                    "application/x-www-form-urlencoded; charset=utf-8"
                ),
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=timeout,
            ) as response:
                raw = response.read()

        except HTTPError as exc:
            try:
                detail = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )
            except Exception:
                detail = str(exc)

            raise TelegramAPIError(
                "Erreur Telegram : "
                f"{detail}"
            ) from exc

        except (URLError, TimeoutError) as exc:
            raise TelegramAPIError(
                "Telegram inaccessible : "
                f"{exc}"
            ) from exc

        try:
            parsed = json.loads(
                raw.decode("utf-8")
            )
        except Exception as exc:
            raise TelegramAPIError(
                "Réponse Telegram invalide."
            ) from exc

        if not parsed.get("ok"):
            raise TelegramAPIError(
                str(
                    parsed.get(
                        "description",
                        "Erreur Telegram inconnue.",
                    )
                )
            )

        return parsed.get("result")


class TelegramAgentOS:
    def __init__(
        self,
        *,
        token: str,
        agentos_url: str,
        allowed_chat_id: int | None,
    ) -> None:
        self.telegram = TelegramAPI(
            token
        )
        self.allowed_chat_id = (
            int(allowed_chat_id)
            if allowed_chat_id is not None
            else None
        )

        client_suffix = (
            str(self.allowed_chat_id)
            if self.allowed_chat_id is not None
            else "onboarding"
        )

        self.agentos = AgentOSClient(
            agentos_url,
            client_id=(
                "telegram-"
                + client_suffix
            ),
        )

        self.stop_event = threading.Event()
        self.offset: int | None = None
        self.bot_username = ""
        self.notifications_initialized = False

    # =========================================================
    # TEXT HELPERS
    # =========================================================

    @staticmethod
    def _chunks(
        text: str,
    ) -> list[str]:
        value = str(
            text
            or ""
        ).strip()

        if not value:
            return []

        chunks = []

        while len(value) > TELEGRAM_MESSAGE_LIMIT:
            split_at = value.rfind(
                "\n",
                0,
                TELEGRAM_MESSAGE_LIMIT,
            )

            if split_at < 1000:
                split_at = value.rfind(
                    " ",
                    0,
                    TELEGRAM_MESSAGE_LIMIT,
                )

            if split_at < 1000:
                split_at = TELEGRAM_MESSAGE_LIMIT

            chunks.append(
                value[:split_at].strip()
            )
            value = value[
                split_at:
            ].strip()

        if value:
            chunks.append(
                value
            )

        return chunks

    @staticmethod
    def _mission_reference(
        text: str,
    ) -> str | None:
        match = MISSION_RE.search(
            str(text or "")
        )

        if match is None:
            return None

        raw = match.group(0).upper()
        number = int(
            raw.split("-")[1]
        )
        return f"M-{number:03d}"

    @staticmethod
    def _needs_approval(
        text: str,
    ) -> bool:
        value = str(
            text
            or ""
        ).lower()

        return any(
            marker in value
            for marker in (
                "autorisation",
                "approbation",
                "tu valides",
            )
        )

    # =========================================================
    # TELEGRAM OUTPUT
    # =========================================================

    def send(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        chunks = self._chunks(
            text
        )

        for index, chunk in enumerate(
            chunks
        ):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }

            if (
                reply_markup is not None
                and index == len(chunks) - 1
            ):
                payload[
                    "reply_markup"
                ] = reply_markup

            self.telegram.call(
                "sendMessage",
                payload,
                timeout=20.0,
            )

    def send_manager_notification(
        self,
        text: str,
    ) -> None:
        if self.allowed_chat_id is None:
            return

        mission_ref = self._mission_reference(
            text
        )

        keyboard = None

        if (
            mission_ref
            and self._needs_approval(
                text
            )
        ):
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Autoriser",
                            "callback_data": (
                                "approve:"
                                + mission_ref
                            ),
                        },
                        {
                            "text": "❌ Refuser",
                            "callback_data": (
                                "reject:"
                                + mission_ref
                            ),
                        },
                    ]
                ]
            }

        self.send(
            self.allowed_chat_id,
            text,
            reply_markup=keyboard,
        )

    # =========================================================
    # SECURITY / COMMANDS
    # =========================================================

    def _authorized(
        self,
        chat_id: int,
    ) -> bool:
        return (
            self.allowed_chat_id is not None
            and chat_id == self.allowed_chat_id
        )

    def _command_name(
        self,
        text: str,
    ) -> str:
        first = str(
            text
            or ""
        ).strip().split(
            " ",
            1,
        )[0]

        if not first.startswith("/"):
            return ""

        command = first[1:]

        if "@" in command:
            command = command.split(
                "@",
                1,
            )[0]

        return command.lower()

    def _help_text(
        self,
    ) -> str:
        return (
            "Agent-OS Telegram\n\n"
            "Écris-moi normalement : le message est transmis au même "
            "Manager que le navigateur et la CLI.\n\n"
            "Commandes :\n"
            "/status — état d'Agent-OS\n"
            "/briefing — point équipe\n"
            "/memory — mémoire personnelle utile\n"
            "/memoryops — historique opérationnel Agent-OS\n"
            "/emotion — état émotionnel courant estimé\n"
            "/emotionhistory — historique émotionnel récent\n"
            "/id — identifiant de ce chat\n"
            "/help — aide\n\n"
            "Les demandes d'autorisation peuvent être validées ou "
            "refusées avec les boutons Telegram."
        )

    def _status_text(
        self,
    ) -> str:
        status = self.agentos.status()

        return (
            "Agent-OS "
            f"V{status.get('version', '?')}\n"
            f"Missions actives : {status.get('active_missions', 0)}\n"
            f"Workers en exécution : {status.get('running_jobs', 0)}\n"
            f"Approbations : {status.get('pending_approvals', 0)}\n"
            f"Missions totales : {status.get('total_missions', 0)}"
        )

    # =========================================================
    # INCOMING MESSAGES
    # =========================================================

    def handle_message(
        self,
        message: dict[str, Any],
    ) -> None:
        chat = message.get(
            "chat"
        ) or {}

        chat_id_raw = chat.get(
            "id"
        )

        if chat_id_raw is None:
            return

        chat_id = int(
            chat_id_raw
        )

        text = str(
            message.get(
                "text",
                "",
            )
            or ""
        ).strip()

        if not text:
            if self._authorized(
                chat_id
            ):
                self.send(
                    chat_id,
                    "Pour le moment, envoie-moi du texte.",
                )
            return

        command = self._command_name(
            text
        )

        # -----------------------------------------------------
        # ONBOARDING
        # -----------------------------------------------------

        if self.allowed_chat_id is None:
            if command in {
                "start",
                "id",
            }:
                self.send(
                    chat_id,
                    (
                        "Ton Telegram chat_id est :\n"
                        f"{chat_id}\n\n"
                        "Ajoute maintenant cette valeur dans "
                        "TELEGRAM_ALLOWED_CHAT_ID puis redémarre "
                        "telegram_client.py. Tant que ce n'est pas fait, "
                        "aucun accès à Agent-OS n'est autorisé."
                    ),
                )
            return

        if not self._authorized(
            chat_id
        ):
            return

        try:
            if command in {
                "start",
                "help",
            }:
                self.send(
                    chat_id,
                    self._help_text(),
                )
                return

            if command == "id":
                self.send(
                    chat_id,
                    f"Chat ID : {chat_id}",
                )
                return

            if command == "status":
                self.send(
                    chat_id,
                    self._status_text(),
                )
                return

            if command == "briefing":
                result = self.agentos.chat(
                    "briefing"
                )
                self.send(
                    chat_id,
                    str(
                        result.get(
                            "response",
                            "",
                        )
                    ),
                )
                return

            if command == "memory":
                result = self.agentos.chat(
                    "memory"
                )
                self.send(
                    chat_id,
                    str(
                        result.get(
                            "response",
                            "",
                        )
                    ),
                )
                return

            if command in {
                "memoryops",
                "memory_ops",
            }:
                result = self.agentos.chat(
                    "memory operations"
                )
                self.send(
                    chat_id,
                    str(
                        result.get(
                            "response",
                            "",
                        )
                    ),
                )
                return

            if command in {
                "emotion",
                "humeur",
            }:
                result = self.agentos.chat(
                    "emotion"
                )
                self.send(
                    chat_id,
                    str(
                        result.get(
                            "response",
                            "",
                        )
                    ),
                )
                return

            if command in {
                "emotionhistory",
                "emotion_history",
            }:
                result = self.agentos.chat(
                    "emotion history"
                )
                self.send(
                    chat_id,
                    str(
                        result.get(
                            "response",
                            "",
                        )
                    ),
                )
                return

            self.telegram.call(
                "sendChatAction",
                {
                    "chat_id": chat_id,
                    "action": "typing",
                },
                timeout=10.0,
            )

            result = self.agentos.chat(
                text
            )

            response = str(
                result.get(
                    "response",
                    "",
                )
                or ""
            ).strip()

            if response:
                self.send(
                    chat_id,
                    response,
                )

        except (
            AgentOSClientError,
            AgentOSUnavailable,
        ) as exc:
            self.send(
                chat_id,
                str(exc),
            )

        except TelegramAPIError:
            raise

        except Exception as exc:
            self.send(
                chat_id,
                "Erreur Telegram/Agent-OS : "
                f"{exc}",
            )

    # =========================================================
    # CALLBACK BUTTONS
    # =========================================================

    def handle_callback(
        self,
        callback: dict[str, Any],
    ) -> None:
        callback_id = str(
            callback.get(
                "id",
                "",
            )
        )

        message = callback.get(
            "message"
        ) or {}

        chat = message.get(
            "chat"
        ) or {}

        chat_id_raw = chat.get(
            "id"
        )

        if chat_id_raw is None:
            return

        chat_id = int(
            chat_id_raw
        )

        if not self._authorized(
            chat_id
        ):
            if callback_id:
                self.telegram.call(
                    "answerCallbackQuery",
                    {
                        "callback_query_id": callback_id,
                        "text": "Non autorisé.",
                        "show_alert": True,
                    },
                    timeout=10.0,
                )
            return

        data = str(
            callback.get(
                "data",
                "",
            )
        )

        try:
            action, reference = data.split(
                ":",
                1,
            )
        except ValueError:
            return

        if action not in {
            "approve",
            "reject",
        }:
            return

        reference = reference.upper()

        try:
            if action == "approve":
                result = self.agentos.approve_mission(
                    reference
                )
                confirmation = (
                    f"{reference} autorisée."
                )
            else:
                result = self.agentos.reject_mission(
                    reference
                )
                confirmation = (
                    f"{reference} refusée."
                )

            detail = str(
                result.get(
                    "message",
                    confirmation,
                )
                or confirmation
            )

            if callback_id:
                self.telegram.call(
                    "answerCallbackQuery",
                    {
                        "callback_query_id": callback_id,
                        "text": confirmation,
                    },
                    timeout=10.0,
                )

            self.send(
                chat_id,
                detail,
            )

        except Exception as exc:
            if callback_id:
                self.telegram.call(
                    "answerCallbackQuery",
                    {
                        "callback_query_id": callback_id,
                        "text": str(exc)[:180],
                        "show_alert": True,
                    },
                    timeout=10.0,
                )

    # =========================================================
    # AGENT-OS NOTIFICATIONS
    # =========================================================

    def notification_loop(
        self,
    ) -> None:
        while not self.stop_event.wait(
            1.2
        ):
            if self.allowed_chat_id is None:
                continue

            try:
                result = self.agentos.notifications(
                    limit=100
                )

                items = list(
                    result.get(
                        "items",
                        [],
                    )
                    or []
                )

                if not self.notifications_initialized:
                    self.notifications_initialized = True

                    if items:
                        print(
                            "[Telegram] "
                            f"{len(items)} ancienne(s) notification(s) "
                            "ignorée(s) au démarrage.",
                            flush=True,
                        )
                    continue

                for item in items:
                    self.send_manager_notification(
                        str(item)
                    )

            except AgentOSUnavailable:
                continue

            except Exception as exc:
                print(
                    "[Telegram] Erreur notifications : "
                    f"{exc}",
                    flush=True,
                )

    # =========================================================
    # UPDATE LOOP
    # =========================================================

    def update_loop(
        self,
    ) -> None:
        while not self.stop_event.is_set():
            payload: dict[str, Any] = {
                "timeout": 25,
                "allowed_updates": [
                    "message",
                    "callback_query",
                ],
            }

            if self.offset is not None:
                payload[
                    "offset"
                ] = self.offset

            try:
                updates = self.telegram.call(
                    "getUpdates",
                    payload,
                    timeout=35.0,
                ) or []

                for update in updates:
                    update_id = int(
                        update.get(
                            "update_id",
                            0,
                        )
                    )

                    self.offset = (
                        update_id + 1
                    )

                    if "callback_query" in update:
                        self.handle_callback(
                            update[
                                "callback_query"
                            ]
                        )
                        continue

                    if "message" in update:
                        self.handle_message(
                            update[
                                "message"
                            ]
                        )

            except TelegramAPIError as exc:
                print(
                    "[Telegram] "
                    f"{exc}",
                    flush=True,
                )
                self.stop_event.wait(
                    3.0
                )

    # =========================================================
    # RUN
    # =========================================================

    def run(
        self,
    ) -> None:
        me = self.telegram.call(
            "getMe",
            timeout=15.0,
        ) or {}

        self.bot_username = str(
            me.get(
                "username",
                "",
            )
        )

        print(
            "=" * 64
        )
        print(
            "AGENT-OS V4.4 — TELEGRAM CLIENT"
        )
        print(
            "=" * 64
        )
        print(
            "Bot Telegram : @"
            + (
                self.bot_username
                or "inconnu"
            )
        )

        if self.allowed_chat_id is None:
            print(
                "Mode onboarding : aucun chat n'a encore accès à Agent-OS."
            )
            print(
                "Envoie /id ou /start au bot pour récupérer ton chat_id."
            )
        else:
            print(
                "Chat autorisé : "
                f"{self.allowed_chat_id}"
            )

            try:
                health = self.agentos.health()
                print(
                    "Agent-OS connecté : V"
                    + str(
                        health.get(
                            "version",
                            "?",
                        )
                    )
                )
            except Exception as exc:
                print(
                    "Agent-OS non joignable au démarrage : "
                    f"{exc}"
                )

        print(
            "Ctrl+C pour arrêter Telegram.\n"
        )

        notification_thread = threading.Thread(
            target=self.notification_loop,
            daemon=True,
            name="agentos-telegram-notifications",
        )
        notification_thread.start()

        try:
            self.update_loop()
        except KeyboardInterrupt:
            print(
                "\nArrêt Telegram demandé."
            )
        finally:
            self.stop_event.set()
            notification_thread.join(
                timeout=2.0
            )


def env_chat_id() -> int | None:
    raw = str(
        os.environ.get(
            "TELEGRAM_ALLOWED_CHAT_ID",
            "",
        )
        or ""
    ).strip()

    if not raw:
        return None

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            "TELEGRAM_ALLOWED_CHAT_ID doit être un nombre entier."
        ) from exc


def main() -> None:
    token = str(
        os.environ.get(
            "TELEGRAM_BOT_TOKEN",
            "",
        )
        or ""
    ).strip()

    if not token:
        print(
            "TELEGRAM_BOT_TOKEN n'est pas défini.\n"
            "Crée le bot avec @BotFather puis, dans PowerShell :\n\n"
            '$env:TELEGRAM_BOT_TOKEN = "TON_TOKEN"\n'
        )
        raise SystemExit(2)

    agentos_url = str(
        os.environ.get(
            "AGENTOS_URL",
            "http://127.0.0.1:8765",
        )
        or "http://127.0.0.1:8765"
    ).strip()

    bridge = TelegramAgentOS(
        token=token,
        agentos_url=agentos_url,
        allowed_chat_id=env_chat_id(),
    )

    bridge.run()


if __name__ == "__main__":
    main()
