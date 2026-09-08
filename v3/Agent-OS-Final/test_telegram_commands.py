from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


# ------------------------------------------------------------
# STUB MINIMAL agentos.client POUR TESTER telegram_client.py
# SANS LANCER LE SERVEUR AGENT-OS.
# ------------------------------------------------------------

agentos_pkg = types.ModuleType("agentos")
client_mod = types.ModuleType("agentos.client")


class AgentOSClientError(RuntimeError):
    pass


class AgentOSUnavailable(AgentOSClientError):
    pass


class AgentOSClient:
    def __init__(self, *args, **kwargs):
        pass


client_mod.AgentOSClient = AgentOSClient
client_mod.AgentOSClientError = AgentOSClientError
client_mod.AgentOSUnavailable = AgentOSUnavailable

sys.modules["agentos"] = agentos_pkg
sys.modules["agentos.client"] = client_mod


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "telegram_client.py"

spec = importlib.util.spec_from_file_location(
    "telegram_client_under_test",
    TARGET,
)

if spec is None or spec.loader is None:
    raise RuntimeError("Impossible de charger telegram_client.py")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[OK] {label}")


commands = module.BOT_COMMANDS
names = [item["command"] for item in commands]

check(len(names) == len(set(names)), "Aucune commande Telegram dupliquée")
check(all(name == name.lower() for name in names), "Toutes les commandes sont en minuscules")
check(all(1 <= len(name) <= 32 for name in names), "Longueur des commandes Telegram valide")
check("help" in names, "/help présent")
check("manager" in names, "/manager présent")
check("conversation" in names, "/conversation présent")
check("research" in names, "/research présent")
check("priority" in names, "/priority présent")
check("deadline" in names, "/deadline présent")
check("pause" in names, "/pause présent")
check("retry" in names, "/retry présent")


obj = object.__new__(module.TelegramAgentOS)

message, error = obj._command_forward(
    "manager",
    "",
)
check(message == "manager status" and error is None, "/manager -> manager status")

message, error = obj._command_forward(
    "research",
    "",
)
check(message == "research status" and error is None, "/research sans argument -> status")

message, error = obj._command_forward(
    "research",
    "accident Lady Di",
)
check(
    message == "Recherche accident Lady Di"
    and error is None,
    "/research avec argument -> recherche",
)

message, error = obj._command_forward(
    "priority",
    "M-043 haute",
)
check(
    message == "priorité M-043 haute"
    and error is None,
    "/priority traduit correctement",
)

message, error = obj._command_forward(
    "deadline",
    "M-043 dans 2h",
)
check(
    message == "deadline M-043 dans 2h"
    and error is None,
    "/deadline traduit correctement",
)

message, error = obj._command_forward(
    "priority",
    "",
)
check(
    message is None
    and error == "Usage : /priority M-043 haute",
    "/priority sans argument donne une aide",
)

message, error = obj._command_forward(
    "pause",
    "M-043",
)
check(
    message == "pause M-043"
    and error is None,
    "/pause traduit correctement",
)

help_text = obj._help_text()
check("/manager" in help_text, "/help documente Manager")
check("/memoryrelations" in help_text, "/help documente mémoire relationnelle")
check("/conversation" in help_text, "/help documente conversation")
check("/research" in help_text, "/help documente recherche")
check("/priority M-043 haute" in help_text, "/help donne exemple priorité")
check("/deadline M-043 dans 2h" in help_text, "/help donne exemple deadline")


class FakeTelegram:
    def __init__(self) -> None:
        self.calls = []

    def call(self, method, payload=None, timeout=35.0):
        self.calls.append((method, payload, timeout))
        return True


obj.telegram = FakeTelegram()
obj.register_bot_commands()

check(
    obj.telegram.calls
    and obj.telegram.calls[0][0] == "setMyCommands",
    "setMyCommands appelé",
)

registered = obj.telegram.calls[0][1]["commands"]

check(
    registered == module.BOT_COMMANDS,
    "Menu Telegram synchronise la liste officielle",
)

print()
print("TOUS LES TESTS TELEGRAM SONT PASSÉS.")
