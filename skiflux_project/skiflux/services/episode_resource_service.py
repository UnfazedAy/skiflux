import logging
import mimetypes

from django.db import transaction
from rest_framework.exceptions import ValidationError

from skiflux.models import AdminUser
from skiflux.models.content import Episode
from skiflux.models.content import EpisodeResource
from rest_framework.exceptions import PermissionDenied
from skiflux.repositories.episode_resource_repository import EpisodeResourceRepository
from skiflux.tasks.content import upload_media_from_minio_task
from skiflux.utils.media import upload_to_minio

logger = logging.getLogger(__name__)


MAX_FILE_SIZE_MB = 50
MAX_RESOURCES_PER_EPISODE = 10


def can_access_episode(self, episode):
    return self.is_super_admin or episode.creator_id == self.id


class EpisodeResourceService:
    def __init__(self):
        self.repo = EpisodeResourceRepository()

    def _get_episode_or_raise(self, episode_id: str, creator: AdminUser) -> Episode:
        try:
            episode = Episode.objects.get(id=episode_id)
        except Episode.DoesNotExist:
            raise ValidationError("Episode not found.")

        if not (creator.is_super_admin or episode.creator_id == creator.id):
            raise PermissionDenied("You do not own this episode.")

        return episode

    def _get_resource_or_raise(
        self,
        resource_id: str,
        episode: Episode,
    ) -> EpisodeResource:
        resource = self.repo.get_resource_by_id(resource_id, episode=episode)
        if not resource:
            raise ValidationError("Resource not found.")
        return resource

    def _resolve_file_type(self, content_type: str, filename: str) -> str:
        # try MIME type first
        file_type = EpisodeResource.FileType.from_mime_type(content_type)
        if file_type:
            return file_type

        # fallback to extension
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        ext_map = {
            "pdf": EpisodeResource.FileType.PDF,
            "zip": EpisodeResource.FileType.ZIP,
            "fig": EpisodeResource.FileType.FIGMA,
            "jpg": EpisodeResource.FileType.IMAGE,
            "jpeg": EpisodeResource.FileType.IMAGE,
            "png": EpisodeResource.FileType.IMAGE,
            "gif": EpisodeResource.FileType.IMAGE,
            "webp": EpisodeResource.FileType.IMAGE,
            "doc": EpisodeResource.FileType.DOC,
            "docx": EpisodeResource.FileType.DOC,
            "txt": EpisodeResource.FileType.DOC,
        }
        return ext_map.get(ext, EpisodeResource.FileType.OTHER)

    def _check_resource_limit(self, episode: Episode) -> None:
        count = EpisodeResource.objects.filter(episode=episode).count()
        if count >= MAX_RESOURCES_PER_EPISODE:
            raise ValidationError(
                f"Episodes can have a maximum of {MAX_RESOURCES_PER_EPISODE} resources."
            )

    def get_resources(
        self,
        episode_id: str,
        creator: AdminUser = None,
    ):
        """
        Creator context: validates ownership.
        No creator context: public read for learners.
        """
        try:
            episode = Episode.objects.get(id=episode_id)
        except Episode.DoesNotExist:
            raise ValidationError("Episode not found.")

        if creator and str(episode.creator_id) != str(creator.id):
            raise ValidationError("You do not own this episode.")

        return self.repo.get_resources_for_episode(episode)

    def add_file_resources(
        self,
        episode_id: str,
        creator: AdminUser,
        files: list,
    ) -> list[EpisodeResource]:
        """
        Upload multiple file resources in one request.

        Each file becomes its own EpisodeResource and its own
        Celery upload task.
        """

        if not files:
            raise ValidationError("At least one file is required.")

        episode = self._get_episode_or_raise(episode_id, creator)

        existing_count = EpisodeResource.objects.filter(episode=episode).count()

        total_after_upload = existing_count + len(files)

        if total_after_upload > MAX_RESOURCES_PER_EPISODE:
            raise ValidationError(
                f"This upload would exceed the maximum of "
                f"{MAX_RESOURCES_PER_EPISODE} resources per episode."
            )

        resources = []

        with transaction.atomic():
            base_order = self.repo.get_next_order(episode)

            for index, file in enumerate(files):
                max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

                if file.size > max_bytes:
                    raise ValidationError(
                        f"{file.name}: file size cannot exceed {MAX_FILE_SIZE_MB}MB."
                    )

                content_type = getattr(
                    file,
                    "content_type",
                    mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                )

                file_type = self._resolve_file_type(
                    content_type,
                    file.name,
                )

                blocked_extensions = {
                    "exe",
                    "msi",
                    "bat",
                    "cmd",
                    "sh",
                    "com",
                    "scr",
                }

                ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""

                if ext in blocked_extensions:
                    raise ValidationError(f"{ext} files are not allowed.")

                resource = self.repo.create_file_resource(
                    episode=episode,
                    file_name=file.name,
                    file_size=file.size,
                    file_type=file_type,
                    content_type=content_type,
                    order=base_order + index,
                )

                resource.is_processing = True
                resource.save(update_fields=["is_processing"])

                minio_key = upload_to_minio(
                    file,
                    folder="skiflux_episode_resources",
                )

                transaction.on_commit(
                    lambda key=minio_key, rid=str(resource.id), ct=content_type: (
                        upload_media_from_minio_task.delay(
                            instance_id=rid,
                            minio_object_key=key,
                            field_name="file_public_id",
                            model_name="EpisodeResource",
                            resource_type=(
                                "raw"
                                if ct.startswith("application/")
                                or ct.startswith("text/")
                                else "image"
                            ),
                            content_type=ct,
                        )
                    )
                )

                resources.append(resource)

        logger.info(f"Queued {len(resources)} resources for episode {episode_id}")

        return resources

    # def add_link_resources(
    #     self,
    #     episode_id: str,
    #     creator: AdminUser,
    #     label: str,
    #     url: str,
    # ) -> EpisodeResource:
    #     episode = self._get_episode_or_raise(episode_id, creator)
    #     self._check_resource_limit(episode)

    #     if not label or not label.strip():
    #         raise ValidationError("Link label is required.")

    #     if not url or not url.strip():
    #         raise ValidationError("Link URL is required.")

    #     order = self.repo.get_next_order(episode)

    #     return self.repo.create_link_resource(
    #         episode=episode,
    #         label=label.strip(),
    #         url=url.strip(),
    #         order=order,
    #     )

    def add_link_resources(
        self,
        episode_id: str,
        creator: AdminUser,
        links: list[dict],  # list of {"label": str, "url": str}
    ) -> list[EpisodeResource]:
        """
        Add multiple link resources in one request.

        Each link in the list becomes its own EpisodeResource.

        Args:
            episode_id: The ID of the episode
            creator: The admin user creating the resources
            links: List of dictionaries with 'label' and 'url' keys

        Returns:
            List of created EpisodeResource objects
        """
        if not links:
            raise ValidationError("At least one link is required.")

        episode = self._get_episode_or_raise(episode_id, creator)

        existing_count = EpisodeResource.objects.filter(episode=episode).count()
        total_after_upload = existing_count + len(links)

        if total_after_upload > MAX_RESOURCES_PER_EPISODE:
            raise ValidationError(
                f"This upload would exceed the maximum of "
                f"{MAX_RESOURCES_PER_EPISODE} resources per episode."
            )

        # Validate all links first
        for link in links:
            label = link.get("label", "").strip()
            url = link.get("url", "").strip()

            if not label:
                raise ValidationError("Link label is required for all links.")

            if not url:
                raise ValidationError("Link URL is required for all links.")

            # Optional: Add URL validation
            if not url.startswith(("http://", "https://")):
                raise ValidationError(
                    f"URL '{url}' must start with http:// or https://"
                )

        resources = []

        with transaction.atomic():
            base_order = self.repo.get_next_order(episode)

            for index, link in enumerate(links):
                resource = self.repo.create_link_resource(
                    episode=episode,
                    label=link["label"].strip(),
                    url=link["url"].strip(),
                    order=base_order + index,
                )
                resources.append(resource)

        logger.info(f"Created {len(resources)} link resources for episode {episode_id}")

        return resources

    def update_link_resource(
        self,
        episode_id: str,
        resource_id: str,
        creator: AdminUser,
        label: str = None,
        url: str = None,
    ) -> EpisodeResource:
        episode = self._get_episode_or_raise(episode_id, creator)
        resource = self._get_resource_or_raise(resource_id, episode)

        if resource.resource_type != EpisodeResource.ResourceType.LINK:
            raise ValidationError("Only link resources can be updated this way.")

        return self.repo.update_link_resource(resource, label=label, url=url)

    def delete_resource(
        self,
        episode_id: str,
        resource_id: str,
        creator: AdminUser,
    ) -> None:
        episode = self._get_episode_or_raise(episode_id, creator)
        resource = self._get_resource_or_raise(resource_id, episode)

        # clean up Cloudinary asset if file
        if (
            resource.resource_type == EpisodeResource.ResourceType.FILE
            and resource.file_public_id
        ):
            try:
                from skiflux.tasks.content import cleanup_cloudinary_asset_task

                resource_type = (
                    "image"
                    if resource.file_type == EpisodeResource.FileType.IMAGE
                    else "raw"
                )
                cleanup_cloudinary_asset_task.delay(
                    resource.file_public_id,
                    resource_type=resource_type,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to queue Cloudinary cleanup for resource "
                    f"{resource_id}: {e}"
                )

        self.repo.delete_resource(resource)

    def reorder_resources(
        self,
        episode_id: str,
        creator: AdminUser,
        reorder_data: list[dict],
    ) -> None:
        """
        reorder_data: [{"id": "uuid", "order": 0}, ...]
        """
        episode = self._get_episode_or_raise(episode_id, creator)

        # validate all IDs belong to this episode
        ids = [item["id"] for item in reorder_data]
        existing_ids = set(
            EpisodeResource.objects.filter(episode=episode, id__in=ids).values_list(
                "id", flat=True
            )
        )
        # convert to str for comparison
        existing_ids_str = {str(i) for i in existing_ids}
        for item_id in ids:
            if str(item_id) not in existing_ids_str:
                raise ValidationError(
                    f"Resource {item_id} does not belong to this episode."
                )

        self.repo.bulk_reorder(reorder_data)
