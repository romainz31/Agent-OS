AGENT-OS V5.2 — SKILL REGISTRY
================================

V5.2 ajoute une mémoire technique séparée de la mémoire personnelle.

NOUVEAU
-------
- data/skills.json persistant
- compétences avec :
  - nom / clé stable
  - niveau
  - confiance
  - confiance effective
  - fraîcheur
  - sources classées A/B/C/D
  - notes
  - connaissances structurées
  - workers associés
  - compteur d'utilisation
- skills requis par mission
- héritage automatique parent -> sous-mission
- détection des compétences manquantes
- injection de skill_context dans le payload envoyé au worker
- API GET /api/skills
- API GET /api/skills/{name}
- commandes Telegram /skills, /skill, /skillrequire, /skillrequirements

IMPORTANT
---------
V5.2 construit le registre et le pipeline de connaissances.
Les agents ne recherchent PAS ENCORE automatiquement une compétence absente.
Ce sera V5.4 après les spécialistes dynamiques V5.3.

COMMANDES UTILES
----------------
skills
skill add yaml
skill yaml
skill level yaml intermediate
skill confidence yaml 0.80
skill worker yaml developer
skill source yaml A https://yaml.org/spec/
skill note yaml : respecter strictement l'indentation
skill require M-043 yaml, home_assistant
skill requirements M-043

TELEGRAM
--------
/skills
/skill yaml
/skill add yaml
/skillrequire M-043 yaml, home_assistant
/skillrequirements M-043

NIVEAUX
-------
novice
basic / basique
intermediate / intermédiaire
advanced / avancé
expert

SOURCES
-------
A : documentation / source officielle
B : documentation reconnue / projet primaire
C : communauté technique / Stack Overflow / forum / blog sérieux
D : source non vérifiée / piste de recherche

TESTS
-----
python .\test_v50.py
python .\test_v51.py
python .\test_v52.py
python .\test_telegram_commands.py

Résultats attendus :
- V5.0 : 37 contrôles
- V5.1 : 47 contrôles
- V5.2 : 52 contrôles
- Telegram : tous les tests passent

TEST RÉEL CONSEILLÉ
-------------------
1. skill add yaml
2. skill level yaml intermediate
3. skill confidence yaml 0.80
4. skill worker yaml developer
5. skill source yaml A https://yaml.org/spec/
6. skill require M-XXX yaml
7. skill requirements M-XXX
8. skill yaml

Sur une sous-mission de M-XXX, "skill requirements M-YYY" doit aussi afficher
YAML par héritage, même si YAML n'a été déclaré que sur le parent.
