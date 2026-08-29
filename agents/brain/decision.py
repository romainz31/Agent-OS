import json
import re


def analyze_response(response):

    if not response:
        return None

    response = response.strip()

    # ==================================================
    # JSON DIRECT
    # ==================================================

    try:
        return json.loads(response)

    except json.JSONDecodeError:
        pass

    # ==================================================
    # JSON DANS DU TEXTE
    # ==================================================

    matches = re.findall(
        r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}",
        response,
        re.DOTALL
    )

    for match in matches:

        try:
            return json.loads(match)

        except json.JSONDecodeError:
            continue

    return None