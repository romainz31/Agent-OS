"""
Décisions structurées du Manager Agent-OS V2.

Le LLM propose une décision.
Python la valide avant toute action.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


VALID_ACTIONS = {
    "conversation",
    "create_task",
    "approval_required",
    "blocked",
}

VALID_PRIORITIES = {
    "low",
    "normal",
    "high",
    "critical",
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

    priority: str = "normal"
    deadline: Optional[str] = None
    assigned_agent: Optional[str] = None

    required_approval: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManagerDecision":
        """
        Transforme la réponse du LLM en décision validée.
        """

        if not isinstance(data, dict):
            raise ValueError("La décision du Manager doit être un objet JSON.")

        action = str(data.get("action", "conversation")).strip().lower()

        if action not in VALID_ACTIONS:
            raise ValueError(
                f"Action Manager inconnue : {action}. "
                f"Actions autorisées : {sorted(VALID_ACTIONS)}"
            )

        priority = str(data.get("priority", "normal")).strip().lower()

        if priority not in VALID_PRIORITIES:
            priority = "normal"

        response = str(data.get("response", "")).strip()

        title = data.get("title")
        if title is not None:
            title = str(title).strip() or None

        description = data.get("description")
        if description is not None:
            description = str(description).strip() or None

        deadline = data.get("deadline")
        if deadline is not None:
            deadline = str(deadline).strip() or None

        assigned_agent = data.get("assigned_agent")
        if assigned_agent is not None:
            assigned_agent = str(assigned_agent).strip() or None

        required_approval = data.get("required_approval")
        if required_approval is not None:
            required_approval = str(required_approval).strip() or None

        metadata = data.get("metadata", {})

        if not isinstance(metadata, dict):
            metadata = {}

        return cls(
            action=action,
            response=response,
            title=title,
            description=description,
            priority=priority,
            deadline=deadline,
            assigned_agent=assigned_agent,
            required_approval=required_approval,
            metadata=metadata,
        )

    def validate(self) -> None:
        """
        Vérifie la cohérence de la décision.
        """

        if self.action == "create_task":
            if not self.title:
                raise ValueError(
                    "Une création de tâche nécessite un titre."
                )

            if not self.description:
                raise ValueError(
                    "Une création de tâche nécessite une description."
                )

        if self.action == "approval_required":
            if not self.required_approval:
                raise ValueError(
                    "Une demande d'approbation doit préciser "
                    "ce qui nécessite l'approbation."
                )

        if self.action == "blocked":
            if not self.response:
                self.response = (
                    "Cette action est bloquée par les règles de sécurité "
                    "du Manager."
                )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit la décision en dictionnaire.
        """

        return {
            "action": self.action,
            "response": self.response,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "deadline": self.deadline,
            "assigned_agent": self.assigned_agent,
            "required_approval": self.required_approval,
            "metadata": self.metadata,
        }