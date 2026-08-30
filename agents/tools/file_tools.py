import os
import subprocess


# ============================================================
# SÉCURITÉ : SANDBOX DE FICHIERS
# ============================================================

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

ALLOWED_DIRS = [
    "applications",
    "data"
]

RUN_TIMEOUT_SECONDS = 15


def _resolve_safe_path(file_path):
    """
    Vérifie que file_path pointe bien vers un fichier situé dans
    l'un des dossiers autorisés du projet.
    """

    if not isinstance(file_path, str):
        raise TypeError(
            "file_path doit être une chaîne de caractères."
        )

    if os.path.isabs(file_path):
        raise PermissionError(
            f"Chemin absolu interdit : {file_path}"
        )

    candidate = os.path.abspath(
        os.path.join(PROJECT_ROOT, file_path)
    )

    for allowed_dir in ALLOWED_DIRS:

        allowed_root = os.path.abspath(
            os.path.join(
                PROJECT_ROOT,
                allowed_dir
            )
        )

        if (
            candidate == allowed_root
            or candidate.startswith(
                allowed_root + os.sep
            )
        ):
            return candidate

    raise PermissionError(
        f"Chemin non autorisé : {file_path}. "
        f"Autorisé uniquement dans : {ALLOWED_DIRS}"
    )


# ============================================================
# WRITE FILE
# ============================================================

def write_file(file_path, content):

    safe_path = _resolve_safe_path(
        file_path
    )

    os.makedirs(
        os.path.dirname(safe_path),
        exist_ok=True
    )

    with open(
        safe_path,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(content)

    return (
        f"Fichier créé : {file_path}"
    )


# ============================================================
# READ FILE
# ============================================================

def read_file(file_path):

    safe_path = _resolve_safe_path(
        file_path
    )

    with open(
        safe_path,
        "r",
        encoding="utf-8"
    ) as file:

        return file.read()


# ============================================================
# RUN PYTHON
# ============================================================

def run_python(
    file_path,
    input_data=None
):
    """
    Exécute un programme Python.

    input_data permet de fournir automatiquement des entrées
    à un programme utilisant input().

    Exemple :

        run_python(
            "applications/calcul.py",
            "10\n20\n"
        )

    équivaut à lancer le programme et saisir :

        10
        20
    """

    safe_path = _resolve_safe_path(
        file_path
    )

    # --------------------------------------------------------
    # ENVIRONNEMENT
    # --------------------------------------------------------

    env = os.environ.copy()

    # Force UTF-8 pour les entrées/sorties Python.
    env["PYTHONIOENCODING"] = "utf-8"

    # --------------------------------------------------------
    # NORMALISATION DE L'ENTRÉE
    # --------------------------------------------------------

    if input_data is not None:

        if not isinstance(
            input_data,
            str
        ):
            raise TypeError(
                "input_data doit être une chaîne de caractères."
            )

    # --------------------------------------------------------
    # EXÉCUTION
    # --------------------------------------------------------

    try:

        result = subprocess.run(

            [
                "python",
                safe_path
            ],

            input=input_data,

            capture_output=True,

            text=True,

            encoding="utf-8",

            timeout=RUN_TIMEOUT_SECONDS,

            env=env

        )

    except subprocess.TimeoutExpired:

        return {

            "success": False,

            "output": "",

            "error": (
                f"Le programme a dépassé le délai maximum "
                f"de {RUN_TIMEOUT_SECONDS} secondes et a été "
                f"arrêté."
            )

        }

    except Exception as e:

        return {

            "success": False,

            "output": "",

            "error": (
                f"Erreur lors de l'exécution : {e}"
            )

        }

    # --------------------------------------------------------
    # SUCCÈS
    # --------------------------------------------------------

    if result.returncode == 0:

        return {

            "success": True,

            "output": result.stdout,

            "error": ""

        }

    # --------------------------------------------------------
    # ERREUR PROGRAMME
    # --------------------------------------------------------

    return {

        "success": False,

        "output": result.stdout,

        "error": result.stderr

    }