from bridges.python.src.sdk.leon import leon
from bridges.python.src.sdk.types import ActionParams
from ..lib import memory


def run(params: ActionParams) -> None:
    """Answer with the owner's saved partner name."""
    owner = memory.get_owner()
    partner_name = owner.get('partner_name') if owner else None

    if not isinstance(partner_name, str) or not partner_name.strip():
        leon.answer({'key': 'relationship_unknown'})
        return

    leon.answer({
        'key': 'relationship_known',
        'data': {'partner_name': partner_name}
    })
