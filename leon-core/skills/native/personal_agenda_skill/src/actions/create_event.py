from bridges.python.src.sdk.leon import leon
from bridges.python.src.sdk.types import ActionParams
from bridges.python.src.sdk.params_helper import ParamsHelper
from ..lib import memory


def run(params: ActionParams, params_helper: ParamsHelper) -> None:
    """Save a dated personal agenda event."""
    event_title = params_helper.get_action_argument('event_title').strip()
    event_date = params_helper.get_action_argument('event_date').strip()
    event_time = params.get('action_arguments', {}).get('event_time', '')
    time_suffix = f" à {event_time.strip()}" if isinstance(event_time, str) and event_time.strip() else ''

    event = {
        'title': event_title,
        'date': event_date,
        'time': event_time.strip() if isinstance(event_time, str) else ''
    }
    memory.add_event(event)

    leon.answer({
        'key': 'event_created',
        'data': {
            'title': event_title,
            'date': event_date,
            'time_suffix': time_suffix
        }
    })
