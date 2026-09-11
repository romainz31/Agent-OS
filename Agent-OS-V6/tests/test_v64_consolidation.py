from __future__ import annotations

from types import SimpleNamespace

from agentos.runtime_recovery import RuntimeRecoveryService
from agentos.runtime_views import RuntimeViewService


def test_task_payload():
    task = SimpleNamespace(
        id="task_1",
        title="Test",
        description="Description",
        worker="developer",
        status="completed",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:01+00:00",
        result="ok",
        result_data={"x": 1},
        error=None,
        depends_on=[],
        metadata={"mission_id": "mission_1"},
    )

    payload = RuntimeViewService.task_payload(task)

    assert payload["id"] == "task_1"
    assert payload["result_data"] == {"x": 1}
    assert payload["metadata"] == {"mission_id": "mission_1"}


def test_recovery_report():
    recovery = {
        "task_recovery": {
            "interrupted": ["task_1"],
            "submitted": ["task_1"],
        },
        "planning_recovery": {},
        "repair_recovery": {},
        "active_missions": ["M-001"],
    }

    lines = RuntimeRecoveryService.report_lines(
        recovery
    )

    assert any("M-001" in line for line in lines)
    assert any(
        "Tâches interrompues" in line
        for line in lines
    )


def main():
    test_task_payload()
    test_recovery_report()
    print("test_v64_consolidation: OK")


if __name__ == "__main__":
    main()
