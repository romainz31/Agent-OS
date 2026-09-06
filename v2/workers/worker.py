"""
Workers Agent-OS V2.

Contient l'interface de base utilisée par tous les workers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class WorkerResult:
    """
    Résultat standardisé produit par un worker.
    """

    success: bool

    message: str

    data: Optional[Dict[str, Any]] = None

    error: Optional[str] = None


class Worker(ABC):
    """
    Classe de base de tous les workers Agent-OS.
    """

    name: str = "worker"

    description: str = ""

    @abstractmethod
    def execute(
        self,
        task: Dict[str, Any],
    ) -> WorkerResult:
        """
        Exécute une tâche.

        Chaque worker doit retourner un WorkerResult.
        """

        raise NotImplementedError