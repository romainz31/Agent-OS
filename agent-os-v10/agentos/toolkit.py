"""Registre d'outils typé et contrôlé pour Agent-OS V7.

Ce contrat reprend les qualités utiles du modèle Agent Zero (catalogue,
cycle avant/après, réponse normalisée et politique par profil) sans importer
sa pile Docker/LangChain. Les outils historiques pourront migrer vers ce
registre progressivement sans casser la V6 reprise par la V7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agentos.extensions import ExtensionBus
from agentos.permissions import Decision, PermissionEngine


ToolHandler = Callable[..., Any]


@dataclass
class ToolResponse:
    message: str
    success: bool = True
    break_loop: bool = False
    additional: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: ToolHandler
    permissions: tuple[str, ...] = ()
    profiles: frozenset[str] = frozenset()
    schema: dict[str, Any] = field(default_factory=dict)

    def public_dict(self, *, profile: str = "") -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions),
            "profiles": sorted(self.profiles),
            "schema": self.schema,
            "available": not self.profiles or profile in self.profiles,
        }


class ToolRegistry:
    def __init__(
        self,
        permissions: PermissionEngine,
        extensions: ExtensionBus | None = None,
    ) -> None:
        self.permissions = permissions
        self.extensions = extensions or ExtensionBus()
        self._tools: dict[str, ToolSpec] = {}

    @staticmethod
    def _name(value: str) -> str:
        name = str(value or "").strip().lower()
        if not name or not name.replace("_", "").isalnum():
            raise ValueError("Nom d'outil invalide.")
        return name

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        name = self._name(spec.name)
        if name in self._tools and not replace:
            raise ValueError(f"Outil déjà enregistré : {name}")
        self._tools[name] = spec

    def catalog(self, *, profile: str = "") -> list[dict[str, Any]]:
        return [
            self._tools[name].public_dict(profile=profile)
            for name in sorted(self._tools)
            if not self._tools[name].profiles or profile in self._tools[name].profiles
        ]

    def _validate(self, spec: ToolSpec, arguments: dict[str, Any]) -> None:
        schema = spec.schema if isinstance(spec.schema, dict) else {}
        required = schema.get("required", [])
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError("Argument(s) requis manquant(s) : " + ", ".join(missing))

        properties = schema.get("properties", {})
        python_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for name, value in arguments.items():
            expected = properties.get(name, {}).get("type")
            expected_type = python_types.get(expected)
            if expected_type and not isinstance(value, expected_type):
                raise TypeError(f"Argument '{name}' : type {expected} attendu.")

    @staticmethod
    def _normalize_response(value: Any) -> ToolResponse:
        if isinstance(value, ToolResponse):
            return value
        if isinstance(value, dict):
            return ToolResponse(
                message=str(value.get("message", "")),
                success=bool(value.get("success", True)),
                break_loop=bool(value.get("break_loop", False)),
                additional=dict(value.get("additional") or {}),
                error=value.get("error"),
            )
        return ToolResponse(message=str(value))

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        profile: str = "manager",
    ) -> ToolResponse:
        tool_name = self._name(name)
        if tool_name not in self._tools:
            return ToolResponse(
                message=f"Outil introuvable : {tool_name}",
                success=False,
                error="tool_not_found",
            )

        spec = self._tools[tool_name]
        if spec.profiles and profile not in spec.profiles:
            return ToolResponse(
                message=f"Outil '{tool_name}' bloqué pour le profil '{profile}'.",
                success=False,
                error="profile_blocked",
            )

        for action in spec.permissions:
            permission = self.permissions.check(action, profile=profile)
            if permission.decision == Decision.BLOCKED:
                return ToolResponse(
                    message=permission.reason,
                    success=False,
                    error="permission_blocked",
                )
            if permission.decision == Decision.APPROVAL_REQUIRED:
                return ToolResponse(
                    message=permission.reason,
                    success=False,
                    additional={"approval_required": True, "action": action},
                    error="approval_required",
                )

        tool_args = dict(arguments or {})
        try:
            self._validate(spec, tool_args)
            event = self.extensions.emit(
                "tool.before_execute",
                {"tool": tool_name, "profile": profile, "arguments": tool_args},
            )
            tool_args = dict(event.data.get("arguments") or tool_args)
            response = self._normalize_response(spec.handler(**tool_args))
            self.extensions.emit(
                "tool.after_execute",
                {"tool": tool_name, "profile": profile, "response": response},
            )
            return response
        except Exception as exc:
            self.extensions.emit(
                "tool.error",
                {"tool": tool_name, "profile": profile, "error": str(exc)},
            )
            return ToolResponse(
                message=f"Échec de l'outil '{tool_name}' : {exc}",
                success=False,
                error=str(exc),
            )

