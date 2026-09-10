"""Install additive file support without replacing the user's memory code."""
from pathlib import Path
import os
import shutil
from datetime import datetime

MARKER = '        # V6-FILES 1.0 — approved document operations\n'
HOOK = '''        # V6-FILES 1.0 — approved document operations
        from agentos.file_assistant import dispatch_file_message
        file_response = dispatch_file_message(self, message)
        if file_response is not None:
            return file_response

'''


def main():
    here = Path(__file__).resolve().parent
    candidates = [Path.cwd(), here, here.parent, Path.cwd() / 'Agent-OS-V6', here / 'Agent-OS-V6']
    root = next((p.resolve() for p in candidates if (p / 'agentos/autonomous_runtime.py').is_file()), None)
    if root is None:
        raise RuntimeError('Lance ce script depuis le dossier Agent-OS-V6 (celui contenant api_server.py).')
    target = root / 'agentos/autonomous_runtime.py'
    original = target.read_text(encoding='utf-8')
    marker = '    def handle_message(\n        self,\n        message: str,\n    ) -> dict[str, Any]:\n'
    shutdown = '    def shutdown(self) -> None:\n'
    if MARKER in original:
        print('V6-Files 1.0 est déjà installé. Aucun changement.')
        return
    if original.count(marker) != 1 or original.count(shutdown) != 1:
        raise RuntimeError('Runtime différent de la V6 attendue : aucun fichier modifié. Fournis cette version pour adapter le module.')
    content = original.replace(marker, marker + HOOK, 1).replace(shutdown, shutdown +
        '        if hasattr(self, "file_assistant"):\n            self.file_assistant.close()\n', 1)
    payload = (here / 'payload/file_assistant.py').read_text(encoding='utf-8')
    compile(content, str(target), 'exec')
    compile(payload, 'file_assistant.py', 'exec')
    dependency = (here / 'requirements-documents.txt').read_text(encoding='utf-8')
    outputs = {root / 'agentos/file_assistant.py': payload,
               root / 'requirements-documents.txt': dependency, target: content}
    backup = root / 'backups' / ('V6-Files-1.0-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    old = {}
    for path in outputs:
        old[path] = path.read_bytes() if path.exists() else None
        if path.exists():
            destination = backup / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    try:
        for path, value in outputs.items():
            temp = path.with_suffix(path.suffix + '.v6files-tmp')
            temp.write_text(value, encoding='utf-8')
            os.replace(temp, path)
    except Exception:
        for path, value in old.items():
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(value)
        raise
    finally:
        for path in outputs:
            path.with_suffix(path.suffix + '.v6files-tmp').unlink(missing_ok=True)
    print('V6-Files 1.0 installé. Mémoire personnelle inchangée.')
    print('Sauvegarde des fichiers remplacés :', backup)
    print('Optionnel pour PDF / XLSX / création DOCX / validation YAML :')
    print('python -m pip install -r requirements-documents.txt')
    print('Relance python api_server.py, puis envoie : fichiers aide')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Installation interrompue :', exc)
        raise SystemExit(1)
