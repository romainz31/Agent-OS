from pathlib import Path
from datetime import datetime
import os
import shutil


def main():
    here = Path(__file__).resolve().parent
    root = next((p.resolve() for p in (Path.cwd(), here, here.parent, Path.cwd()/'Agent-OS-V6')
                 if (p/'agentos/autonomous_runtime.py').is_file()), None)
    if root is None:
        raise RuntimeError('Lance ce script depuis Agent-OS-V6, le dossier contenant api_server.py.')
    runtime = (root/'agentos/autonomous_runtime.py').read_text(encoding='utf-8')
    if '# V6-FILES 1.1 — native Mission Control integration' not in runtime:
        raise RuntimeError('Installe d’abord V6-Files 1.1 Mission Control. Aucun fichier modifié.')
    contents = {}
    for name in ('file_assistant.py', 'file_missions.py'):
        raw=(here/'payload'/name).read_bytes()
        compile(raw, name, 'exec')
        contents[root/'agentos'/name]=raw
    if all(p.is_file() and p.read_bytes()==raw for p,raw in contents.items()):
        print('V6-Files 1.2 déjà installé. Aucun changement.')
        return
    backup=root/'backups'/('V6-Files-1.2-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    old={}
    for p in contents:
        old[p]=p.read_bytes() if p.exists() else None
        if p.exists():
            shutil.copy2(p,backup/p.name)
    try:
        for p,raw in contents.items():
            tmp=p.with_suffix('.v6files-tmp')
            tmp.write_bytes(raw)
            os.replace(tmp,p)
    except Exception:
        for p,raw in old.items():
            if raw is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(raw)
        raise
    finally:
        for p in contents:
            p.with_suffix('.v6files-tmp').unlink(missing_ok=True)
    print('V6-Files 1.2 installé : choix Renommer / Écraser dans la même mission.')
    print('Sauvegarde du code remplacé :',backup)
    print('Redémarre python api_server.py. Pour M-005 déjà échouée : retry M-005.')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('Installation interrompue :',exc)
        raise SystemExit(1)
