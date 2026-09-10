# Agent-OS V10.1.0 — Paul plus naturel et images en attente

Version complète à extraire dans votre dossier Agent-OS : le ZIP crée `agent-os-v10/`.
Mémoire vierge au premier lancement. Ne recopiez pas les dossiers data ou workspace
anciens. `start_v10.py` impose les dossiers propres à V10 même si des variables
AGENTOS_DATA_DIR ou AGENTOS_WORKSPACE_DIR d'une ancienne version sont encore actives.
Redémarrer conserve ensuite vos données : aucun effacement automatique.

## Installation dans le terminal VS Code / PowerShell

Ouvrir le dossier `agent-os-v10`, puis :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen2.5:7b
ollama pull qwen2.5vl:3b
.\.venv\Scripts\python.exe start_v10.py
```

Aucune activation PowerShell nécessaire. Les scripts INSTALLER.cmd et DEMARRER.cmd
permettent aussi l'installation et le démarrage par double clic.
Ollama doit tourner. Ouvrir http://127.0.0.1:8765. Garder le serveur en fonctionnement
pour les missions et rappels. V10 ne réveille pas un PC éteint et n'installe pas de
service Windows. Python 3.12 utilisé pour les tests de cette livraison ; exécution
Windows et modèles locaux à vérifier sur votre machine. Un seul serveur par dossier.

## Ce que contient cette version

- Paul et la mémoire relationnelle existante, Web, CLI et Telegram.
- Journal SQLite daté, sans purge automatique, indépendant du tampon conversationnel.
- Actions accomplies et ressentis explicites : recherche, liste, comptage par période.
- Agenda et priorités haute/normale/basse hérités ; les tâches restent dans UNE table.
- Report des tâches datées en attente vers aujourd'hui au démarrage et en fonctionnement.
  Date initiale et compteur conservés. Les tâches sans date restent dans le backlog.
  Les rendez-vous ne sont jamais déplacés par ce report.
- Programme quotidien après 8 h et rappel 30 minutes avant un rendez-vous horaire,
  fuseau Europe/Paris. Notifications via les canaux connectés, une fois par événement.
- Pièces jointes Web et Telegram ; lecture seulement après autorisation de la mission.
- PDF texte et PDF scannés/mixtes (pages sans texte rendues pour le modèle vision),
  images PNG/JPEG/WebP, DOCX, XLSX, texte/CSV/JSON/YAML.
- Analyse de dossiers explicitement autorisés, synthèse structurée et Excel,
  missions M-xxx, réouverture du classeur de sortie pour vérification.
- Bouton « Vie quotidienne » en bas à droite de l'interface, téléchargement des exports.

## Comportement plus naturel de Paul — V10.1

Les réponses du journal sont formulées comme une conversation et n'affichent plus
les identifiants techniques à chaque ajout. La donnée reste enregistrée de façon
structurée et exacte dans SQLite. Exemple :

```text
Toi : Journal : nettoyé le filtre ; arrosé les plantes ; fait les courses
Paul : C'est noté pour aujourd'hui : tu as nettoyé le filtre, tu as arrosé
les plantes et tu as fait les courses.
```

Le ton conversationnel ne change pas les faits mémorisés et Paul ne prétend pas
avoir des émotions ou une vie humaine. Une humeur reçoit un accueil bref et naturel,
sans question automatique imposée.

Quand une image ou un document est envoyé sans consigne, Paul le conserve dans
`workspace/inbox/` et demande ce que tu veux en faire. La réponse suivante du même
client Web ou Telegram est rattachée au fichier. Cet état survit à un redémarrage.
`annule`, `rien`, `laisse tomber` ou `oublie le fichier` abandonne la demande.

## Premier test, avec une mémoire vide

Envoyer à Paul :

```text
Je m'appelle Romain.
Journal : nettoyé le filtre de l'aquarium; arrosé les plantes; fait les courses
Journal aujourd'hui
Journal trois derniers mois : filtre
Combien de fois j'ai nettoyé le filtre sur les trois derniers mois ?
Humeur : fatigué mais content d'avoir avancé
À faire aujourd'hui : nettoyer le garage
Rendez-vous le 12/09/2026 à 14h : dentiste
Qu'ai-je prévu le 12/09/2026 ?
```

Pour une liste de plusieurs actions, `Journal : action; action; action` est la syntaxe
fiable : une entrée par point-virgule. Les déclarations simples « J'ai nettoyé… »,
« J'ai réparé… », etc. sont aussi capturées. Les formulations libres plus complexes
restent dépendantes de la compréhension de Paul. Il ne faut pas interpréter une
réponse conversationnelle comme une preuve d'enregistrement : vérifier le journal.

Le comptage porte sur les faits ENREGISTRÉS, pas sur une connaissance exhaustive de
votre vie. Le même libellé le même jour est dédoublonné. Pour deux occurrences réelles
le même jour, préciser « matin » et « soir ». Recherche par mots présents dans le
libellé ; les synonymes ne sont pas tous rapprochés. Aucun comptage approximatif par
LLM. Une tâche accomplie est lue directement depuis l'agenda, sans copie dans le journal.
Pour corriger : `journal supprimer 1`, puis ajouter la bonne entrée. Les IDs J-1 sont
affichés à l'enregistrement ; la suppression utilise le numéro sans le préfixe.
Les ressentis sont des déclarations, pas des diagnostics : Paul ne lit pas les pensées.

## Photos, factures et Excel

Dans le panneau V10, choisir un ou plusieurs fichiers et préciser l'objectif, par
exemple « Extraire fournisseur, numéro, date, HT, TVA et TTC dans un Excel ».
Envoyer, puis copier dans le chat la commande `fichiers autoriser M-xxx` affichée.
Suivre Mission Control. Le bouton « Afficher les exports Excel » donne les fichiers.
Chaque pièce jointe crée sa mission. Pour un récapitulatif commun de plusieurs
factures, demander dans le chat l'analyse du dossier qui les contient :

```text
Analyse le dossier "C:\Users\romai\Documents\Factures" et fais un récapitulatif Excel
```

La lecture de ce dossier nécessite un nouvel accord. Les originaux restent en place.
Les pièces reçues sont rangées dans `workspace/inbox/` sous un identifiant unique.
Aucune écriture ne peut écraser un autre téléversement. Les noms d'origine sont
présentés à la réception ; les fichiers locaux sont nommés document.extension.
Sans consigne, envoyer un seul fichier à la fois. Paul demande ensuite l'objectif
dans le panneau ; répondre dans la discussion principale.

Limites : 10 Mio/fichier, 100 fichiers/dossier, 30 pages/PDF, 24 000 caractères
analysés par document, XLSX limité à 1 000 lignes et 50 colonnes par feuille. Les
résultats tronqués sont signalés par le pipeline. Les formats non reconnus sont
refusés. Les pages avec très peu de texte passent par la vision ; une page avec
beaucoup de texte ET un tableau image peut nécessiter l'envoi du tableau en image.
Les montants extraits par IA restent à vérifier face aux originaux.

Vision : le lanceur utilise `qwen2.5vl:3b` par défaut. Pour changer avant démarrage :

```powershell
$env:AGENTOS_VISION_MODEL = "nom-du-modele-vision-installe"
.\.venv\Scripts\python.exe start_v10.py
```

Les contenus sont transmis au serveur Ollama configuré (localhost par défaut).
PDF chiffré, scan illisible ou modèle absent : échec explicite, pas de texte inventé.

## Telegram

Dans un deuxième terminal ouvert dans `agent-os-v10` :

```powershell
$env:TELEGRAM_BOT_TOKEN = "TOKEN_BOTFATHER"
$env:TELEGRAM_ALLOWED_CHAT_ID = "TON_CHAT_ID"
.\.venv\Scripts\python.exe telegram_client.py
```

Sans chat_id, `/id` permet de le connaître ; les autres opérations restent bloquées.
Envoyer une photo ou un document, avec l'objectif en légende. Paul renvoie une demande
d'autorisation M-xxx. Autoriser dans Telegram. Le client doit rester lancé pour recevoir
les notifications. Les exports se téléchargent depuis le Web ou le workspace ; cette
version ne renvoie pas encore le fichier Excel comme pièce jointe Telegram.

## Agent Zero : intégration réelle et limites

Base retrouvée : V7.0.0 + correctif V7.0.1. Aucune base V8/V9 n'a été retrouvée pour
cette livraison. Les adaptations Agent Zero existantes sont conservées : bus
extensions, contrats d'outils, restrictions par profil et hooks de missions.
Ce ZIP n'embarque pas le moteur complet Agent Zero, sa sandbox Docker ou ses plugins.
LangGraph et Microsoft Agent Framework ne sont pas intégrés. Aucune connexion fictive.
Le journal transactionnel spécifique est ajouté au-dessus de l'agenda Agent-OS ;
importer une deuxième mémoire opérationnelle créerait des sources concurrentes.
Licences et attribution conservées dans THIRD_PARTY_NOTICES.md et licenses/.

Références consultées :
- https://github.com/agent0ai/agent-zero
- https://docs.ollama.com/api/chat
- https://ollama.com/library/qwen2.5vl:3b
- https://core.telegram.org/bots/api#getfile

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m tests.run_all
```

Les tests utilisent des données temporaires. Ils ne vident pas vos données.
Les tests de vision remplacent le modèle par une réponse contrôlée : ils vérifient le
chemin PDF → image → texte, pas la qualité réelle de reconnaissance de vos factures.
Conserver une copie de `data/` et `workspace/` serveur arrêté pour sauvegarder vos
souvenirs, agenda et documents. Ne pas exposer le serveur local directement à Internet.
