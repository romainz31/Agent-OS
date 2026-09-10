# Agent-OS V10.2.1

Patch correctif pour V10.2.0.

## Installation

Arrêter Agent-OS puis extraire le contenu du ZIP dans `Agent-OS-V10` en acceptant le remplacement.
Aucun dossier `data/` ou `workspace/` n'est inclus.

Installer les dépendances documentaires une fois :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-documents.txt
```

## Lancement le plus simple

```powershell
.\start_v10.cmd
```

Le fichier utilise directement `.venv\Scripts\python.exe`; aucune activation PowerShell n'est nécessaire.

Pour retrouver l'usage `python xxx.py`, lancer :

```powershell
.\.venv\Scripts\Activate.ps1
python start_v10.py
```

Ou double-cliquer `venv.cmd`, puis taper les commandes `python ...` dans la fenêtre ouverte.

## Boutons Windows inclus

- `INSTALLER_V10.cmd` : crée/répare `.venv` et installe toutes les dépendances.
- `TESTER_V10.cmd` : lance les tests V10 puis le test API.
- `LANCER_AGENT_OS.cmd` : lance Agent-OS avec `.venv\Scripts\python.exe`.
- `OUVRIR_VENV.cmd` : ouvre un terminal où `python` désigne le Python du venv.

Le lanceur historique `start_v10.cmd` est également fourni.
