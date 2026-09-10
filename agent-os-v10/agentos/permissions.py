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
    """Politique globale complétée par des limites propres aux profils V7."""

    PROFILE_ALLOWED_ACTIONS = {
        "manager": {
            "read_workspace",
            "web_search",
            "create_file",
            "modify_file",
            "run_python_test",
            "build_artifact",
            "run_artifact_test",
            "delete_file",
            "send_external_message",
        },
        "ai_worker": {"read_workspace"},
        "researcher": {"read_workspace", "web_search"},
        "developer": {
            "read_workspace",
            "create_file",
            "modify_file",
            "run_python_test",
            "build_artifact",
            "run_artifact_test",
        },
        "tester": {
            "read_workspace",
            "run_python_test",
            "run_artifact_test",
        },
        "document_analyst": {
            "read_workspace",
            "create_file",
            "modify_file",
            "build_artifact",
            "run_artifact_test",
        },
    }

    def __init__(self) -> None:
        self.rules = {
            "read_workspace": Permission(
                "read_workspace",
                Decision.ALLOWED,
                "Lecture autorisée.",
            ),
            "web_search": Permission(
                "web_search",
                Decision.ALLOWED,
                "Recherche Web autorisée.",
            ),
            "create_file": Permission(
                "create_file",
                Decision.ALLOWED,
                "Création autorisée.",
            ),
            "modify_file": Permission(
                "modify_file",
                Decision.APPROVAL_REQUIRED,
                "Modification soumise à approbation.",
            ),
            "run_python_test": Permission(
                "run_python_test",
                Decision.ALLOWED,
                "Tests Python contraints autorisés.",
            ),
            "build_artifact": Permission(
                "build_artifact",
                Decision.ALLOWED,
                (
                    "Build d'artefacts locaux via les builders "
                    "Agent-OS explicitement autorisés."
                ),
            ),
            "run_artifact_test": Permission(
                "run_artifact_test",
                Decision.ALLOWED,
                (
                    "Self-tests bornés des artefacts locaux "
                    "produits par Agent-OS autorisés."
                ),
            ),
            "delete_file": Permission(
                "delete_file",
                Decision.APPROVAL_REQUIRED,
                "Suppression soumise à approbation.",
            ),
            "install_software": Permission(
                "install_software",
                Decision.BLOCKED,
                "Installation bloquée.",
            ),
            "shell_command": Permission(
                "shell_command",
                Decision.BLOCKED,
                "Shell arbitraire bloqué.",
            ),
            "restart_system": Permission(
                "restart_system",
                Decision.BLOCKED,
                "Redémarrage bloqué.",
            ),
            "send_external_message": Permission(
                "send_external_message",
                Decision.APPROVAL_REQUIRED,
                "Envoi externe soumis à approbation.",
            ),
        }

    def check(
        self,
        action: str,
        profile: str | None = None,
    ) -> Permission:
        normalized_profile = str(profile or "").strip().lower()
        allowed = self.PROFILE_ALLOWED_ACTIONS.get(normalized_profile)
        if allowed is not None and action not in allowed:
            return Permission(
                action,
                Decision.BLOCKED,
                (
                    f"Action '{action}' bloquée pour le profil "
                    f"'{normalized_profile}'."
                ),
            )
        return self.rules.get(
            action,
            Permission(
                action,
                Decision.BLOCKED,
                "Action inconnue : blocage par défaut.",
            ),
        )

    def catalog(self, profile: str | None = None) -> list[dict[str, str]]:
        """Expose la politique effective pour l'interface et les diagnostics."""
        return [
            {
                "action": action,
                "decision": self.check(action, profile=profile).decision.value,
                "reason": self.check(action, profile=profile).reason,
            }
            for action in sorted(self.rules)
        ]
