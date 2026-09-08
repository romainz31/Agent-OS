from __future__ import annotations

import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from agentos.config import DATA_DIR
from agentos.storage import JsonStore


class ResilientWebSearch:
    """Recherche DDGS tolérante aux pannes de backend.

    DDGS peut lever ``No results found`` en mode auto lorsqu'un backend échoue
    avant les autres. On interroge donc plusieurs moteurs séparément et on
    conserve les résultats des moteurs qui fonctionnent réellement.
    """

    BACKENDS = (
        "wikipedia",
        "brave",
        "bing",
        "duckduckgo",
        "yahoo",
        "mojeek",
    )

    REGIONS = (
        "fr-fr",
        "us-en",
    )

    STOPWORDS = {
        "a", "au", "aux", "avec", "ce", "ces", "cette", "dans", "de",
        "des", "du", "elle", "en", "est", "et", "il", "la", "le", "les",
        "leur", "leurs", "lui", "mais", "ne", "non", "on", "ou", "où",
        "par", "pas", "pour", "que", "quel", "quelle", "quels", "quelles",
        "qui", "quoi", "sa", "se", "ses", "son", "sur", "un", "une",
        "y", "s", "t", "d", "l", "m", "n",
    }

    def __init__(self, backend_provider=None) -> None:
        self.backend_provider = backend_provider

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @classmethod
    def simplified_query(cls, query: str) -> str:
        clean = cls._clean(query)
        # Retire les préambules internes éventuellement ajoutés pour un suivi.
        clean = re.sub(
            r"(?i)contexte (?:de la question précédente|conversationnel)\s*:\s*",
            "",
            clean,
        )
        clean = re.sub(r"(?i)question de suivi\s*:\s*", " ", clean)
        tokens = re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", clean)
        kept = []
        for token in tokens:
            normalized = unicodedata.normalize("NFKD", token)
            normalized = "".join(
                c for c in normalized if not unicodedata.combining(c)
            ).lower().strip("'-")
            if not normalized or normalized in cls.STOPWORDS:
                continue
            if token not in kept:
                kept.append(token)
        return " ".join(kept[:18]).strip()

    @classmethod
    def query_variants(cls, query: str) -> list[str]:
        clean = cls._clean(query)
        simplified = cls.simplified_query(clean)
        values = []
        for candidate in (clean, simplified):
            if candidate and candidate not in values:
                values.append(candidate)
        return values

    def _backend_search(
        self,
        *,
        query: str,
        backend: str,
        region: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        if self.backend_provider is not None:
            return list(
                self.backend_provider(
                    query,
                    backend,
                    region,
                    max_results,
                )
                or []
            )

        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError("Le package ddgs n'est pas installé.") from exc

        return list(
            DDGS(timeout=12).text(
                query,
                region=region,
                safesearch="moderate",
                max_results=max_results,
                backend=backend,
            )
            or []
        )

    def search(
        self,
        query: str,
        max_results: int = 8,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        max_results = max(1, int(max_results))
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        attempts: list[dict[str, Any]] = []

        variants = self.query_variants(query)

        for variant_index, variant in enumerate(variants):
            for region in self.REGIONS:
                for backend in self.BACKENDS:
                    if len(collected) >= max_results:
                        break
                    try:
                        raw = self._backend_search(
                            query=variant,
                            backend=backend,
                            region=region,
                            max_results=min(5, max_results),
                        )
                        attempts.append(
                            {
                                "query": variant,
                                "backend": backend,
                                "region": region,
                                "ok": True,
                                "results": len(raw),
                                "error": "",
                            }
                        )
                    except Exception as exc:
                        attempts.append(
                            {
                                "query": variant,
                                "backend": backend,
                                "region": region,
                                "ok": False,
                                "results": 0,
                                "error": str(exc)[:240],
                            }
                        )
                        continue

                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        url = self._clean(item.get("href") or item.get("url"))
                        title = self._clean(item.get("title"))
                        body = self._clean(item.get("body") or item.get("snippet"))
                        key = url or f"{title}|{body[:100]}"
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        collected.append(item)
                        if len(collected) >= max_results:
                            break

                if collected:
                    # Une région fonctionnelle suffit. On évite de multiplier
                    # inutilement les requêtes réseau.
                    break
            if collected:
                break

        return collected[:max_results], attempts


@dataclass
class ReliableWorkerResult:
    success: bool
    message: str
    data: dict[str, Any]
    error: str | None = None


class ReliableResearcherWorker:
    """Researcher de mission utilisant la même recherche robuste que Paul."""

    name = "researcher"

    def __init__(self, llm, permissions) -> None:
        self.llm = llm
        self.permissions = permissions
        self.searcher = ResilientWebSearch()

    def execute(self, task) -> ReliableWorkerResult:
        permission = self.permissions.check("web_search")
        if permission.decision.value != "allowed":
            return ReliableWorkerResult(
                False,
                "Recherche Web interdite.",
                {},
                "permission",
            )

        query = str(task.get("description", "") or "").strip()
        try:
            raw, attempts = self.searcher.search(query, max_results=8)
        except Exception as exc:
            return ReliableWorkerResult(
                False,
                "Recherche Web échouée.",
                {"search_attempts": []},
                str(exc),
            )

        if not raw:
            errors = [
                item.get("error", "")
                for item in attempts
                if not item.get("ok") and item.get("error")
            ]
            detail = errors[-1] if errors else "Aucun résultat exploitable."
            return ReliableWorkerResult(
                False,
                "Recherche Web échouée : aucune source exploitable.",
                {"search_attempts": attempts},
                detail,
            )

        sources = []
        for item in raw:
            url = str(item.get("href") or item.get("url") or "").strip()
            if not url:
                continue
            sources.append(
                {
                    "id": f"S{len(sources) + 1}",
                    "title": str(item.get("title", "") or "").strip(),
                    "url": url,
                    "body": str(item.get("body") or item.get("snippet") or "").strip(),
                }
            )

        context = "\n\n".join(
            f"[{s['id']}] {s['title']}\n{s['body']}\n{s['url']}"
            for s in sources
        )

        try:
            answer = self.llm.chat(
                (
                    "QUESTION:\n"
                    f"{query}\n\n"
                    "RÉSULTATS WEB RÉELS:\n"
                    f"{context}\n\n"
                    "Synthétise en français et cite [S1], [S2]. "
                    "N'invente aucun fait ni aucune source."
                ),
                system=(
                    "Tu es le Researcher d'Agent-OS. Utilise uniquement les "
                    "résultats Web fournis. Si un point n'est pas établi par "
                    "les sources, dis-le explicitement."
                ),
            )
        except Exception as exc:
            return ReliableWorkerResult(
                False,
                "Synthèse impossible.",
                {"sources": sources, "search_attempts": attempts},
                str(exc),
            )

        return ReliableWorkerResult(
            True,
            answer,
            {
                "worker": self.name,
                "sources": sources,
                "search_attempts": attempts,
            },
        )


class ResearchGateway:
    """Recherche factuelle conversationnelle de Paul.

    Cette couche est volontairement séparée des missions longues. Elle sert aux
    questions factuelles pour lesquelles une réponse non vérifiée du LLM serait
    risquée : histoire, personnes, lieux, dates, réglementation, actualité,
    caractéristiques techniques, etc.

    Le résultat est sourcé et injecté dans le fil de conversation afin que les
    questions de suivi restent cohérentes.
    """

    SCHEMA_VERSION = "2"
    MAX_HISTORY = 30
    MAX_SOURCES = 8

    STATUS_COMMANDS = {
        "research status",
        "recherche status",
        "statut recherche",
        "research debug",
    }

    HISTORY_COMMANDS = {
        "research history",
        "historique recherche",
        "historique recherches",
    }

    ENABLE_COMMANDS = {
        "research on",
        "recherche on",
        "active recherche factuelle",
        "active la recherche factuelle",
    }

    DISABLE_COMMANDS = {
        "research off",
        "recherche off",
        "désactive recherche factuelle",
        "desactive recherche factuelle",
        "désactive la recherche factuelle",
        "desactive la recherche factuelle",
    }

    EXPLICIT_RESEARCH_MARKERS = (
        "vérifie sur internet",
        "verifie sur internet",
        "sur internet",
        "sur le web",
        "trouve des sources",
        "avec des sources",
        "source fiable",
        "sources fiables",
    )

    FRESHNESS_MARKERS = (
        "aujourd'hui",
        "aujourdhui",
        "actuellement",
        "en ce moment",
        "dernier ",
        "dernière ",
        "derniere ",
        "récent",
        "recent",
        "actualité",
        "actualite",
        "prix ",
        "tarif ",
        "météo",
        "meteo",
        "loi ",
        "réglementation",
        "reglementation",
        "version actuelle",
    )

    FACTUAL_PREFIXES = (
        "qui est ",
        "qui était ",
        "qui etait ",
        "qui a ",
        "où ",
        "ou ",
        "quand ",
        "quel est ",
        "quelle est ",
        "quels sont ",
        "quelles sont ",
        "combien ",
        "pourquoi ",
        "comment s'est ",
        "comment s est ",
        "comment fonctionne ",
        "comment fonctionnent ",
        "est-ce que ",
        "est ce que ",
        "c'est quoi ",
        "c est quoi ",
        "qu'est-ce que ",
        "qu est ce que ",
        "de quel ",
        "de quelle ",
        "raconte-moi l'histoire ",
        "raconte moi l'histoire ",
        "explique-moi l'histoire ",
        "explique moi l'histoire ",
    )

    VERIFICATION_FOLLOWUPS = (
        "t'es sûr",
        "t es sur",
        "tu es sûr",
        "tu es sur",
        "c'est sûr",
        "c est sur",
        "c'est vrai",
        "c est vrai",
        "y'a pas une erreur",
        "y a pas une erreur",
        "il n'y a pas une erreur",
        "il n y a pas une erreur",
        "ça me paraît faux",
        "ca me parait faux",
        "vérifie ça",
        "verifie ca",
        "vérifie bien",
        "verifie bien",
        "pas plutôt",
        "pas plutot",
        "où exactement",
        "ou exactement",
        "quand exactement",
    )

    PERSONAL_MARKERS = (
        "ma copine",
        "mon copain",
        "ma compagne",
        "mon compagnon",
        "ma femme",
        "mon mari",
        "mon poisson préféré",
        "mon poisson prefere",
        "mes habitudes",
        "mes préférences",
        "mes preferences",
        "mes centres d'intérêt",
        "mes centres d interet",
        "que sais-tu sur moi",
        "que sais tu sur moi",
        "comment je vais",
        "comment je me sens",
        "mon humeur",
        "ma motivation",
        "mon énergie",
        "mon energie",
    )

    OPINION_MARKERS = (
        "tu en penses quoi",
        "qu'en penses-tu",
        "qu en penses tu",
        "ton avis",
        "à ton avis",
        "a ton avis",
        "tu penses quoi",
    )

    OPERATIONAL_MARKERS = (
        "manager status",
        "manager decisions",
        "conversation status",
        "conversation history",
        "memory debug",
        "memory status",
        "mission m-",
        "m-0",
        "agent-os",
        "agent os",
        "workspace/",
        "workspace\\",
    )

    TASK_ACTION_RE = re.compile(
        r"^(?:stp\s+|svp\s+)?(?:"
        r"crée|cree|créer|creer|modifie|modifier|corrige|corriger|"
        r"teste|tester|vérifie|verifie|compile|compiler|"
        r"ajoute|ajouter|supprime|supprimer"
        r")\b",
        flags=re.IGNORECASE,
    )

    VERIFY_RE = re.compile(
        r"^(?:stp\s+|svp\s+)?(?:vérifie|verifie|vérifier|verifier)\b",
        flags=re.IGNORECASE,
    )

    FILE_RE = re.compile(
        r"(?:(?:workspace[\\/])?(?:[A-Za-z0-9_.-]+[\\/])*"
        r"[A-Za-z0-9_.-]+\.[A-Za-z][A-Za-z0-9_-]*)"
    )

    def __init__(
        self,
        *,
        llm,
        permissions,
        conversation_tracker=None,
        store_path: Path | None = None,
        search_provider: Callable[[str, int], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.llm = llm
        self.permissions = permissions
        self.conversation_tracker = conversation_tracker
        self.search_provider = search_provider
        self.searcher = ResilientWebSearch()
        self.lock = threading.RLock()
        self.store = JsonStore(
            store_path or (DATA_DIR / "research.json"),
            {
                "schema_version": self.SCHEMA_VERSION,
                "enabled": True,
                "current": None,
                "last_attempt": None,
                "history": [],
            },
        )
        loaded = self.store.load()
        self.data = loaded if isinstance(loaded, dict) else {}
        self.data.setdefault("schema_version", self.SCHEMA_VERSION)
        self.data.setdefault("enabled", True)
        self.data.setdefault("current", None)
        self.data.setdefault("last_attempt", None)
        self.data.setdefault("history", [])
        if not isinstance(self.data.get("history"), list):
            self.data["history"] = []
        self._save()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clean(text: Any) -> str:
        return " ".join(str(text or "").strip().split())

    @staticmethod
    def _ascii(text: str) -> str:
        value = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(
            char for char in value if not unicodedata.combining(char)
        ).lower()

    @classmethod
    def _normalize(cls, text: str) -> str:
        return " ".join(cls._ascii(cls._clean(text)).split())

    def _save(self) -> None:
        self.data["schema_version"] = self.SCHEMA_VERSION
        self.data["history"] = [
            item
            for item in self.data.get("history", [])[-self.MAX_HISTORY:]
            if isinstance(item, dict)
        ]
        self.store.save(self.data)

    def enabled(self) -> bool:
        return bool(self.data.get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        with self.lock:
            self.data["enabled"] = bool(enabled)
            self._save()

    def current(self) -> dict[str, Any] | None:
        value = self.data.get("current")
        return dict(value) if isinstance(value, dict) else None

    def _has_research_context(self) -> bool:
        current = self.current()
        return bool(current and current.get("query") and current.get("sources"))

    def _conversation_anchor(self) -> str:
        tracker = self.conversation_tracker
        if tracker is None:
            return ""
        try:
            snapshot = tracker.snapshot()
        except Exception:
            return ""
        if not isinstance(snapshot, dict):
            return ""
        topic = self._clean(snapshot.get("topic", ""))
        summary = self._clean(snapshot.get("summary", ""))
        parts = []
        if topic and topic.lower() != "conversation générale":
            parts.append("Sujet : " + topic)
        if summary:
            parts.append("Résumé : " + summary)
        return ". ".join(parts)

    def should_research(self, message: str) -> bool:
        if not self.enabled():
            return False

        clean = self._clean(message)
        normalized = self._normalize(clean)
        if not normalized:
            return False

        if any(self._normalize(marker) in normalized for marker in self.PERSONAL_MARKERS):
            return False

        if any(self._normalize(marker) in normalized for marker in self.OPERATIONAL_MARKERS):
            return False

        if any(self._normalize(marker) in normalized for marker in self.OPINION_MARKERS):
            return False

        if self.TASK_ACTION_RE.search(clean):
            # « Vérifie ce fichier » reste chez Tester, mais « Vérifie si cette
            # information est vraie » est une demande factuelle et doit être
            # sourcée. Les autres verbes de travail restent des missions.
            if self.VERIFY_RE.search(clean):
                if self.FILE_RE.search(clean) or any(
                    marker in normalized
                    for marker in (
                        "workspace", "code", "script", "python",
                        "fichier", "compile", "test unitaire",
                    )
                ):
                    return False
                return True
            return False

        if any(self._normalize(marker) in normalized for marker in self.EXPLICIT_RESEARCH_MARKERS):
            return True

        if any(self._normalize(marker) in normalized for marker in self.FRESHNESS_MARKERS):
            return True

        if any(normalized.startswith(self._normalize(prefix)) for prefix in self.FACTUAL_PREFIXES):
            return True

        verification_followup = any(
            self._normalize(marker) in normalized
            for marker in self.VERIFICATION_FOLLOWUPS
        )
        if verification_followup and (
            self._has_research_context()
            or bool(self._conversation_anchor())
        ):
            return True

        if self._has_research_context():
            # Questions courtes de suivi : « et le chauffeur ? », « où
            # exactement ? », « combien de temps ? ».
            words = normalized.split()
            if (
                len(words) <= 9
                and (
                    clean.rstrip().endswith("?")
                    or normalized.startswith((
                        "et ", "mais ", "donc ", "alors ", "où ", "ou ",
                        "quand ", "qui ", "quel ", "quelle ", "combien ",
                    ))
                )
            ):
                return True

        return False

    def expanded_query(self, message: str) -> str:
        clean = self._clean(message)
        current = self.current()

        normalized = self._normalize(clean)
        short_followup = len(normalized.split()) <= 10
        verification = any(
            self._normalize(marker) in normalized for marker in self.VERIFICATION_FOLLOWUPS
        )

        if not short_followup and not verification:
            return clean

        previous_query = self._clean(
            current.get("query", "")
            if isinstance(current, dict)
            else ""
        )
        if previous_query:
            return f"{previous_query} — {clean}"

        anchor = self._conversation_anchor()
        if anchor:
            return f"{anchor} — {clean}"

        return clean

    def _permission_allowed(self) -> bool:
        try:
            decision = self.permissions.check("web_search")
            value = getattr(getattr(decision, "decision", None), "value", None)
            return value == "allowed"
        except Exception:
            return False

    def _search(
        self,
        query: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []

        if self.search_provider is not None:
            try:
                raw = self.search_provider(query, self.MAX_SOURCES)
                attempts.append(
                    {
                        "query": query,
                        "backend": "custom_provider",
                        "region": "custom",
                        "ok": True,
                        "results": len(raw or []),
                        "error": "",
                    }
                )
            except Exception as exc:
                attempts.append(
                    {
                        "query": query,
                        "backend": "custom_provider",
                        "region": "custom",
                        "ok": False,
                        "results": 0,
                        "error": str(exc)[:240],
                    }
                )
                raw = []
        else:
            raw, attempts = self.searcher.search(
                query,
                max_results=self.MAX_SOURCES,
            )

        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for item in raw or []:
            if not isinstance(item, dict):
                continue
            url = self._clean(item.get("href") or item.get("url"))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                domain = urlparse(url).netloc.lower()
            except Exception:
                domain = ""
            sources.append(
                {
                    "id": f"S{len(sources) + 1}",
                    "title": self._clean(item.get("title")),
                    "url": url,
                    "body": self._clean(item.get("body") or item.get("snippet")),
                    "domain": domain,
                }
            )
            if len(sources) >= self.MAX_SOURCES:
                break

        return sources, attempts

    @staticmethod
    def _source_context(sources: list[dict[str, Any]]) -> str:
        blocks = []
        for source in sources:
            blocks.append(
                f"[{source['id']}] {source.get('title', '')}\n"
                f"{source.get('body', '')}\n"
                f"{source.get('url', '')}"
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _valid_citation_ids(sources: list[dict[str, Any]]) -> set[str]:
        return {str(source.get("id", "")) for source in sources}

    @classmethod
    def sanitize_citations(
        cls,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> str:
        valid = cls._valid_citation_ids(sources)

        def repl(match: re.Match[str]) -> str:
            source_id = match.group(1)
            return f"[{source_id}]" if source_id in valid else ""

        clean = re.sub(r"\[(S\d+)\]", repl, str(answer or ""))
        clean = re.sub(r"\s+([,.;:!?])", r"\1", clean)
        return " ".join(clean.split()).strip()

    @staticmethod
    def _source_footer(sources: list[dict[str, Any]], limit: int = 4) -> str:
        if not sources:
            return ""
        lines = ["Sources :"]
        for source in sources[:limit]:
            title = source.get("title") or source.get("domain") or source["id"]
            lines.append(
                f"[{source['id']}] {title} — {source.get('url', '')}"
            )
        return "\n".join(lines)

    def _synthesize(
        self,
        *,
        message: str,
        query: str,
        sources: list[dict[str, Any]],
    ) -> str:
        context = self._source_context(sources)
        system = """
Tu es le Researcher factuel d'Agent-OS.
Tu dois répondre UNIQUEMENT à partir des résultats Web fournis.

RÈGLES STRICTES
- N'invente aucun fait, lieu, date, personne, relation causale ou proximité.
- Chaque affirmation factuelle importante doit être appuyée par [S1], [S2], etc.
- N'utilise jamais un identifiant de source absent des résultats fournis.
- Si les sources ne permettent pas d'établir un point, dis clairement que tu
  ne peux pas le confirmer.
- Si les sources se contredisent, signale la contradiction.
- Si l'utilisateur remet en cause une affirmation précédente, vérifie-la et
  corrige-la explicitement si elle est fausse.
- Ne transforme jamais deux lieux distincts en lieux « proches » sans source.
- Réponds en français, directement, sans formule de bien-être ni relance
  générique.
"""
        prompt = f"""
QUESTION UTILISATEUR :
{message}

REQUÊTE DE RECHERCHE :
{query}

RÉSULTATS WEB :
{context}

Produis une réponse concise et factuelle avec citations [Sx].
"""
        answer = self.llm.chat(prompt, system=system)
        return self.sanitize_citations(answer, sources)

    def answer(self, message: str) -> str:
        if not self._permission_allowed():
            return (
                "Je ne peux pas vérifier cette information : la recherche Web "
                "n'est pas autorisée dans Agent-OS."
            )

        query = self.expanded_query(message)

        try:
            sources, attempts = self._search(query)
        except Exception as exc:
            attempts = []
            sources = []
            search_error = str(exc)
        else:
            search_error = ""

        if not sources:
            errors = [
                str(item.get("error", ""))
                for item in attempts
                if not item.get("ok") and item.get("error")
            ]
            detail = search_error or (errors[-1] if errors else "Aucun résultat exploitable.")
            failed_item = {
                "at": self._now_iso(),
                "query": self._clean(message),
                "expanded_query": query,
                "answer": "",
                "sources": [],
                "success": False,
                "error": detail,
                "search_attempts": attempts,
            }
            with self.lock:
                self.data["last_attempt"] = failed_item
                self.data.setdefault("history", []).append(failed_item)
                self._save()
            return (
                "Je n'ai trouvé aucune source exploitable après plusieurs "
                "moteurs de recherche, donc je préfère ne pas inventer de réponse."
            )

        try:
            answer = self._synthesize(
                message=message,
                query=query,
                sources=sources,
            )
        except Exception as exc:
            return f"J'ai trouvé des sources, mais leur synthèse a échoué : {exc}"

        if not answer:
            answer = (
                "Les sources ont été trouvées, mais je n'ai pas obtenu de "
                "synthèse fiable."
            )

        footer = self._source_footer(sources)
        final = answer + ("\n\n" + footer if footer else "")

        item = {
            "at": self._now_iso(),
            "query": self._clean(message),
            "expanded_query": query,
            "answer": answer,
            "sources": sources,
            "success": True,
            "error": "",
            "search_attempts": attempts,
        }

        with self.lock:
            self.data["current"] = item
            self.data["last_attempt"] = item
            self.data.setdefault("history", []).append(item)
            self._save()

        return final

    def status_summary(self) -> str:
        current = self.current()
        last = self.data.get("last_attempt")
        if not isinstance(last, dict):
            last = None

        lines = [
            "RECHERCHE FACTUELLE",
            f"Mode automatique : {'actif' if self.enabled() else 'désactivé'}",
        ]

        if last:
            success = bool(last.get("success"))
            lines.append(
                "Dernier essai : "
                + str(last.get("query", ""))
                + (" — OK" if success else " — ÉCHEC")
            )
            attempts = [
                item
                for item in (last.get("search_attempts", []) or [])
                if isinstance(item, dict)
            ]
            if attempts:
                ok_backends = [
                    str(item.get("backend"))
                    for item in attempts
                    if item.get("ok") and int(item.get("results", 0) or 0) > 0
                ]
                lines.append(f"Backends essayés : {len(attempts)}")
                if ok_backends:
                    lines.append(
                        "Backends avec résultats : "
                        + ", ".join(dict.fromkeys(ok_backends))
                    )
            if not success and last.get("error"):
                lines.append("Dernière erreur : " + str(last.get("error")))

        if current:
            lines.append(f"Dernière recherche réussie : {current.get('query', '')}")
            lines.append(
                f"Sources : {len(current.get('sources', []) or [])}"
            )
        elif not last:
            lines.append("Aucune recherche enregistrée.")

        return "\n".join(lines)

    def history_summary(self, limit: int = 8) -> str:
        items = [
            item for item in self.data.get("history", []) if isinstance(item, dict)
        ][-max(1, int(limit)):]
        if not items:
            return "Aucune recherche factuelle enregistrée."
        lines = ["RECHERCHES RÉCENTES"]
        for item in reversed(items):
            success = bool(item.get("success", bool(item.get("sources"))))
            state = "OK" if success else "ÉCHEC"
            lines.append(
                f"- {item.get('query', '')} — {state} "
                f"({len(item.get('sources', []) or [])} source(s))"
            )
        return "\n".join(lines)

    def command_response(self, message: str) -> str | None:
        normalized = self._normalize(message)
        if normalized in {self._normalize(x) for x in self.STATUS_COMMANDS}:
            return self.status_summary()
        if normalized in {self._normalize(x) for x in self.HISTORY_COMMANDS}:
            return self.history_summary()
        if normalized in {self._normalize(x) for x in self.ENABLE_COMMANDS}:
            self.set_enabled(True)
            return "Recherche factuelle automatique activée."
        if normalized in {self._normalize(x) for x in self.DISABLE_COMMANDS}:
            self.set_enabled(False)
            return "Recherche factuelle automatique désactivée."
        return None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "enabled": self.enabled(),
                "current": dict(self.data.get("current") or {}),
                "last_attempt": dict(self.data.get("last_attempt") or {}),
                "history_count": len(self.data.get("history", []) or []),
            }
