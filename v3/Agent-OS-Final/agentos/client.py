from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AgentOSClientError(RuntimeError):
    pass


class AgentOSUnavailable(AgentOSClientError):
    pass


class AgentOSClient:
    """Client HTTP léger pour parler au runtime unique Agent-OS."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        *,
        client_id: str | None = None,
    ) -> None:
        self.base_url = (
            str(base_url)
            .strip()
            .rstrip("/")
        )

        if not self.base_url:
            raise ValueError(
                "URL Agent-OS vide."
            )

        self.client_id = (
            str(client_id).strip()
            if client_id
            else (
                "cli-"
                + uuid.uuid4().hex
            )
        )

    # =========================================================
    # HTTP
    # =========================================================

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        path = (
            "/" + path.lstrip("/")
        )

        url = (
            self.base_url
            + path
        )

        if query:
            clean_query = {
                key: value
                for key, value
                in query.items()
                if value is not None
            }

            if clean_query:
                url += (
                    "?"
                    + urlencode(
                        clean_query
                    )
                )

        data = None

        headers = {
            "Accept": "application/json",
            "X-AgentOS-Client": (
                self.client_id
            ),
        }

        if payload is not None:
            data = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")

            headers[
                "Content-Type"
            ] = (
                "application/json; charset=utf-8"
            )

        request = Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urlopen(
                request,
                timeout=timeout,
            ) as response:
                raw = response.read()

        except HTTPError as exc:
            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )
                parsed = json.loads(
                    body
                )
                detail = (
                    parsed.get("detail")
                    or parsed.get("message")
                    or body
                )
            except Exception:
                detail = str(exc)

            raise AgentOSClientError(
                f"API Agent-OS : {detail}"
            ) from exc

        except URLError as exc:
            reason = getattr(
                exc,
                "reason",
                exc,
            )

            raise AgentOSUnavailable(
                "Serveur Agent-OS inaccessible : "
                f"{reason}"
            ) from exc

        except TimeoutError as exc:
            raise AgentOSUnavailable(
                "Le serveur Agent-OS ne répond pas."
            ) from exc

        if not raw:
            return None

        try:
            return json.loads(
                raw.decode(
                    "utf-8"
                )
            )
        except Exception as exc:
            raise AgentOSClientError(
                "Réponse Agent-OS invalide."
            ) from exc

    # =========================================================
    # PUBLIC METHODS
    # =========================================================

    def health(
        self,
    ) -> dict[str, Any]:
        result = self._request(
            "/api/health",
            timeout=3.0,
        )

        return dict(
            result
            or {}
        )

    def status(
        self,
    ) -> dict[str, Any]:
        result = self._request(
            "/api/status",
            timeout=5.0,
        )

        return dict(
            result
            or {}
        )

    def chat(
        self,
        message: str,
    ) -> dict[str, Any]:
        value = str(
            message
        ).strip()

        if not value:
            raise ValueError(
                "Le message est vide."
            )

        result = self._request(
            "/api/chat",
            method="POST",
            payload={
                "message": value,
            },
            timeout=600.0,
        )

        return dict(
            result
            or {}
        )

    def notifications(
        self,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        result = self._request(
            "/api/notifications",
            query={
                "limit": limit,
            },
            timeout=5.0,
        )

        return dict(
            result
            or {}
        )
