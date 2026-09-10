"""Compatibility layer for Agent-OS <= V10.1.

V10.2 replaced the separate LifeJournal store with PersonalTimeline. Existing
imports keep working so old API routes/tests/extensions do not break.
"""
from agentos.personal_timeline import PersonalTimeline, canon, norm


class LifeJournal(PersonalTimeline):
    pass


__all__ = ["LifeJournal", "PersonalTimeline", "canon", "norm"]
