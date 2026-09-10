from __future__ import annotations

import json
import os
import re
import threading
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


BOT_COMMANDS: list[dict[str, str]] = [
    {"command": "help", "description": "Toutes les commandes Agent-OS"},
    {"command": "status", "description": "État général d'Agent-OS"},
    {"command": "briefing", "description": "Point équipe et missions"},
    {"command": "manager", "description": "État du Manager autonome"},
    {"command": "decisions", "description": "Décisions récentes du Manager"},
    {"command": "managercheck", "description": "Force une supervision immédiate"},
    {"command": "memory", "description": "Mémoire personnelle utile"},
    {"command": "memoryops", "description": "Historique opérationnel"},
    {"command": "memoryrelations", "description": "Mémoire relationnelle"},
    {"command": "memoryhistory", "description": "Historique de la mémoire"},
    {"command": "memorystats", "description": "Statistiques mémoire"},
    {"command": "memorycleanup", "description": "Maintenance de la mémoire"},
    {"command": "emotion", "description": "État émotionnel courant"},
    {"command": "emotionhistory", "description": "Historique émotionnel"},
    {"command": "conversation", "description": "État du fil de conversation"},
    {"command": "conversationhistory", "description": "Historique des conversations"},
    {"command": "newconversation", "description": "Démarre un nouveau fil"},
    {"command": "research", "description": "État recherche ou lance une recherche"},
    {"command": "researchhistory", "description": "Historique des recherches"},
    {"command": "skills", "description": "Liste des compétences techniques"},
    {"command": "skill", "description": "Détail d'une compétence"},
    {"command": "skillrequire", "description": "Skills requis pour une mission"},
    {"command": "skillrequirements", "description": "Skills effectifs d'une mission"},
    {"command": "specialists", "description": "Spécialistes dynamiques actifs/récents"},
    {"command": "specialist", "description": "Profil spécialiste d'une mission"},
    {"command": "learning", "description": "État de l'apprentissage autonome"},
    {"command": "learninghistory", "description": "Historique des apprentissages"},
    {"command": "learning_on", "description": "Active l'apprentissage autonome"},
    {"command": "learning_off", "description": "Désactive l'apprentissage autonome"},
    {"command": "collaboration", "description": "État de l'entraide entre agents"},
    {"command": "collaborationhistory", "description": "Historique des renforts inter-agents"},
    {"command": "collaboration_on", "description": "Active la collaboration inter-agents"},
    {"command": "collaboration_off", "description": "Désactive la collaboration inter-agents"},
    {"command": "workload", "description": "Charge globale et workers"},
    {"command": "backlog", "description": "Tâches en attente"},
    {"command": "workers", "description": "État des workers"},
    {"command": "tree", "description": "Arbre d'une mission : M-043"},
    {"command": "submissions", "description": "Sous-missions : M-043"},
    {"command": "submission", "description": "Crée une sous-mission"},
    {"command": "autonomy_on", "description": "Active l'autonomie globale"},
    {"command": "autonomy_off", "description": "Désactive l'autonomie globale"},
    {"command": "priority", "description": "Priorité mission : M-043 haute"},
    {"command": "deadline", "description": "Échéance : M-043 dans 2h"},
    {"command": "pause", "description": "Met une mission en pause"},
    {"command": "resume", "description": "Reprend une mission"},
    {"command": "cancel", "description": "Annule une mission"},
    {"command": "retry", "description": "Retente une mission échouée"},
    {"command": "id", "description": "Affiche le Chat ID Telegram"},
]


