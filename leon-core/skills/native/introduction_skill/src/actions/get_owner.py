from bridges.python.src.sdk.leon import leon
from bridges.python.src.sdk.types import ActionParams
from ..lib import memory


def run(params: ActionParams) -> None:
    """Answer with the owner's saved basic profile information."""
    owner = memory.get_owner()
    owner_name = owner.get('name') if owner else None
    owner_location = owner.get('location') if owner else None

    if (
        isinstance(owner_name, str)
        and owner_name.strip()
        and isinstance(owner_location, str)
        and owner_location.strip()
    ):
        leon.answer({
            'key': 'owner_known_with_location',
            'data': {
                'owner_name': owner_name,
                'owner_location': owner_location
            }
        })
        return

    if isinstance(owner_name, str) and owner_name.strip():
        leon.answer({
            'key': 'owner_known',
            'data': {'owner_name': owner_name}
        })
        return

    if isinstance(owner_location, str) and owner_location.strip():
        leon.answer({
            'key': 'owner_location_known',
            'data': {'owner_location': owner_location}
        })
        return

    if not isinstance(owner_name, str) or not owner_name.strip():
        leon.answer({'key': 'owner_unknown'})
        return
