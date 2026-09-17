from skiflux.services.platform_task_service import PlatformTaskService


def trigger_platform_task(user, trigger_type: str, increment: int = 1) -> None:
    """Fire-and-forget helper for hooking platform tasks into other services."""
    if not trigger_type:
        return
    PlatformTaskService().handle_trigger(user, trigger_type, increment=increment)
