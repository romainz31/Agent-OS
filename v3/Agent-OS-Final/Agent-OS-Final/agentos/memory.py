from __future__ import annotations
from datetime import datetime, timezone
from agentos.config import DATA_DIR
from agentos.storage import JsonStore

class Memory:
    def __init__(self) -> None:
        self.store = JsonStore(DATA_DIR / "memory.json", {"session": [], "long_term": []})
        self.data = self.store.load()
    def _now(self): return datetime.now(timezone.utc).isoformat()
    def add_session(self, role: str, content: str) -> None:
        self.data["session"].append({"role": role, "content": content, "at": self._now()})
        self.data["session"] = self.data["session"][-20:]
        self.store.save(self.data)
    def remember(self, text: str) -> None:
        text = text.strip()
        if text and text not in [x["content"] for x in self.data["long_term"]]:
            self.data["long_term"].append({"content": text, "at": self._now()})
            self.store.save(self.data)
    def maybe_remember(self, text: str) -> None:
        markers = ("souviens-toi", "retiens que", "mémorise", "memorise", "je préfère", "je prefere", "à l'avenir", "a l'avenir")
        if any(m in text.lower() for m in markers): self.remember(text)
    def context(self) -> str:
        lt = "\n".join(f"- {x['content']}" for x in self.data["long_term"][-15:]) or "(vide)"
        sess = "\n".join(f"{x['role']}: {x['content']}" for x in self.data["session"][-8:]) or "(vide)"
        return f"MÉMOIRE LONGUE DURÉE:\n{lt}\n\nSESSION RÉCENTE:\n{sess}"
    def format(self) -> str: return self.context()
