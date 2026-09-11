from __future__ import annotations

import requests


class AgentZeroBridge:
    def __init__(self, base_url: str, api_key: str = "", timeout: int = 180) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def status(self) -> dict:
        if not self.configured:
            return {"configured": False, "ok": False, "mode": "external-api"}
        headers = {"X-API-KEY": self.api_key} if self.api_key else {}
        try:
            response = requests.get(self.base_url + "/", headers=headers, timeout=3)
            return {
                "configured": True,
                "ok": response.status_code < 500,
                "status_code": response.status_code,
                "mode": "external-api",
            }
        except Exception as exc:
            return {"configured": True, "ok": False, "error": str(exc), "mode": "external-api"}

    def send(self, message: str, context_id: str = "") -> dict:
        if not self.configured:
            raise RuntimeError("Agent Zero n'est pas configuré.")
        payload: dict[str, str] = {"message": message}
        if context_id:
            payload["context_id"] = context_id
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        response = requests.post(
            self.base_url + "/api_message",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code == 404 and context_id:
            payload.pop("context_id", None)
            response = requests.post(
                self.base_url + "/api_message",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        response.raise_for_status()
        data = response.json()
        return {
            "response": str(data.get("response", "")).strip(),
            "context_id": str(data.get("context_id", "") or ""),
        }
