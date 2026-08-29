import os
import subprocess


# ============================================================
# SÉCURITÉ : SANDBOX DE FICHIERS
# ============================================================
#
# Les agents (Developer, Tester) sont pilotés par un LLM. Un LLM
# peut halluciner un chemin, ou une consigne malveillante pourrait
# tenter de lui faire écrire/lire/exécuter en dehors du projet.
#
# On restreint donc toute opération de fichier à un petit nombre
# de dossiers autorisés, situés à l'intérieur du projet.

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

ALLOWED_DIRS = ["applications", "data"]

RUN_TIMEOUT_SECONDS = 15


def _resolve_safe_path(file_path):
    """
    Vérifie que file_path pointe bien vers un fichier situé dans
    l'un des ALLOWED_DIRS, à l'intérieur de PROJECT_ROOT.

    Bloque notamment :
    - les chemins absolus (/etc/passwd, C:\\...)
    - les remontées de dossier (../../etc/passwd)
    - les chemins pointant vers un dossier non autorisé
    """

    if os.path.isabs(file_path):
        raise PermissionError(
            f"Chemin absolu interdit : {file_path}"
        )

    candidate = os.path.abspath(
        os.path.join(PROJECT_ROOT, file_path)
    )

    allowed = False

    for allowed_dir in ALLOWED_DIRS:
        allowed_root = os.path.abspath(
            os.path.join(PROJECT_ROOT, allowed_dir)
        )

        if candidate == allowed_root or candidate.startswith(
            allowed_root + os.sep
        ):
            allowed = True
            break

    if not allowed:
        raise PermissionError(
            f"Chemin non autorisé : {file_path}. "
            f"Autorisé uniquement dans : {ALLOWED_DIRS}"
        )

    return candidate


def write_file(file_path, content):

    safe_path = _resolve_safe_path(file_path)

    os.makedirs(os.path.dirname(safe_path), exist_ok=True)

    with open(safe_path, "w", encoding="utf-8") as file:
        file.write(content)

    return f"Fichier créé : {file_path}"


def read_file(file_path):

    safe_path = _resolve_safe_path(file_path)

    with open(safe_path, "r", encoding="utf-8") as file:
        return file.read()


def run_python(file_path):

    safe_path = _resolve_safe_path(file_path)

    # Sur Windows, la console utilise par défaut un encodage limité
    # (cp1252) qui ne sait pas afficher certains caractères non
    # occidentaux (chinois, emojis, etc.). Si le script généré par
    # le LLM contient de tels caractères, le sous-processus plante
    # avec une UnicodeEncodeError avant même que Python ne nous
    # renvoie la main. On force donc l'UTF-8 pour le sous-processus.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        result = subprocess.run(
            ["python", safe_path],
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
                f"Le programme a dépassé le délai maximum de "
                f"{RUN_TIMEOUT_SECONDS} secondes et a été arrêté."
            )
        }

    if result.returncode == 0:
        return {
            "success": True,
            "output": result.stdout,
            "error": ""
        }

    return {
        "success": False,
        "output": result.stdout,
        "error": result.stderr
    }