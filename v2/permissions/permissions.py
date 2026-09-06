"""
Permission Engine de Agent-OS V2.

Le modèle peut demander une action.

Il ne peut pas décider lui-même
si cette action est autorisée.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)

from enum import (
    Enum,
)


class PermissionResult(
    str,
    Enum,
):

    ALLOWED = (
        "allowed"
    )

    APPROVAL_REQUIRED = (
        "approval_required"
    )

    BLOCKED = (
        "blocked"
    )


@dataclass(
    frozen=True
)
class Permission:

    action: str

    result: PermissionResult

    reason: str


class PermissionEngine:
    """
    Autorité externe concernant
    les permissions.
    """

    def __init__(
        self,
    ) -> None:

        self._rules: dict[
            str,
            Permission,
        ] = {

            # ==============================================
            # LECTURE
            # ==============================================

            "read_file": Permission(
                action="read_file",
                result=(
                    PermissionResult.ALLOWED
                ),
                reason=(
                    "Lecture de fichiers "
                    "autorisée."
                ),
            ),

            "read_project": Permission(
                action="read_project",
                result=(
                    PermissionResult.ALLOWED
                ),
                reason=(
                    "Lecture du projet "
                    "autorisée."
                ),
            ),

            # ==============================================
            # WEB
            # ==============================================

            "web_search": Permission(
                action="web_search",
                result=(
                    PermissionResult.ALLOWED
                ),
                reason=(
                    "Recherche Web "
                    "autorisée."
                ),
            ),

            "web_fetch": Permission(
                action="web_fetch",
                result=(
                    PermissionResult.ALLOWED
                ),
                reason=(
                    "Lecture de pages Web "
                    "publiques autorisée."
                ),
            ),

            # ==============================================
            # ÉCRITURE
            # ==============================================

            "create_file": Permission(
                action="create_file",
                result=(
                    PermissionResult.ALLOWED
                ),
                reason=(
                    "Création de fichiers "
                    "projet autorisée."
                ),
            ),

            "modify_code": Permission(
                action="modify_code",
                result=(
                    PermissionResult
                    .APPROVAL_REQUIRED
                ),
                reason=(
                    "Modification de code "
                    "nécessitant validation."
                ),
            ),

            "delete_file": Permission(
                action="delete_file",
                result=(
                    PermissionResult
                    .APPROVAL_REQUIRED
                ),
                reason=(
                    "Suppression de fichier "
                    "nécessitant validation."
                ),
            ),

            # ==============================================
            # SYSTÈME
            # ==============================================

            "install_software": Permission(
                action="install_software",
                result=(
                    PermissionResult.BLOCKED
                ),
                reason=(
                    "Installation logicielle "
                    "bloquée par défaut."
                ),
            ),

            "restart_system": Permission(
                action="restart_system",
                result=(
                    PermissionResult.BLOCKED
                ),
                reason=(
                    "Redémarrage système "
                    "interdit."
                ),
            ),

            "run_dangerous_command": Permission(
                action=(
                    "run_dangerous_command"
                ),
                result=(
                    PermissionResult.BLOCKED
                ),
                reason=(
                    "Commande potentiellement "
                    "dangereuse interdite."
                ),
            ),

            # ==============================================
            # HOME ASSISTANT
            # ==============================================

            "modify_home_assistant": Permission(
                action=(
                    "modify_home_assistant"
                ),
                result=(
                    PermissionResult
                    .APPROVAL_REQUIRED
                ),
                reason=(
                    "Modification Home Assistant "
                    "nécessitant validation."
                ),
            ),

            "restart_home_assistant": Permission(
                action=(
                    "restart_home_assistant"
                ),
                result=(
                    PermissionResult.BLOCKED
                ),
                reason=(
                    "Redémarrage Home Assistant "
                    "interdit par défaut."
                ),
            ),

            # ==============================================
            # COMMUNICATION
            # ==============================================

            "send_external_message": Permission(
                action=(
                    "send_external_message"
                ),
                result=(
                    PermissionResult
                    .APPROVAL_REQUIRED
                ),
                reason=(
                    "Envoi externe nécessitant "
                    "validation."
                ),
            ),
        }

    def check(
        self,
        action: str,
    ) -> Permission:
        """
        Vérifie une permission.
        """

        permission = (
            self._rules.get(
                action
            )
        )

        if (
            permission
            is not None
        ):

            return permission

        return Permission(
            action=action,
            result=(
                PermissionResult.BLOCKED
            ),
            reason=(
                "Action inconnue : "
                "blocage par défaut."
            ),
        )

    def is_allowed(
        self,
        action: str,
    ) -> bool:

        return (
            self.check(
                action
            ).result
            == PermissionResult.ALLOWED
        )

    def requires_approval(
        self,
        action: str,
    ) -> bool:

        return (
            self.check(
                action
            ).result
            == (
                PermissionResult
                .APPROVAL_REQUIRED
            )
        )

    def is_blocked(
        self,
        action: str,
    ) -> bool:

        return (
            self.check(
                action
            ).result
            == PermissionResult.BLOCKED
        )