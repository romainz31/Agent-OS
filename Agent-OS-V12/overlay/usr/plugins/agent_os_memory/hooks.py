from usr.plugins.agent_os_memory.helpers.runtime import get_store


def install():
    """Create or upgrade the database without touching existing rows."""
    get_store()


def pre_update():
    return None


def uninstall():
    """Code removal deliberately preserves the user's personal database."""
    return None
