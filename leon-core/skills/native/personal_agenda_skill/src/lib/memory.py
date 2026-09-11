from bridges.python.src.sdk.memory import Memory
from typing import TypedDict


class AgendaEvent(TypedDict, total=False):
    title: str
    date: str
    time: str


events_memory = Memory({
    'name': 'personal_agenda_events',
    'default_memory': []
})


def add_event(event: AgendaEvent) -> None:
    events = events_memory.read() or []
    events.append(event)
    events_memory.write(events)


def get_events() -> list[AgendaEvent]:
    return events_memory.read() or []
