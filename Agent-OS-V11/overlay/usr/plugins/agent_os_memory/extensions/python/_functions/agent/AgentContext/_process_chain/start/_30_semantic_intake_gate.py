from helpers.extension import Extension


class SemanticPersonalIntakeGateDisabledV114(Extension):
    """V11.5 : ancien gate plugin neutralisé.

    Le gate actif est installé sous usr/extensions afin d'être découvert même si
    l'ordre/la portée des plugins change. Garder ce fichier évite un double
    traitement après mise à jour depuis V11.3.
    """

    async def execute(self, **kwargs):
        return None
