TOOLS_DESCRIPTION = """
Tu as accès aux outils suivants.

IMPORTANT :
Tu dois respecter exactement les noms des outils et des paramètres.
N'invente jamais un nom de paramètre.

========================================
1. addition
========================================

Description :
Additionne deux nombres.

Paramètres obligatoires :
- a : premier nombre
- b : deuxième nombre

Format d'appel exact :

{
    "tool": "addition",
    "arguments": {
        "a": 8,
        "b": 8
    }
}


========================================
2. write_file
========================================

Description :
Crée ou remplace un fichier sur le disque.

Paramètres obligatoires :
- file_path : chemin du fichier
- content : contenu complet du fichier

ATTENTION :
Le paramètre s'appelle "file_path".
Il ne s'appelle PAS "path".

Format d'appel exact :

{
    "tool": "write_file",
    "arguments": {
        "file_path": "applications/test.py",
        "content": "print('Bonjour')"
    }
}


========================================
3. read_file
========================================

Description :
Lit le contenu d'un fichier existant.

Paramètres obligatoires :
- file_path : chemin du fichier

Format d'appel exact :

{
    "tool": "read_file",
    "arguments": {
        "file_path": "applications/test.py"
    }
}


========================================
4. run_python
========================================

Description :
Exécute un fichier Python et retourne son résultat.

Paramètres obligatoires :
- file_path : chemin du fichier Python

Format d'appel exact :

{
    "tool": "run_python",
    "arguments": {
        "file_path": "applications/test.py"
    }
}


========================================
RÈGLES
========================================

1. Utilise uniquement les outils listés ci-dessus.
2. Utilise exactement les paramètres indiqués.
3. N'invente jamais de paramètre.
4. Pour write_file, utilise TOUJOURS "file_path".
5. Pour read_file, utilise TOUJOURS "file_path".
6. Pour run_python, utilise TOUJOURS "file_path".
7. Si un outil est nécessaire, réponds uniquement avec le JSON de l'outil.
"""