from bridges.python.src.sdk.leon import leon
from bridges.python.src.sdk.types import ActionParams
from ..lib import memory


def run(params: ActionParams) -> None:
    """Answer with the owner's saved basic profile information."""
    owner = memory.get_owner()
    owner_name = owner.get('name') if owner else None

    if not isinstance(owner_name, str) or not owner_name.strip():
        leon.answer({'key': 'owner_unknown'})
        return

    leon.answer({
        'key': 'owner_known',
        'data': {'owner_name': owner_name}
    })
