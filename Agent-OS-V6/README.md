# Agent-OS V6.0 — base consolidée

Cette V6 reprend le moteur du commit V5.5 `6b708db` et place l'application active à la racine. Telegram, Web et CLI utilisent le même serveur. Managers, mémoire relationnelle, missions persistantes, priorités, sous-missions, compétences, apprentissage et collaboration sont conservés.

## Installation Windows / PowerShell

Extraire `Agent-OS-V6.zip` dans un nouveau dossier permet de démarrer avec une mémoire vide sans toucher à la V5.5 locale. Ouvrir PowerShell dans le dossier extrait `Agent-OS-V6` :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python api_server.py
```

Ollama doit être lancé avec le modèle `qwen2.5:7b` disponible. L'interface Web est accessible à http://127.0.0.1:8765. Le serveur reste lié à l'interface locale.

Dans un autre terminal PowerShell, depuis le même dossier :

```powershell
.\.venv\Scripts\Activate.ps1
$env:TELEGRAM_BOT_TOKEN = "ton_token"
$env:TELEGRAM_ALLOWED_CHAT_ID = "ton_chat_id"
python telegram_client.py
```

Pour la CLI : `python run.py`. Un seul `api_server.py` doit fonctionner pour un même dossier de données.

## Données et mémoire

- `agentos/` : code du moteur ; `web/` : interface ; `tests/` : vérifications utiles.
- `data/` : mémoire personnelle, conversations, missions et compétences créées localement.
- `workspace/` : fichiers produits par les agents, créé localement à la demande.
- Aucun historique personnel, cache Python ou résultat d'essai n'est livré dans cette V6.
- La mémoire active de V5.5 n'était pas suivie dans GitHub : elle reste sur l'ancien PC/dossier. Aucun nettoyage automatique de cette mémoire n'est effectué.

Conseil : commencer V6 avec ses données vides, puis lui redonner uniquement les préférences utiles. Ne pas recopier tout `data/` si l'objectif est d'éviter la reprise d'anciennes missions. Les compétences et l'historique opérationnel font également partie des données, pas du code.

`AGENTOS_DATA_DIR` et `AGENTOS_WORKSPACE_DIR` permettent de choisir des répertoires distincts (chemins absolus recommandés). Par défaut ils sont placés à la racine du projet. `OLLAMA_HOST`, `OLLAMA_MODEL` et `AGENT_OS_MAX_WORKERS` restent disponibles. Aucun fichier `.env` n'est chargé automatiquement.

## Vérification

```powershell
python -m tests.run_all
```

Chaque suite tourne dans un processus séparé, avec des répertoires de données temporaires automatiquement supprimés. Les tests conservés sont des contrôles de non-régression ; les anciens fichiers produits par les essais ont été retirés. La construction réelle de `.exe` dans la suite V5.5 nécessite Windows et PyInstaller ; elle est ignorée ailleurs. Les tests ne valident pas une conversation réelle avec Ollama ou la connexion Telegram.

## Prochaines améliorations proposées

1. **V6.1 — cibles des missions** : résoudre et transmettre le fichier cible du Manager au Developer ; demander une précision avant de lancer une modification ambiguë. `explicit_path_missing` existe encore pour les demandes sans cible identifiable ; le supprimer aveuglément serait une régression.
2. **V6.2 — mémoire contrôlable** : consultation, correction et oubli ciblés depuis Telegram ; distinguer préférences durables, humeur passagère et traces des missions.
3. **V6.3 — exécution fiable** : vérifier reprise après interruption, annulation, notifications et absence de doublons ; renforcer la persistance si plusieurs processus doivent être supportés.
4. **V6.4 — suivi du travail** : présenter objectif, étape active, blocage, preuve de vérification et livrable pour chaque mission.

L'historique Git conserve les versions précédentes. Cette V6 consolide l'existant ; elle ne prétend pas résoudre les quatre chantiers ci-dessus.

## Validation de cette livraison

Les dix suites conservées passent sous Linux, et le chargement de l’API ainsi que la cohérence du numéro 6.0.0 sont vérifiés. Ollama et Telegram ne sont pas connectés dans cet environnement. Le build Windows reste à vérifier sous Windows. GitHub a refusé la création de l’arbre Git (403, intégration sans accès à cette opération) : cette archive n’a donc pas été publiée sur une branche distante.
