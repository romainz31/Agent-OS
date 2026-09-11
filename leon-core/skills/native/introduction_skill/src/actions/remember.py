from bridges.python.src.sdk.leon import leon
from bridges.python.src.sdk.types import ActionParams
from ..lib import memory


def run(params: ActionParams) -> None:
    """Save explicit owner profile information into Leon's memory."""
    action_arguments = params.get('action_arguments', {})
    owner_name = action_arguments.get('owner_name')
    owner_birth_date = action_arguments.get('owner_birth_date')
    owner_location = action_arguments.get('owner_location')
    owner_work = action_arguments.get('owner_work')

    if (
        not isinstance(owner_name, str)
        and not isinstance(owner_birth_date, str)
        and not isinstance(owner_location, str)
        and not isinstance(owner_work, str)
    ):
        leon.answer({
            'core': {
                'should_stop_skill': True
            }
        })
        return

    owner = memory.get_owner() or {}
    if isinstance(owner_name, str):
        owner['name'] = owner_name
    if isinstance(owner_birth_date, str):
        owner['birth_date'] = owner_birth_date
    if isinstance(owner_location, str):
        owner['location'] = owner_location
    if isinstance(owner_work, str):
        owner['work'] = owner_work
    memory.upsert_owner(owner)

    if (
        isinstance(owner_name, str)
        and isinstance(owner_location, str)
        and isinstance(owner_work, str)
    ):
        leon.answer({
            'key': 'remembered_with_location_and_work',
            'data': {
                'owner_name': owner.get('name', ''),
                'owner_location': owner['location'],
                'owner_work': owner['work']
            }
        })
        return

    if isinstance(owner_name, str) and isinstance(owner_location, str):
        leon.answer({
            'key': 'remembered_with_location',
            'data': {
                'owner_name': owner.get('name', ''),
                'owner_location': owner['location']
            }
        })
        return

    if isinstance(owner_name, str) and isinstance(owner_work, str):
        leon.answer({
            'key': 'remembered_with_work',
            'data': {
                'owner_name': owner.get('name', ''),
                'owner_work': owner['work']
            }
        })
        return

    if isinstance(owner_location, str):
        leon.answer({
            'key': 'remembered_location',
            'data': {'owner_location': owner['location']}
        })
        return

    if isinstance(owner_work, str):
        leon.answer({
            'key': 'remembered_work',
            'data': {'owner_work': owner['work']}
        })
        return

    leon.answer({
        'key': 'remembered',
        'data': {
            'owner_name': owner.get('name', '')
        }
    })
