from __future__ import annotations

import requests


class OpenHandsBridge:
    """V8.0: health/compatibility bridge only. Automatic coding delegation stays opt-in."""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key.strip()

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def status(self) -> dict:
        if not self.configured:
            return {"configured": False, "ok": False, "mode": "agent-server", "auto_delegate": False}
        headers = {"X-Session-API-Key": self.api_key} if self.api_key else {}
        checks = ["/api/server/details", "/docs"]
        last_error = ""
        for path in checks:
            try:
                response = requests.get(self.base_url + path, headers=headers, timeout=3)
                if response.status_code < 500:
                    return {
                        "configured": True,
                        "ok": response.status_code < 400,
                        "status_code": response.status_code,
                        "mode": "agent-server",
                        "auto_delegate": False,
                    }
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:
                last_error = str(exc)
        return {
            "configured": True,
            "ok": False,
            "error": last_error,
            "mode": "agent-server",
            "auto_delegate": False,
        }
