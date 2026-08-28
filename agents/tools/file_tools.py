import subprocess


def write_file(file_path, content):

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

    return f"Fichier créé : {file_path}"


def read_file(file_path):

    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def run_python(file_path):

    result = subprocess.run(
        ["python", file_path],
        capture_output=True,
        text=True,
        encoding="utf-8"
    )

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