class TelegramAPIError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str) -> None:
        self.token = str(token).strip()

        if not self.token:
            raise ValueError("Token Telegram vide.")

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
            clean_payload: dict[str, str] = {}

            for key, value in payload.items():
                if value is None:
                    continue

                if isinstance(value, (dict, list)):
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
                    clean_payload[key] = str(value)

            data = urlencode(
                clean_payload
            ).encode("utf-8")

        request = Request(
            f"{self.base_url}/{method}",
            data=data,
            headers={
                "Content-Type": (
                    "application/x-www-form-urlencoded; "
                    "charset=utf-8"
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
        self.telegram = TelegramAPI(token)

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

        chunks: list[str] = []

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
            chunks.append(value)

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

    @staticmethod
    def _command_name(
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

    @staticmethod
    def _command_args(
        text: str,
    ) -> str:
        value = str(
            text
            or ""
        ).strip()

        if not value.startswith("/"):
            return ""

        parts = value.split(
            None,
            1,
        )

        if len(parts) < 2:
            return ""

        return parts[1].strip()

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
        chunks = self._chunks(text)

        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }

            if (
                reply_markup is not None
                and index == len(chunks) - 1
            ):
                payload["reply_markup"] = reply_markup

            self.telegram.call(
                "sendMessage",
                payload,
                timeout=20.0,
            )

    def _chat_and_send(
        self,
        chat_id: int,
        message: str,
    ) -> None:
        self.telegram.call(
            "sendChatAction",
            {
                "chat_id": chat_id,
                "action": "typing",
            },
            timeout=10.0,
        )

        result = self.agentos.chat(
            message
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
            and self._needs_approval(text)
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
    # COMMAND MENU / HELP
    # =========================================================

    def register_bot_commands(
        self,
    ) -> None:
        self.telegram.call(
            "setMyCommands",
            {
                "commands": BOT_COMMANDS,
            },
            timeout=15.0,
        )

    def _help_text(
        self,
    ) -> str:
        return (
            "Agent-OS Telegram\n\n"
            "Tu peux écrire normalement à Paul. Les commandes ci-dessous "
            "servent surtout de raccourcis.\n\n"

            "GÉNÉRAL\n"
            "/status — état général d'Agent-OS\n"
            "/briefing — point équipe et missions\n"
            "/manager — état du Manager autonome\n"
            "/decisions — décisions récentes du Manager\n"
            "/managercheck — force une supervision immédiate\n\n"

            "MÉMOIRE\n"
            "/memory — mémoire personnelle utile\n"
            "/memoryops — historique opérationnel\n"
            "/memoryrelations — mémoire relationnelle\n"
            "/memoryhistory — historique des changements\n"
            "/memorystats — statistiques mémoire\n"
            "/memorycleanup — maintenance/nettoyage\n\n"

            "ÉMOTIONS\n"
            "/emotion — état émotionnel courant\n"
            "/emotionhistory — historique émotionnel\n\n"

            "CONVERSATION\n"
            "/conversation — état du fil courant\n"
            "/conversationhistory — anciens fils\n"
            "/newconversation — démarre un nouveau fil\n\n"

            "RECHERCHE\n"
            "/research — état de la recherche factuelle\n"
            "/research Lady Di — lance une vraie recherche\n"
            "/researchhistory — historique des recherches\n\n"

            "COMPÉTENCES / SPÉCIALISTES / LEARNING / COLLABORATION V5.5\n"
            "/skills — liste le Skill Registry\n"
            "/skill yaml — détail d'une compétence\n"
            "/skill add yaml — crée une compétence\n"
            "/skillrequire M-043 yaml, home_assistant — skills requis\n"
            "/skillrequirements M-043 — skills effectifs + héritage\n"
            "/specialists — spécialistes dynamiques actifs/récents\n"
            "/specialist M-043 — profils calculés pour une mission\n"
            "/learning — état de l'apprentissage autonome\n"
            "/learninghistory — historique des apprentissages\n"
            "/learning_on — active l'apprentissage autonome\n"
            "/learning_off — désactive l'apprentissage autonome\n"
            "/collaboration — état de l'entraide entre agents\n"
            "/collaborationhistory — historique des renforts\n"
            "/collaboration_on — active la collaboration\n"
            "/collaboration_off — désactive la collaboration\n\n"

            "WORKLOAD / ARBRES V5\n"
            "/workload — charge globale et disponibilité\n"
            "/backlog — tâches actuellement en attente\n"
            "/workers — état des workers\n"
            "/tree M-043 — affiche l'arbre complet\n"
            "/submissions M-043 — liste ses sous-missions directes\n"
            "/submission M-043 : Recherche la documentation — crée un enfant\n"
            "/submission M-043 après M-044 : Crée le YAML — enfant dépendant\n\n"

            "AUTONOMIE / MISSIONS\n"
            "/autonomy_on — active l'autonomie globale\n"
            "/autonomy_off — désactive l'autonomie globale\n"
            "/priority M-043 haute — change la priorité\n"
            "/deadline M-043 dans 2h — fixe une échéance\n"
            "/pause M-043 — met en pause\n"
            "/resume M-043 — reprend\n"
            "/cancel M-043 — annule\n"
            "/retry M-043 — retente une mission échouée\n\n"

            "AUTORISATIONS\n"
            "Les demandes sensibles affichent directement les boutons "
            "✅ Autoriser et ❌ Refuser.\n\n"

            "/id — affiche ton Chat ID Telegram\n"
            "/help — affiche cette aide"
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

    def _command_forward(
        self,
        command: str,
        args: str,
    ) -> tuple[str | None, str | None]:
        """
        Retourne (message Agent-OS, erreur utilisateur).
        """

        fixed = {
            "briefing": "briefing",
            "memory": "memory",
            "memoryops": "memory operations",
            "memory_ops": "memory operations",
            "memoryrelations": "memory relations",
            "relations": "memory relations",
            "memoryhistory": "memory history",
            "relationhistory": "memory history",
            "memorystats": "memory stats",
            "memorycleanup": "memory cleanup",
            "memorymaintenance": "memory cleanup",
            "emotion": "emotion",
            "humeur": "emotion",
            "emotionhistory": "emotion history",
            "emotion_history": "emotion history",
            "conversation": "conversation status",
            "conversationhistory": "conversation history",
            "newconversation": "nouvelle conversation",
            "manager": "manager status",
            "decisions": "manager decisions",
            "managercheck": "manager check",
            "researchhistory": "research history",
            "skills": "skills",
            "specialists": "specialists",
            "learning": "learning status",
            "learninghistory": "learning history",
            "learning_on": "learning on",
            "learning_off": "learning off",
            "collaboration": "collaboration status",
            "collaborationhistory": "collaboration history",
            "collaboration_on": "collaboration on",
            "collaboration_off": "collaboration off",
            "workload": "workload status",
            "backlog": "backlog",
            "workers": "workers status",
            "autonomy_on": "autonomie on",
            "autonomy_off": "autonomie off",
        }

        if command in fixed:
            return fixed[command], None

        if command == "research":
            if args:
                return (
                    "Recherche "
                    + args,
                    None,
                )

            return "research status", None

        if command == "skill":
            if args:
                return "skill " + args, None
            return "skills", None

        if command == "skillrequire":
            if not args:
                return (
                    None,
                    "Usage : /skillrequire M-043 yaml, home_assistant",
                )
            return "skill require " + args, None

        if command == "skillrequirements":
            if not args:
                return (
                    None,
                    "Usage : /skillrequirements M-043",
                )
            return "skill requirements " + args, None

        if command == "specialist":
            if not args:
                return (
                    None,
                    "Usage : /specialist M-043",
                )
            return "specialist " + args, None

        if command == "tree":
            return (
                "mission tree " + args
                if args
                else "mission tree",
                None,
            )

        if command == "submissions":
            if not args:
                return (
                    None,
                    "Usage : /submissions M-043",
                )
            return (
                "sous-missions " + args,
                None,
            )

        if command == "submission":
            if not args:
                return (
                    None,
                    "Usage : /submission M-043 : Recherche la documentation",
                )
            return (
                "sous-mission " + args,
                None,
            )

        if command == "priority":
            if not args:
                return (
                    None,
                    "Usage : /priority M-043 haute",
                )

            return (
                "priorité "
                + args,
                None,
            )

        if command == "deadline":
            if not args:
                return (
                    None,
                    "Usage : /deadline M-043 dans 2h",
                )

            return (
                "deadline "
                + args,
                None,
            )

        if command == "pause":
            return (
                "pause "
                + args
                if args
                else "pause",
                None,
            )

        if command == "resume":
            return (
                "reprends "
                + args
                if args
                else "reprends",
                None,
            )

        if command == "cancel":
            return (
                "annule "
                + args
                if args
                else "annule",
                None,
            )

        if command == "retry":
            return (
                "retry "
                + args
                if args
                else "retry",
                None,
            )

        return None, None

    # =========================================================
    # SECURITY
    # =========================================================

    def _authorized(
        self,
        chat_id: int,
    ) -> bool:
        return (
            self.allowed_chat_id is not None
            and chat_id == self.allowed_chat_id
        )

    # =========================================================
    # INCOMING MESSAGES
    # =========================================================

    def handle_message(
        self,
        message: dict[str, Any],
    ) -> None:
        chat = (
            message.get("chat")
            or {}
        )

        chat_id_raw = chat.get("id")

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
            if self._authorized(chat_id):
                self.send(
                    chat_id,
                    "Pour le moment, envoie-moi du texte.",
                )
            return

        command = self._command_name(
            text
        )

        args = self._command_args(
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

            if command:
                forwarded, error = (
                    self._command_forward(
                        command,
                        args,
                    )
                )

                if error:
                    self.send(
                        chat_id,
                        error,
                    )
                    return

                if forwarded is not None:
                    self._chat_and_send(
                        chat_id,
                        forwarded,
                    )
                    return

                self.send(
                    chat_id,
                    (
                        f"Commande /{command} inconnue.\n"
                        "Utilise /help pour voir les commandes disponibles."
                    ),
                )
                return

            self._chat_and_send(
                chat_id,
                text,
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

        message = (
            callback.get("message")
            or {}
        )

        chat = (
            message.get("chat")
            or {}
        )

        chat_id_raw = chat.get("id")

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
                payload["offset"] = self.offset

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

        try:
            self.register_bot_commands()
            commands_status = "menu de commandes synchronisé"
        except TelegramAPIError as exc:
            commands_status = (
                "menu non synchronisé : "
                + str(exc)
            )

        print("=" * 64)
        print("AGENT-OS — TELEGRAM CLIENT")
        print("=" * 64)

        print(
            "Bot Telegram : @"
            + (
                self.bot_username
                or "inconnu"
            )
        )

        print(
            "Commandes Telegram : "
            + commands_status
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
