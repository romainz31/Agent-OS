import json
import os
import re
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

MEMORY_DIR = "data/memory"

KNOWLEDGE_FILE = os.path.join(
    MEMORY_DIR,
    "knowledge.json"
)


# ============================================================
# OUTILS INTERNES
# ============================================================

def _load_json(path):

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except (
        FileNotFoundError,
        json.JSONDecodeError
    ):

        return []


def _save_json(path, data):

    os.makedirs(
        os.path.dirname(path),
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False
        )


# ============================================================
# CHARGEMENT
# ============================================================

def load_knowledge():

    return _load_json(
        KNOWLEDGE_FILE
    )


# ============================================================
# SAUVEGARDE
# ============================================================

def save_knowledge(knowledge):

    _save_json(
        KNOWLEDGE_FILE,
        knowledge
    )


# ============================================================
# AJOUT D'UNE CONNAISSANCE
# ============================================================

def add_knowledge(
    title,
    source,
    summary,
    facts=None,
    topics=None
):

    knowledge = load_knowledge()

    facts = facts or []

    topics = topics or []


    entry = {

        "id":
            datetime.now().strftime(
                "%Y%m%d%H%M%S%f"
            ),

        "title":
            title,

        "source":
            source,

        "summary":
            summary,

        "facts":
            facts,

        "topics":
            topics,

        "created_at":
            datetime.now().isoformat(
                timespec="seconds"
            )

    }


    knowledge.append(
        entry
    )

    save_knowledge(
        knowledge
    )

    return entry


# ============================================================
# RECHERCHE DE CONNAISSANCES
# ============================================================

def search_knowledge(
    query,
    max_results=5
):

    knowledge = load_knowledge()

    if not knowledge:

        return []


    query_words = set(
        re.findall(
            r"\w+",
            query.lower()
        )
    )


    scored = []


    for entry in knowledge:

        searchable = " ".join([

            str(
                entry.get(
                    "title",
                    ""
                )
            ),

            str(
                entry.get(
                    "summary",
                    ""
                )
            ),

            " ".join(
                entry.get(
                    "facts",
                    []
                )
            ),

            " ".join(
                entry.get(
                    "topics",
                    []
                )
            ),

            str(
                entry.get(
                    "source",
                    ""
                )
            )

        ]).lower()


        score = sum(

            1

            for word in query_words

            if word in searchable

        )


        if score > 0:

            scored.append(
                (
                    score,
                    entry
                )
            )


    scored.sort(
        key=lambda item: item[0],
        reverse=True
    )


    return [

        entry

        for score, entry

        in scored[:max_results]

    ]


# ============================================================
# FORMATAGE POUR LE LLM
# ============================================================

def format_knowledge(
    knowledge
):

    if not knowledge:

        return "(aucune connaissance pertinente)"


    sections = []


    for entry in knowledge:

        facts = "\n".join(

            f"- {fact}"

            for fact in entry.get(
                "facts",
                []
            )

        )


        sections.append(

            f"""
SOURCE :
{entry.get("title", "")}

URL :
{entry.get("source", "")}

RÉSUMÉ :
{entry.get("summary", "")}

FAITS IMPORTANTS :
{facts}
"""

        )


    return "\n".join(
        sections
    )


# ============================================================
# RESET
# ============================================================

def reset_knowledge():

    save_knowledge([])