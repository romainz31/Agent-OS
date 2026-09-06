"""
Manager principal Agent-OS V2.

Le Manager est l'unique interlocuteur humain.

Responsabilités :
- conversation
- compréhension des demandes
- création des tâches
- lancement des tâches
- suivi des tâches
- permissions
- événements
- orchestration des workers
"""

from typing import Any, Dict, List, Optional
import json

from v2.brain.llm import LLM
from v2.config import MANAGER_SYSTEM_PROMPT
from v2.events.event_bus import EventBus
from v2.memory.memory import MemoryStore
from v2.permissions.permissions import PermissionEngine
from v2.tasks.task_manager import TaskManager
from v2.workers.worker import Worker
from v2.workers.worker_engine import WorkerEngine

from v2.manager.decision import ManagerDecision


class Manager:
    """
    Manager central d'Agent-OS.
    """

    def __init__(self) -> None:
        self.llm = LLM()
        self.memory = MemoryStore()
        self.tasks = TaskManager()
        self.permissions = PermissionEngine()

        self.events = EventBus()

        self.workers = WorkerEngine(
            task_manager=self.tasks,
            event_bus=self.events,
        )

        self._register_event_handlers()

    # ============================================================
    # EVENTS
    # ============================================================

    def _register_event_handlers(self) -> None:

        self.events.subscribe(
            "task.created",
            self._on_task_created,
        )

        self.events.subscribe(
            "task.started",
            self._on_task_started,
        )

        self.events.subscribe(
            "task.completed",
            self._on_task_completed,
        )

        self.events.subscribe(
            "task.failed",
            self._on_task_failed,
        )

    # ============================================================
    # WORKERS
    # ============================================================

    def register_worker(
        self,
        worker: Worker,
    ) -> None:
        """
        Enregistre un worker.
        """

        self.workers.register(
            worker
        )

    def get_worker_names(
        self,
    ) -> List[str]:
        """
        Retourne les workers disponibles.
        """

        return list(
            self.workers.workers.keys()
        )

    # ============================================================
    # CHAT
    # ============================================================

    def chat(
        self,
        message: str,
    ) -> str:

        if not isinstance(
            message,
            str,
        ):
            message = str(message)

        message = message.strip()

        if not message:
            return "Je n'ai rien reçu."

        # --------------------------------------------------------
        # Mémoire conversation
        # --------------------------------------------------------

        self.memory.add(
            "conversation",
            message,
            metadata={
                "role": "user",
            },
        )

        # --------------------------------------------------------
        # Contexte
        # --------------------------------------------------------

        context = (
            self.memory
            .build_manager_context()
        )

        tasks = self._format_tasks()
        workers = self._format_workers()

        prompt = (
            self._build_decision_prompt(
                message=message,
                context=context,
                tasks=tasks,
                workers=workers,
            )
        )

        # --------------------------------------------------------
        # LLM
        # --------------------------------------------------------

        try:

            raw_response = self.llm.chat(
                system_prompt=(
                    MANAGER_SYSTEM_PROMPT
                ),
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            decision = (
                self._parse_decision(
                    raw_response
                )
            )

        except Exception as exc:

            print(
                "[MANAGER] "
                f"Erreur de décision : {exc}"
            )

            return (
                "Je n'ai pas réussi à interpréter "
                "correctement ta demande. "
                "Aucune action n'a été exécutée."
            )

        # --------------------------------------------------------
        # Exécution
        # --------------------------------------------------------

        result = (
            self._execute_decision(
                decision
            )
        )

        # --------------------------------------------------------
        # Mémoire
        # --------------------------------------------------------

        self.memory.add(
            "conversation",
            result,
            metadata={
                "role": "manager",
                "action": decision.action,
            },
        )

        return result

    # ============================================================
    # DECISION PROMPT
    # ============================================================

    def _build_decision_prompt(
        self,
        message: str,
        context: str,
        tasks: str,
        workers: str,
    ) -> str:

        return f"""
Tu es le cerveau décisionnel du Manager d'Agent-OS.

Tu es le seul interlocuteur visible de l'utilisateur.

Tu dois comprendre son intention et choisir l'action appropriée.

============================================================
ACTIONS
============================================================

1. conversation
2. create_task
3. approval_required
4. blocked

============================================================
RÈGLES
============================================================

- Discussion normale => conversation.
- Question => conversation.
- Demande personnelle => conversation.
- Demande de travail concrète => create_task.
- Action nécessitant une validation humaine
  => approval_required.
- Action interdite => blocked.

NE FAIS JAMAIS croire à l'utilisateur qu'un travail
a été effectué si aucun worker ne l'a réellement effectué.

============================================================
WORKERS DISPONIBLES
============================================================

{workers}

La liste ci-dessus contient uniquement les workers
réellement enregistrés.

NE JAMAIS inventer un worker.

Si une tâche peut être exécutée par un worker disponible,
sélectionne-le obligatoirement dans assigned_agent.

Pour une tâche de test générique, si "demo" existe,
utilise :

"assigned_agent": "demo"

Si aucun worker ne convient :

"assigned_agent": null

============================================================
TÂCHES EXISTANTES
============================================================

{tasks}

============================================================
MÉMOIRE
============================================================

{context}

============================================================
ÉCHÉANCE
============================================================

Si aucune échéance n'est donnée :

"deadline": null

Priorités autorisées :

- low
- normal
- high
- critical

============================================================
MESSAGE UTILISATEUR
============================================================

{message}

============================================================
RÉPONSE
============================================================

Réponds UNIQUEMENT avec du JSON valide.

Format conversation :

{{
    "action": "conversation",
    "response": "réponse naturelle",
    "title": null,
    "description": null,
    "priority": "normal",
    "deadline": null,
    "assigned_agent": null,
    "required_approval": null,
    "metadata": {{}}
}}

Format tâche :

{{
    "action": "create_task",
    "response": "",
    "title": "titre",
    "description": "description précise",
    "priority": "normal",
    "deadline": null,
    "assigned_agent": "demo",
    "required_approval": null,
    "metadata": {{}}
}}

NE METS AUCUN TEXTE EN DEHORS DU JSON.
"""

    # ============================================================
    # WORKERS FORMAT
    # ============================================================

    def _format_workers(self) -> str:

        workers = self.get_worker_names()

        if not workers:
            return "Aucun worker disponible."

        lines = []

        for worker_name in workers:

            worker = (
                self.workers.get_worker(
                    worker_name
                )
            )

            description = ""

            if worker is not None:

                description = (
                    getattr(
                        worker,
                        "description",
                        "",
                    )
                    or ""
                )

            if description:

                lines.append(
                    f"- {worker_name} : "
                    f"{description}"
                )

            else:

                lines.append(
                    f"- {worker_name}"
                )

        return "\n".join(lines)

    # ============================================================
    # PARSING
    # ============================================================

    def _parse_decision(
        self,
        raw_response: str,
    ) -> ManagerDecision:

        if not isinstance(
            raw_response,
            str,
        ):
            raise ValueError(
                "La réponse du LLM doit être "
                "une chaîne."
            )

        text = raw_response.strip()

        if text.startswith("```"):

            lines = text.splitlines()

            if (
                lines
                and lines[0]
                .strip()
                .startswith("```")
            ):
                lines = lines[1:]

            if (
                lines
                and lines[-1].strip()
                == "```"
            ):
                lines = lines[:-1]

            text = "\n".join(
                lines
            ).strip()

            if text.lower().startswith(
                "json"
            ):
                text = text[4:].strip()

        try:

            data = json.loads(
                text
            )

        except json.JSONDecodeError as exc:

            raise ValueError(
                f"Réponse JSON invalide : {exc}"
            ) from exc

        decision = (
            ManagerDecision.from_dict(
                data
            )
        )

        decision.validate()

        return decision

    # ============================================================
    # DECISION EXECUTION
    # ============================================================

    def _execute_decision(
        self,
        decision: ManagerDecision,
    ) -> str:

        # --------------------------------------------------------
        # CONVERSATION
        # --------------------------------------------------------

        if decision.action == "conversation":

            return (
                decision.response
                or "D'accord."
            )

        # --------------------------------------------------------
        # CREATE TASK
        # --------------------------------------------------------

        if decision.action == "create_task":

            assigned_agent = (
                decision.assigned_agent
            )

            # ----------------------------------------------------
            # Vérification worker
            # ----------------------------------------------------

            if assigned_agent is not None:

                if (
                    assigned_agent
                    not in self.workers.workers
                ):

                    print(
                        "[MANAGER] Worker demandé "
                        "mais indisponible : "
                        f"{assigned_agent}"
                    )

                    assigned_agent = None

            # ----------------------------------------------------
            # Création
            # ----------------------------------------------------

            task = self.create_task(
                title=(
                    decision.title
                    or "Nouvelle tâche"
                ),
                description=(
                    decision.description
                    or ""
                ),
                priority=decision.priority,
                deadline=decision.deadline,
                assigned_agent=assigned_agent,
                metadata=decision.metadata,
            )

            # ----------------------------------------------------
            # Lancement
            # ----------------------------------------------------

            if assigned_agent:

                started = self.start_task(
                    task["id"]
                )

                if started:

                    return (
                        "Tâche créée et lancée : "
                        f"{task['id']}\n"
                        f"Titre : {task['title']}\n"
                        f"Priorité : "
                        f"{task['priority']}\n"
                        f"Échéance : "
                        f"{task['deadline'] or 'aucune'}\n"
                        f"Worker : "
                        f"{assigned_agent}\n"
                        f"Statut : running"
                    )

                return (
                    f"Tâche créée : "
                    f"{task['id']}\n"
                    f"Titre : {task['title']}\n"
                    f"Worker : "
                    f"{assigned_agent}\n"
                    "Statut : impossible de "
                    "démarrer automatiquement"
                )

            return (
                f"Tâche créée : "
                f"{task['id']}\n"
                f"Titre : {task['title']}\n"
                f"Priorité : "
                f"{task['priority']}\n"
                f"Échéance : "
                f"{task['deadline'] or 'aucune'}\n"
                "Worker : en attente d'affectation\n"
                "Statut : pending"
            )

        # --------------------------------------------------------
        # APPROVAL
        # --------------------------------------------------------

        if (
            decision.action
            == "approval_required"
        ):

            reason = (
                decision.required_approval
                or (
                    "Cette action nécessite "
                    "ton approbation."
                )
            )

            return (
                "Cette action nécessite ton "
                "approbation avant de continuer.\n\n"
                f"Raison : {reason}"
            )

        # --------------------------------------------------------
        # BLOCKED
        # --------------------------------------------------------

        if decision.action == "blocked":

            return (
                decision.response
                or (
                    "Cette action est bloquée "
                    "par les règles de sécurité."
                )
            )

        return "Aucune action effectuée."

    # ============================================================
    # TASK MANAGEMENT
    # ============================================================

    def create_task(
        self,
        title: str,
        description: str,
        priority: str = "normal",
        deadline: Optional[str] = None,
        assigned_agent: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Dict[str, Any]:

        task = self.tasks.create(
            title=title,
            description=description,
            priority=priority,
            deadline=deadline,
            assigned_agent=assigned_agent,
            parent_task_id=parent_task_id,
            metadata=metadata or {},
        )

        task_dict = task.to_dict()

        self.memory.add(
            "tasks",
            (
                f"Tâche créée : "
                f"{task_dict['id']} | "
                f"Titre : "
                f"{task_dict['title']} | "
                f"Priorité : "
                f"{task_dict['priority']} | "
                f"Statut : "
                f"{task_dict['status']} | "
                f"Worker : "
                f"{task_dict.get('assigned_agent') or 'non assigné'}"
            ),
            metadata={
                "event": "task_created",
                "task_id": task_dict["id"],
            },
        )

        self.events.publish(
            "task.created",
            task_dict,
        )

        return task_dict

    def start_task(
        self,
        task_id: str,
    ) -> bool:

        return self.workers.submit(
            task_id
        )

    def get_tasks(
        self,
    ) -> List[Dict[str, Any]]:

        return [
            task.to_dict()
            for task in self.tasks.list()
        ]

    # ============================================================
    # PERMISSIONS
    # ============================================================

    def check_action(
        self,
        action: str,
        **context: Any,
    ) -> Dict[str, Any]:

        permission = (
            self.permissions.check(
                action,
                **context,
            )
        )

        return {
            "action": action,
            "result": (
                permission.result.value
            ),
            "reason": permission.reason,
        }

    # ============================================================
    # EVENTS
    # ============================================================

    def _on_task_created(
        self,
        event: Any,
    ) -> None:

        print(
            "[EVENT] Tâche créée : "
            f"{event.data.get('id')}"
        )

    def _on_task_started(
        self,
        event: Any,
    ) -> None:

        print(
            "[EVENT] Tâche démarrée : "
            f"{event.data.get('task_id')}"
        )

    def _on_task_completed(
        self,
        event: Any,
    ) -> None:

        data = event.data

        task_id = data.get(
            "task_id"
        )

        message = data.get(
            "message",
            "",
        )

        result_data = data.get(
            "data"
        )

        # --------------------------------------------------------
        # Récupération de la tâche
        # --------------------------------------------------------

        task = self.tasks.get(
            task_id
        )

        if task is not None:

            self.tasks.complete(
                task_id=task_id,
                result=message,
                data=result_data,
            )

        # --------------------------------------------------------
        # Mémoire
        # --------------------------------------------------------

        self.memory.add(
            "tasks",
            (
                f"Tâche terminée : "
                f"{task_id} | "
                f"Résultat : {message}"
            ),
            metadata={
                "event": "task_completed",
                "task_id": task_id,
                "result_data": result_data,
            },
        )

        # --------------------------------------------------------
        # Console
        # --------------------------------------------------------

        print(
            "[EVENT] Tâche terminée : "
            f"{task_id}"
        )

        print(
            f"[RESULT] {message}"
        )

        if result_data:

            print(
                "[RESULT DATA] "
                f"{result_data}"
            )

    def _on_task_failed(
        self,
        event: Any,
    ) -> None:

        data = event.data

        task_id = data.get(
            "task_id"
        )

        error = data.get(
            "error",
            "",
        )

        # --------------------------------------------------------
        # Persistance
        # --------------------------------------------------------

        task = self.tasks.get(
            task_id
        )

        if task is not None:

            self.tasks.fail(
                task_id,
                error,
            )

        # --------------------------------------------------------
        # Mémoire
        # --------------------------------------------------------

        self.memory.add(
            "tasks",
            (
                f"Tâche échouée : "
                f"{task_id} | "
                f"Erreur : {error}"
            ),
            metadata={
                "event": "task_failed",
                "task_id": task_id,
            },
        )

        print(
            "[EVENT] Tâche échouée : "
            f"{task_id}"
        )

        print(
            f"[ERROR] {error}"
        )

    # ============================================================
    # TASK FORMAT
    # ============================================================

    def _format_tasks(self) -> str:

        tasks = self.get_tasks()

        if not tasks:
            return "Aucune tâche."

        lines = []

        for task in tasks[-10:]:

            lines.append(
                f"- {task['id']} | "
                f"{task['status']} | "
                f"{task['priority']} | "
                f"{task['title']}"
            )

        return "\n".join(lines)

    # ============================================================
    # STATUS
    # ============================================================

    def status(
        self,
    ) -> Dict[str, Any]:

        tasks = self.get_tasks()

        counts = {
            "total": len(tasks),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "waiting_approval": 0,
            "blocked": 0,
            "cancelled": 0,
        }

        running_task_ids = []

        for task in tasks:

            status = task.get(
                "status"
            )

            if status in counts:
                counts[status] += 1

            if status == "running":

                running_task_ids.append(
                    task["id"]
                )

        return {
            "manager": "online",
            "model": self.llm.model,
            "workers": (
                self.get_worker_names()
            ),
            "running_tasks": (
                running_task_ids
            ),
            "tasks": counts,
        }

    # ============================================================
    # SHUTDOWN
    # ============================================================

    def shutdown(
        self,
    ) -> None:

        self.workers.shutdown()