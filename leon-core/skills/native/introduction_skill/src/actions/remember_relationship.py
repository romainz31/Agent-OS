from bridges.python.src.sdk.leon import leon
from bridges.python.src.sdk.types import ActionParams
from ..lib import memory


def run(params: ActionParams) -> None:
    """Save the owner's explicitly stated partner name."""
    action_arguments = params.get('action_arguments', {})
    partner_name = action_arguments.get('partner_name')

    if not isinstance(partner_name, str) or not partner_name.strip():
        leon.answer({
            'core': {
                'should_stop_skill': True
            }
        })
        return

    owner = memory.get_owner() or {}
    owner['partner_name'] = partner_name.strip()
    memory.upsert_owner(owner)

    leon.answer({
        'key': 'relationship_remembered',
        'data': {
            'partner_name': owner['partner_name']
        }
    })
