from __future__ import annotations
import json, threading
from pathlib import Path
from typing import Any

class JsonStore:
    def __init__(self, path: Path, default: Any) -> None:
        self.path, self.default = path, default
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
    def _default(self):
        return json.loads(json.dumps(self.default))
    def load(self):
        with self.lock:
            if not self.path.exists(): return self._default()
            try: return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): return self._default()
    def save(self, data):
        with self.lock:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
