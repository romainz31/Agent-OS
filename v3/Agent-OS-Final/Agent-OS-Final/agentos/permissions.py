from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class Decision(str, Enum):
    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class Permission:
    action: str
    decision: Decision
    reason: str

class PermissionEngine:
    def __init__(self) -> None:
        self.rules = {
            "read_workspace": Permission("read_workspace", Decision.ALLOWED, "Lecture autorisée."),
            "web_search": Permission("web_search", Decision.ALLOWED, "Recherche Web autorisée."),
            "create_file": Permission("create_file", Decision.ALLOWED, "Création autorisée."),
            "modify_file": Permission("modify_file", Decision.APPROVAL_REQUIRED, "Modification soumise à approbation."),
            "run_python_test": Permission("run_python_test", Decision.ALLOWED, "Tests Python contraints autorisés."),
            "delete_file": Permission("delete_file", Decision.APPROVAL_REQUIRED, "Suppression soumise à approbation."),
            "install_software": Permission("install_software", Decision.BLOCKED, "Installation bloquée."),
            "shell_command": Permission("shell_command", Decision.BLOCKED, "Shell arbitraire bloqué."),
            "restart_system": Permission("restart_system", Decision.BLOCKED, "Redémarrage bloqué."),
            "send_external_message": Permission("send_external_message", Decision.APPROVAL_REQUIRED, "Envoi externe soumis à approbation."),
        }
    def check(self, action: str) -> Permission:
        return self.rules.get(action, Permission(action, Decision.BLOCKED, "Action inconnue : blocage par défaut."))
