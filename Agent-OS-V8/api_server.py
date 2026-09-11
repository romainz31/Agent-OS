from __future__ import annotations

import uvicorn

from agentos.config import AGENTOS_HOST, AGENTOS_PORT


def main() -> None:
    print("=" * 64)
    print("AGENT-OS V8.0 — HYBRID INTEGRATION KERNEL")
    print("=" * 64)
    print(f"Interface : http://{AGENTOS_HOST}:{AGENTOS_PORT}")
    print(f"API       : http://{AGENTOS_HOST}:{AGENTOS_PORT}/docs")
    print("Paul reste le Manager. Les moteurs externes sont des workers.")
    print()
    uvicorn.run(
        "agentos.api:app",
        host=AGENTOS_HOST,
        port=AGENTOS_PORT,
        reload=False,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
