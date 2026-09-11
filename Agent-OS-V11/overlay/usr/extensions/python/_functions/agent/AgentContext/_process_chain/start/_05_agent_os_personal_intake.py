from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent import LoopData
from helpers.extension import Extension
from helpers.llm_result import LLMResult
from usr.plugins.agent_os_memory.helpers.intake import render_direct_reply, semantic_intake
from usr.plugins.agent_os_memory.helpers.runtime import context_id, data_path, get_store, plugin_config


HANDLED_STATUSES = {
    "captured",
    "query_ready",
    "clarification_required",
    "updated",
    "forgotten",
}

MARKER = "PAUL_IDENTITY_GUARD_V11_6"


def _raw_message(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return str(getattr(value, "message", "") or "").strip()


def _profile_text(agent: Any) -> str:
    return str(getattr(getattr(agent, "config", None), "profile", "") or "").strip()


def _is_paul(agent: Any) -> bool:
    if not agent or getattr(agent, "number", -1) != 0:
        return False

    profile = _profile_text(agent).casefold().replace("\\", "/")
    profile_parts = [part for part in re.split(r"[:/]", profile) if part]
    if profile_parts and profile_parts[-1] == "paul":
        return True

    if str(getattr(agent, "agent_name", "") or "").strip().casefold() == "paul":
        return True

    # Dernier filet de sécurité : le prompt propre au profil contient un marqueur
    # explicite. Cela évite qu'une variation de représentation de config.profile
    # désactive silencieusement l'intake.
    try:
        specifics = str(agent.read_prompt("agent.system.main.specifics.md") or "")
        if MARKER in specifics:
            return True
    except Exception:
        pass
    return False


def _debug(config: dict[str, Any], event: str, payload: dict[str, Any]) -> None:
    if not bool(config.get("semantic_intake_debug", True)):
        return
    try:
        path = Path(data_path()).parent / "intake_runtime.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 512_000:
            backup = path.with_suffix(".log.1")
            try:
                backup.unlink(missing_ok=True)
            except Exception:
                pass
            path.replace(backup)
        row = {
            "ts": datetime.now().astimezone().isoformat(),
            "event": event,
            **payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


class AgentOSPersonalIntakeGate(Extension):
    """Barrière mémoire exécutée AVANT AgentContext._process_chain.

    Qwen ne fait ici que du routage/extraction. Pour un tour personnel traité,
    le monologue conversationnel Agent Zero n'est jamais lancé : cela empêche
    Paul de reprendre les faits de Romain à la première personne.
    """

    async def execute(self, data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if not isinstance(data, dict):
            return

        args = data.get("args")
        call_kwargs = data.get("kwargs") if isinstance(data.get("kwargs"), dict) else {}
        if not isinstance(args, tuple) or len(args) < 3:
            return

        target_agent = args[1]
        message_obj = args[2]
        user_turn = bool(args[3]) if len(args) >= 4 else bool(call_kwargs.get("user", True))
        if not user_turn or not _is_paul(target_agent):
            return

        config = plugin_config(target_agent) or {}
        if not bool(config.get("semantic_intake_enabled", True)):
            return

        message = _raw_message(message_obj)
        if not message:
            return

        try:
            history = target_agent.history.output_text(human_label="Romain", ai_label="Paul")
        except Exception:
            history = ""

        async def extractor_model_call(*, system: str, message: str):
            # 1) modèle Utility configuré, si disponible.
            try:
                return await target_agent.call_utility_model(
                    system=system,
                    message=message,
                    background=True,
                )
            except Exception as utility_error:
                _debug(config, "utility_fallback", {"error": str(utility_error)[:500]})

            # 2) modèle de chat actif, appelé DIRECTEMENT en mode system/user.
            # On n'entre pas dans le monologue Agent Zero et on ne lui donne pas
            # la personnalité de Paul : Qwen reste un parseur sémantique isolé.
            model = target_agent.get_chat_model()
            response, _reasoning = await model.unified_call(
                system_message=system,
                user_message=message,
                response_callback=None,
                rate_limiter_callback=None,
            )
            return response

        _debug(
            config,
            "incoming",
            {"profile": _profile_text(target_agent), "message": message},
        )

        try:
            outcome = await semantic_intake(
                agent=target_agent,
                store=get_store(target_agent),
                message=message,
                context_id=context_id(target_agent),
                config=config,
                history=history,
                model_call=extractor_model_call,
            )
        except Exception as exc:
            _debug(config, "intake_exception", {"message": message, "error": repr(exc)[:1000]})
            if bool(config.get("semantic_intake_strict_errors", True)):
                reply = "J'ai rencontré une erreur dans ma mémoire personnelle sur ce message. Je préfère ne rien inventer ni l'enregistrer de travers."
                user_history = target_agent.hist_add_user_message(message_obj)
                target_agent.loop_data = LoopData(user_message=user_history)
                assistant_message = target_agent.hist_add_ai_response(reply, llm_result=LLMResult.non_llm())
                try:
                    target_agent.context.log.log(type="response", content=reply, finished=True, update_progress="none", id=assistant_message.id)
                except Exception:
                    pass
                data["result"] = reply
            return

        _debug(
            config,
            "outcome",
            {
                "message": message,
                "status": outcome.status,
                "plan": outcome.raw_plan,
            },
        )

        if outcome.status == "extractor_unavailable" and bool(config.get("semantic_intake_strict_errors", True)):
            reply = "Je n'arrive pas à joindre le modèle d'extraction de ma mémoire. Je préfère ne rien inventer sur ce message."
        elif outcome.status not in HANDLED_STATUSES:
            return
        else:
            reply = render_direct_reply(outcome)
        if not reply:
            return

        # Historique : conserver le message de Romain et une réponse de Paul en
        # deuxième personne. Aucun appel au LLM conversationnel n'est effectué.
        user_history = target_agent.hist_add_user_message(message_obj)
        target_agent.loop_data = LoopData(user_message=user_history)
        assistant_message = target_agent.hist_add_ai_response(
            reply,
            llm_result=LLMResult.non_llm(),
        )

        # WebUI : le court-circuit évite les extensions de streaming normales ;
        # on publie donc explicitement la bulle de réponse.
        try:
            target_agent.context.log.log(
                type="response",
                content=reply,
                finished=True,
                update_progress="none",
                id=assistant_message.id,
            )
        except Exception:
            pass

        _debug(config, "direct_reply", {"message": message, "reply": reply})

        # @extensible : définir result empêche l'appel de _process_chain original.
        data["result"] = reply
