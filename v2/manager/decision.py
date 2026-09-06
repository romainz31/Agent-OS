"""
Décisions structurées du Manager Agent-OS V2.

Le LLM propose une décision.
Python la valide et la normalise avant toute action.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


VALID_ACTIONS = {
    "conversation",
    "create_task",
    "create_mission",
    "approval_required",
    "blocked",
}


VALID_PRIORITIES = {
    "low",
    "normal",
    "high",
    "critical",
}


# ------------------------------------------------------------
# ALIAS D'ACTIONS
# ------------------------------------------------------------

ACTION_ALIASES = {
    "response": "conversation",
    "chat": "conversation",
    "answer": "conversation",
    "reply": "conversation",

    "analysis": "create_task",
    "analyze": "create_task",
    "analyse": "create_task",

    "research": "create_task",
    "recherche": "create_task",

    "code": "create_task",
    "coding": "create_task",
    "programming": "create_task",
    "programmation": "create_task",

    "test": "create_task",
    "testing": "create_task",
    "validation": "create_task",

    "mission": "create_mission",
    "workflow": "create_mission",

    "approval": "approval_required",
    "approve": "approval_required",

    "deny": "blocked",
    "forbidden": "blocked",
}


@dataclass
class ManagerDecision:
    """
    Décision produite par le cerveau du Manager.
    """

    action: str

    response: str = ""

    title: Optional[str] = None

    description: Optional[str] = None

    objective: Optional[str] = None

    priority: str = "normal"

    deadline: Optional[str] = None

    assigned_agent: Optional[str] = None

    required_approval: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
    ) -> "ManagerDecision":

        if not isinstance(data, dict):
            raise ValueError(
                "La décision du Manager doit être "
                "un objet JSON."
            )

        raw_action = str(
            data.get(
                "action",
                "conversation",
            )
        ).strip().lower()

        # --------------------------------------------------------
        # NORMALISATION ACTION
        # --------------------------------------------------------

        action = ACTION_ALIASES.get(
            raw_action,
            raw_action,
        )

        if action not in VALID_ACTIONS:

            raise ValueError(
                f"Action Manager inconnue : "
                f"{raw_action}. "
                f"Actions autorisées : "
                f"{sorted(VALID_ACTIONS)}"
            )

        priority = str(
            data.get(
                "priority",
                "normal",
            )
        ).strip().lower()

        if priority not in VALID_PRIORITIES:
            priority = "normal"

        response = str(
            data.get(
                "response",
                "",
            )
        ).strip()

        title = data.get("title")

        if title is not None:
            title = str(title).strip() or None

        description = data.get("description")

        if description is not None:
            description = (
                str(description).strip()
                or None
            )

        objective = data.get("objective")

        if objective is not None:
            objective = (
                str(objective).strip()
                or None
            )

        deadline = data.get("deadline")

        if deadline is not None:
            deadline = (
                str(deadline).strip()
                or None
            )

        assigned_agent = data.get(
            "assigned_agent"
        )

        if assigned_agent is not None:
            assigned_agent = (
                str(assigned_agent)
                .strip()
                or None
            )

        required_approval = data.get(
            "required_approval"
        )

        if required_approval is not None:
            required_approval = (
                str(required_approval)
                .strip()
                or None
            )

        metadata = data.get(
            "metadata",
            {},
        )

        if not isinstance(metadata, dict):
            metadata = {}

        return cls(
            action=action,
            response=response,
            title=title,
            description=description,
            objective=objective,
            priority=priority,
            deadline=deadline,
            assigned_agent=assigned_agent,
            required_approval=required_approval,
            metadata=metadata,
        )

    def validate(self) -> None:

        if self.action == "create_task":

            if not self.title:
                raise ValueError(
                    "Une création de tâche nécessite "
                    "un titre."
                )

            if not self.description:
                raise ValueError(
                    "Une création de tâche nécessite "
                    "une description."
                )

        if self.action == "create_mission":

            if not self.title:
                raise ValueError(
                    "Une création de mission nécessite "
                    "un titre."
                )

            if not self.objective:
                raise ValueError(
                    "Une création de mission nécessite "
                    "un objectif."
                )

            if not self.description:
                raise ValueError(
                    "Une création de mission nécessite "
                    "la description de la première étape."
                )

        if self.action == "approval_required":

            if not self.required_approval:
                raise ValueError(
                    "Une demande d'approbation doit "
                    "préciser ce qui nécessite "
                    "l'approbation."
                )

        if self.action == "blocked":

            if not self.response:
                self.response = (
                    "Cette action est bloquée "
                    "par les règles de sécurité "
                    "du Manager."
                )

    def to_dict(self) -> Dict[str, Any]:

        return {
            "action": self.action,
            "response": self.response,
            "title": self.title,
            "description": self.description,
            "objective": self.objective,
            "priority": self.priority,
            "deadline": self.deadline,
            "assigned_agent": self.assigned_agent,
            "required_approval": (
                self.required_approval
            ),
            "metadata": self.metadata,
        }