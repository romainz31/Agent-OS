from pathlib import Path
from datetime import datetime
import shutil
import os

MARKER = '        # V6-FILES 1.1 — native Mission Control integration\n'
HOOK = MARKER + '        from agentos.file_missions import install_file_missions\n        install_file_missions(self)\n\n'


def main():
    here = Path(__file__).resolve().parent
    root = next((p.resolve() for p in (Path.cwd(), here, here.parent, Path.cwd()/'Agent-OS-V6')
                 if (p/'agentos/autonomous_runtime.py').is_file()), None)
    if root is None:
        raise RuntimeError('Lance ce script depuis Agent-OS-V6, le dossier contenant api_server.py.')
    target = root/'agentos/autonomous_runtime.py'
    original = target.read_text(encoding='utf-8')
    if '# V6-FILES 1.0 — approved document operations' not in original:
        raise RuntimeError('Installe d’abord V6-Files 1.0. Aucun fichier modifié.')
    if MARKER in original:
        print('V6-Files 1.1 déjà installé. Aucun changement.')
        return
    anchor = '        self.recovery = super()._recover_active_work()\n'
    if original.count(anchor) != 1:
        raise RuntimeError('Runtime différent : point d’intégration introuvable. Aucun fichier modifié.')
    contents = {
        root/'agentos/file_assistant.py': (here/'payload/file_assistant.py').read_text(encoding='utf-8'),
        root/'agentos/file_missions.py': (here/'payload/file_missions.py').read_text(encoding='utf-8'),
        target: original.replace(anchor, HOOK + anchor, 1),
    }
    for path, text in contents.items():
        compile(text, str(path), 'exec')
    backup = root/'backups'/('V6-Files-1.1-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    old = {}
    for path in contents:
        old[path] = path.read_bytes() if path.exists() else None
        if path.exists():
            dest=backup/path.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path,dest)
    try:
        for path,text in contents.items():
            tmp=path.with_suffix('.v6files-tmp')
            tmp.write_text(text,encoding='utf-8')
            os.replace(tmp,path)
    except Exception:
        for path,raw in old.items():
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(raw)
        raise
    finally:
        for path in contents:
            path.with_suffix('.v6files-tmp').unlink(missing_ok=True)
    print('V6-Files 1.1 installé : missions M-xxx et Mission Control.')
    print('Mémoire personnelle conservée. Sauvegarde du code :',backup)
    print('Redémarre : python api_server.py')
    print('Les anciens travaux F-... sont importés en missions au démarrage, sans être réexécutés.')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('Installation interrompue :',exc)
        raise SystemExit(1)
