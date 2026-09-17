from skiflux.models import Episode
from skiflux.models.wallet import SystemFinancialConfig
from skiflux.repositories.content_repository import ContentRepository


def _episode_ids_from_items(items) -> list:
    episode_ids = []
    for item in items or []:
        if isinstance(item, Episode):
            episode_ids.append(item.id)
        elif hasattr(item, "episode_id"):
            episode_ids.append(item.episode_id)
        elif hasattr(item, "episode") and item.episode is not None:
            episode_ids.append(item.episode.id)
    return episode_ids


def build_episode_serializer_context(request, items=None) -> dict:
    """Build serializer context with request and batched purchase lookups."""
    ctx = {"request": request}
    purchased_ids = set()
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        episode_ids = _episode_ids_from_items(items)
        if episode_ids:
            purchased_ids = ContentRepository().get_purchased_episode_ids(
                user, episode_ids
            )
    ctx["purchased_episode_ids"] = purchased_ids
    ctx["episode_purchase_price_skillcoins"] = (
        SystemFinancialConfig.get_config().episode_purchase_price_skillcoins
    )
    return ctx
