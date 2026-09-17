from rest_framework import serializers

from skiflux.models.content import EpisodeResource


class EpisodeResourceSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = EpisodeResource
        fields = [
            "id",
            "resource_type",
            "file_name",
            "file_size",
            "file_type",
            "content_type",
            "file_public_id",
            "file_url",
            "is_processing",
            "link_label",
            "link_url",
            "order",
            "created_at",
        ]

    def get_file_url(self, obj) -> str | None:
        if obj.resource_type != EpisodeResource.ResourceType.FILE:
            return None
        if not obj.file_public_id:
            return None
        if obj.file_url:
            return obj.file_url
        try:
            from skiflux.utils.media import get_private_media_url

            resource_type = (
                "image" if obj.file_type == EpisodeResource.FileType.IMAGE else "raw"
            )
            return get_private_media_url(
                obj.file_public_id, resource_type=resource_type
            )
        except Exception:
            return None


class AddFileResourceSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(),
        min_length=1,
        help_text="list of files to upload.",
    )


class LinkItemSerializer(serializers.Serializer):
    label = serializers.CharField(
        max_length=255,
        help_text="e.g. Reference article",
    )
    url = serializers.URLField(
        max_length=2000,
        help_text="https://...",
    )


class AddLinkResourceSerializer(serializers.Serializer):
    links = serializers.ListField(
        child=LinkItemSerializer(),
        min_length=1,
        max_length=10,
        help_text="List of link resources to add",
    )


class UpdateLinkResourceSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=255, required=False)
    url = serializers.URLField(max_length=2000, required=False)

    def validate(self, data):
        if not data.get("label") and not data.get("url"):
            raise serializers.ValidationError(
                "At least one of label or url is required."
            )
        return data


class ReorderResourceItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order = serializers.IntegerField(min_value=0)


class ReorderResourcesSerializer(serializers.Serializer):
    resources = serializers.ListField(
        child=ReorderResourceItemSerializer(),
        min_length=1,
        help_text="List of resource IDs with their new order.",
    )

    def validate_resources(self, value):
        ids = [str(item["id"]) for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Duplicate resource IDs are not allowed.")
        return value
