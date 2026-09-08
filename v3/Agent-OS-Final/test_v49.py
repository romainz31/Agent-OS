from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from agentos.research import ResearchGateway, ResilientWebSearch


class FakeLLM:
    def __init__(self) -> None:
        self.calls = []

    def chat(self, prompt: str, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return (
            "L'accident de Diana s'est produit dans le tunnel du pont de "
            "l'Alma à Paris le 31 août 1997 [S1] [S2]. "
            "Buckingham Palace est à Londres [S3]."
        )


class FakePermissions:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def check(self, name: str):
        assert name == "web_search"
        return SimpleNamespace(
            decision=SimpleNamespace(
                value="allowed" if self.allowed else "denied"
            )
        )


class FakeTracker:
    def __init__(self) -> None:
        self.topic = "l'accident de Lady Di"
        self.summary = "On vérifie le lieu exact de l'accident de Lady Di."

    def snapshot(self):
        return {
            "topic": self.topic,
            "summary": self.summary,
        }


def fake_search(query: str, max_results: int):
    return [
        {
            "title": "Princess Diana dies in Paris crash",
            "href": "https://www.bbc.example/diana-paris",
            "body": "Diana was fatally injured in a car crash in the Pont de l'Alma tunnel in Paris on 31 August 1997.",
        },
        {
            "title": "Diana, Princess of Wales",
            "href": "https://www.britannica.example/diana",
            "body": "She died after a car crash in a tunnel beneath the Pont de l'Alma in Paris.",
        },
        {
            "title": "Buckingham Palace",
            "href": "https://www.royal.example/buckingham",
            "body": "Buckingham Palace is the London residence of the sovereign.",
        },
    ][:max_results]


passed = 0


def check(condition: bool, label: str) -> None:
    global passed
    if not condition:
        raise AssertionError(label)
    passed += 1
    print(f"[OK] {label}")


def main() -> None:
    print("=" * 68)
    print("TEST AGENT-OS V4.9 — RECHERCHE FACTUELLE SOURCÉE")
    print("=" * 68)

    with tempfile.TemporaryDirectory() as temp:
        store = Path(temp) / "research.json"
        llm = FakeLLM()
        tracker = FakeTracker()
        gateway = ResearchGateway(
            llm=llm,
            permissions=FakePermissions(True),
            conversation_tracker=tracker,
            store_path=store,
            search_provider=fake_search,
        )

        check(
            gateway.should_research("Où s'est déroulé l'accident de Lady Di ?"),
            "Question historique factuelle => recherche",
        )
        check(
            gateway.should_research("Quand a eu lieu l'accident de Lady Di ?"),
            "Question de date => recherche",
        )
        check(
            gateway.should_research("Quel est le président actuel de la France ?"),
            "Question factuelle actuelle => recherche",
        )
        check(
            gateway.should_research("Vérifie sur internet où a eu lieu l'accident."),
            "Vérification Web explicite => recherche directe",
        )
        check(
            gateway.should_research("Vérifie si l'accident de Lady Di a eu lieu à Paris"),
            "Vérification factuelle sans fichier => Researcher",
        )
        check(
            not gateway.should_research("Vérifie workspace/test.py"),
            "Vérification de fichier => Tester",
        )
        check(
            not gateway.should_research("Recherche des informations sur Zigbee2MQTT"),
            "Recherche explicite longue reste une mission Researcher",
        )
        check(
            not gateway.should_research("Crée workspace/test.py qui affiche OK"),
            "Création de fichier reste une mission Developer",
        )
        check(
            not gateway.should_research("Comment s'appelle ma copine ?"),
            "Question personnelle reste dans la mémoire personnelle",
        )
        check(
            not gateway.should_research("Que sais-tu sur mes habitudes ?"),
            "Question mémoire par catégorie non routée vers le Web",
        )
        check(
            not gateway.should_research("manager status"),
            "Commande Manager non routée vers le Web",
        )
        check(
            not gateway.should_research("Tu en penses quoi ?"),
            "Question d'opinion reste conversationnelle",
        )

        check(
            gateway.should_research("Y'a pas une erreur là ?"),
            "Contestations factuelles utilisent le sujet du fil",
        )
        expanded = gateway.expanded_query("Y'a pas une erreur là ?")
        check(
            "Lady Di" in expanded,
            "Question ambiguë enrichie avec le contexte conversationnel",
        )

        answer = gateway.answer("Où s'est déroulé l'accident de Lady Di ?")
        check(
            "pont de l'Alma" in answer and "Paris" in answer,
            "Réponse Researcher retournée",
        )
        check(
            "[S1]" in answer and "Sources :" in answer,
            "Réponse accompagnée de citations et URLs",
        )
        check(
            "bbc.example" in answer and "britannica.example" in answer,
            "Sources visibles dans la réponse",
        )
        check(
            len(llm.calls) == 1,
            "Une synthèse LLM seulement après collecte des sources",
        )
        system = llm.calls[0][1] or ""
        check(
            "N'invente aucun fait" in system,
            "Prompt Researcher interdit explicitement l'invention",
        )
        check(
            "deux lieux distincts" in system,
            "Prompt protège le cas de fausse proximité géographique",
        )

        current = gateway.current() or {}
        check(
            current.get("query") == "Où s'est déroulé l'accident de Lady Di ?",
            "Dernière recherche persistée",
        )
        check(
            len(current.get("sources", [])) == 3,
            "Sources structurées persistées",
        )

        check(
            gateway.should_research("Et Buckingham Palace ?"),
            "Question courte de suivi réutilise le contexte de recherche",
        )
        followup = gateway.expanded_query("Et Buckingham Palace ?")
        check(
            "Lady Di" in followup
            and "Buckingham Palace" in followup,
            "Suivi court enrichi avec la recherche précédente",
        )

        sanitized = gateway.sanitize_citations(
            "Paris [S1], Londres [S9].",
            current.get("sources", []),
        )
        check(
            "[S1]" in sanitized and "[S9]" not in sanitized,
            "Citation inexistante supprimée",
        )

        gateway2 = ResearchGateway(
            llm=FakeLLM(),
            permissions=FakePermissions(True),
            conversation_tracker=tracker,
            store_path=store,
            search_provider=fake_search,
        )
        check(
            (gateway2.current() or {}).get("query")
            == "Où s'est déroulé l'accident de Lady Di ?",
            "Contexte de recherche survit au redémarrage",
        )
        check(
            "Où s'est déroulé" in gateway2.history_summary(),
            "Historique des recherches lisible",
        )

        gateway2.set_enabled(False)
        check(
            not gateway2.should_research("Où a eu lieu l'accident ?"),
            "Recherche automatique désactivable",
        )
        gateway2.set_enabled(True)
        check(
            gateway2.should_research("Où a eu lieu l'accident ?"),
            "Recherche automatique réactivable",
        )

        denied = ResearchGateway(
            llm=FakeLLM(),
            permissions=FakePermissions(False),
            conversation_tracker=tracker,
            store_path=Path(temp) / "denied.json",
            search_provider=fake_search,
        )
        denied_answer = denied.answer("Où est Paris ?")
        check(
            "n'est pas autorisée" in denied_answer,
            "Aucune recherche contournant les permissions",
        )

        empty = ResearchGateway(
            llm=FakeLLM(),
            permissions=FakePermissions(True),
            conversation_tracker=tracker,
            store_path=Path(temp) / "empty.json",
            search_provider=lambda q, n: [],
        )
        empty_answer = empty.answer("Où est ce lieu ?")
        check(
            "préfère ne pas inventer" in empty_answer,
            "Absence de source => pas d'hallucination de secours",
        )
        empty_status = empty.status_summary()
        check(
            "Dernier essai" in empty_status and "ÉCHEC" in empty_status,
            "Une recherche échouée reste visible dans research status",
        )

        backend_calls = []

        def flaky_backend(query, backend, region, max_results):
            backend_calls.append((query, backend, region))
            if backend == "wikipedia":
                raise RuntimeError("No results found.")
            if backend == "brave":
                return [
                    {
                        "title": "Diana crash",
                        "href": "https://example.org/diana",
                        "body": "Pont de l'Alma tunnel, Paris",
                    }
                ]
            return []

        resilient = ResilientWebSearch(backend_provider=flaky_backend)
        raw, attempts = resilient.search(
            "Où s'est déroulé l'accident de Lady Di ?",
            max_results=5,
        )
        check(
            len(raw) == 1,
            "Un backend en échec n'annule plus les résultats d'un autre backend",
        )
        check(
            any(not item.get("ok") for item in attempts)
            and any(item.get("ok") and item.get("results") for item in attempts),
            "Diagnostics conservent les backends en échec et en succès",
        )
        check(
            backend_calls[0][1] == "wikipedia"
            and any(call[1] == "brave" for call in backend_calls),
            "Les backends sont essayés séparément et séquentiellement",
        )
        check(
            "Lady" in resilient.simplified_query(
                "Où s'est déroulé l'accident de Lady Di ?"
            ),
            "Fallback de requête simplifiée conserve les entités utiles",
        )

        command = gateway2.command_response("research status") or ""
        check(
            "RECHERCHE FACTUELLE" in command,
            "Commande research status opérationnelle",
        )
        check(
            gateway2.command_response("research off")
            == "Recherche factuelle automatique désactivée.",
            "Commande research off opérationnelle",
        )
        check(
            gateway2.command_response("research on")
            == "Recherche factuelle automatique activée.",
            "Commande research on opérationnelle",
        )

    print()
    print(f"TOUS LES TESTS V4.9 SONT PASSÉS — {passed} contrôles.")
    print("Tu peux ensuite lancer api_server.py et tester Paul/Telegram.")


if __name__ == "__main__":
    main()
