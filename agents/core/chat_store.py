import json
import os
import uuid
from datetime import datetime


# ============================================================
# STOCKAGE DES CONVERSATIONS
# ============================================================

CHAT_DIR = "data/chats"


# ============================================================
# OUTILS INTERNES
# ============================================================

def _ensure_chat_dir():

    os.makedirs(
        CHAT_DIR,
        exist_ok=True
    )


def _chat_file(chat_id):

    return os.path.join(
        CHAT_DIR,
        f"{chat_id}.json"
    )


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

        return None


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
# CRÉER UN CHAT
# ============================================================

def create_chat(
    agents,
    title=None,
    shared=None
):

    _ensure_chat_dir()


    chat_id = uuid.uuid4().hex


    if not agents:

        agents = []


    # --------------------------------------------------------
    # Si plusieurs agents participent au chat,
    # la mémoire partagée est activée automatiquement.
    # --------------------------------------------------------

    if shared is None:

        shared = len(agents) > 1


    if title is None:

        if agents:

            agent_names = [
                agent.capitalize()
                for agent in agents
            ]

            title = " + ".join(
                agent_names
            )

        else:

            title = "Nouveau chat"


    now = datetime.now().isoformat(
        timespec="seconds"
    )


    chat = {

        "id": chat_id,

        "title": title,

        "agents": agents,

        "shared": shared,

        "created_at": now,

        "updated_at": now,

        "messages": []

    }


    _save_json(
        _chat_file(chat_id),
        chat
    )


    return chat


# ============================================================
# CHARGER UN CHAT
# ============================================================

def load_chat(chat_id):

    chat = _load_json(
        _chat_file(chat_id)
    )


    if not isinstance(
        chat,
        dict
    ):

        return None


    return chat


# ============================================================
# SAUVEGARDER UN CHAT
# ============================================================

def save_chat(chat):

    chat["updated_at"] = (
        datetime.now().isoformat(
            timespec="seconds"
        )
    )


    _save_json(
        _chat_file(chat["id"]),
        chat
    )


    return chat


# ============================================================
# LISTER LES CHATS
# ============================================================

def list_chats():

    _ensure_chat_dir()


    chats = []


    for filename in os.listdir(CHAT_DIR):

        if not filename.endswith(".json"):

            continue


        path = os.path.join(
            CHAT_DIR,
            filename
        )


        chat = _load_json(path)


        if not isinstance(
            chat,
            dict
        ):

            continue


        chats.append(chat)


    chats.sort(
        key=lambda chat: chat.get(
            "updated_at",
            ""
        ),
        reverse=True
    )


    return chats


# ============================================================
# AJOUTER UN MESSAGE
# ============================================================

def add_message(
    chat_id,
    role,
    content,
    agent=None
):

    chat = load_chat(
        chat_id
    )


    if chat is None:

        return None


    message = {

        "role": role,

        "content": content,

        "timestamp": (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

    }


    if agent:

        message["agent"] = agent


    chat["messages"].append(
        message
    )


    # --------------------------------------------------------
    # Le titre du chat est automatiquement créé à partir
    # du premier message utilisateur.
    # --------------------------------------------------------

    if (
        role == "user"
        and len(chat["messages"]) == 1
    ):

        clean_title = content.strip()


        if len(clean_title) > 40:

            clean_title = (
                clean_title[:40]
                + "..."
            )


        if clean_title:

            chat["title"] = clean_title


    save_chat(chat)


    return chat


# ============================================================
# SUPPRIMER UN CHAT
# ============================================================

def delete_chat(chat_id):

    path = _chat_file(
        chat_id
    )


    if not os.path.exists(path):

        return False


    os.remove(path)


    return True