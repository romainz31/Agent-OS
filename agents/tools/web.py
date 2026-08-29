import requests
from bs4 import BeautifulSoup


def fetch_webpage(url):
    """
    Récupère une page web et extrait son contenu textuel.
    """

    if not url:
        return {
            "success": False,
            "error": "Aucune URL fournie."
        }

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
            )
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # ----------------------------------------------------
        # Suppression des éléments inutiles
        # ----------------------------------------------------

        for element in soup([
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "footer"
        ]):

            element.decompose()

        # ----------------------------------------------------
        # Titre
        # ----------------------------------------------------

        title = ""

        if soup.title and soup.title.string:

            title = soup.title.string.strip()

        # ----------------------------------------------------
        # Extraction du texte
        # ----------------------------------------------------

        text = soup.get_text(
            separator="\n"
        )

        lines = []

        for line in text.splitlines():

            line = line.strip()

            if line:

                lines.append(line)

        text = "\n".join(lines)

        # ----------------------------------------------------
        # Limitation de sécurité
        # ----------------------------------------------------

        max_length = 50000

        truncated = False

        if len(text) > max_length:

            text = text[:max_length]

            truncated = True

        return {

            "success":
                True,

            "url":
                url,

            "title":
                title,

            "content":
                text,

            "truncated":
                truncated,

            "characters":
                len(text)

        }

    except requests.exceptions.RequestException as e:

        return {

            "success":
                False,

            "url":
                url,

            "error":
                f"Erreur réseau : {str(e)}"

        }

    except Exception as e:

        return {

            "success":
                False,

            "url":
                url,

            "error":
                str(e)

        }