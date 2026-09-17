from skiflux.models.content import Episode
from skiflux.models.content import EpisodeResource


class EpisodeResourceRepository:
    def get_resources_for_episode(self, episode: Episode):
        return EpisodeResource.objects.filter(episode=episode).order_by(
            "order", "created_at"
        )

    def get_resource_by_id(
        self,
        resource_id: str,
        episode: Episode = None,
    ) -> EpisodeResource | None:
        try:
            qs = EpisodeResource.objects.filter(id=resource_id)
            if episode:
                qs = qs.filter(episode=episode)
            return qs.get()
        except EpisodeResource.DoesNotExist:
            return None

    def create_file_resource(
        self,
        episode: Episode,
        file_name: str,
        file_size: int,
        file_type: str,
        content_type: str,
        order: int = 0,
    ) -> EpisodeResource:
        return EpisodeResource.objects.create(
            episode=episode,
            resource_type=EpisodeResource.ResourceType.FILE,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            content_type=content_type,
            is_processing=True,
            order=order,
        )

    def create_link_resource(
        self,
        episode: Episode,
        label: str,
        url: str,
        order: int = 0,
    ) -> EpisodeResource:
        return EpisodeResource.objects.create(
            episode=episode,
            resource_type=EpisodeResource.ResourceType.LINK,
            link_label=label,
            link_url=url,
            order=order,
        )

    def update_link_resource(
        self,
        resource: EpisodeResource,
        label: str = None,
        url: str = None,
    ) -> EpisodeResource:
        if label is not None:
            resource.link_label = label
        if url is not None:
            resource.link_url = url
        resource.save(update_fields=["link_label", "link_url", "updated_at"])
        return resource

    def update_order(
        self,
        resource: EpisodeResource,
        order: int,
    ) -> EpisodeResource:
        resource.order = order
        resource.save(update_fields=["order", "updated_at"])
        return resource

    def delete_resource(self, resource: EpisodeResource) -> None:
        resource.delete()

    def bulk_reorder(self, reorder_data: list[dict]) -> None:
        """
        reorder_data: [{"id": "...", "order": 0}, ...]
        """
        for item in reorder_data:
            EpisodeResource.objects.filter(id=item["id"]).update(order=item["order"])

    def get_next_order(self, episode: Episode) -> int:
        """Returns the next available order index for an episode."""
        last = (
            EpisodeResource.objects.filter(episode=episode)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        return (last + 1) if last is not None else 0
