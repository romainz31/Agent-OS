from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from agentos.research import ResilientWebSearch


def main() -> None:
    print("=" * 68)
    print("TEST AGENT-OS V4.9 — RECHERCHE WEB RÉELLE")
    print("=" * 68)

    try:
        ddgs_version = version("ddgs")
    except PackageNotFoundError:
        print("[ERREUR] Le package ddgs n'est pas installé.")
        print("Commande : python -m pip install -U ddgs")
        raise SystemExit(2)

    print(f"ddgs installé : {ddgs_version}")
    print()

    searcher = ResilientWebSearch()
    query = "accident Lady Di Paris Pont de l'Alma"

    results, attempts = searcher.search(query, max_results=8)

    print("Backends essayés :")
    for item in attempts:
        state = "OK" if item.get("ok") else "ERREUR"
        count = int(item.get("results", 0) or 0)
        backend = item.get("backend", "?")
        region = item.get("region", "?")
        error = str(item.get("error", "") or "")
        suffix = f" — {error}" if error else ""
        print(f"- {backend:12s} | {region:5s} | {state:6s} | {count} résultat(s){suffix}")

    print()

    if not results:
        print("[ECHEC] Aucun backend n'a retourné de résultat exploitable.")
        print("Essaie ensuite : python -m pip install -U ddgs")
        print("Puis relance ce test.")
        raise SystemExit(1)

    print(f"[OK] {len(results)} résultat(s) Web récupéré(s).")
    print("Premiers résultats :")
    for item in results[:5]:
        title = str(item.get("title", "") or "").strip()
        url = str(item.get("href") or item.get("url") or "").strip()
        print(f"- {title}")
        print(f"  {url}")

    print()
    print("RECHERCHE WEB RÉELLE OPÉRATIONNELLE.")


if __name__ == "__main__":
    main()
