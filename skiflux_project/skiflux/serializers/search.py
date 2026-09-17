from rest_framework import serializers

from skiflux.models import User
from skiflux.serializers.studio import (
    CreatorSerializer,
    EpisodeSerializer,
    SeasonSerializer,
)


class BasicUserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "username", "avatar_url"]

    def get_name(self, obj) -> str:
        return f"{obj.first_name} {obj.last_name}".strip()


class PaginatedListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)


class PaginatedEpisodeSerializer(PaginatedListSerializer):
    results = EpisodeSerializer(many=True, read_only=True)


class PaginatedSeasonSerializer(PaginatedListSerializer):
    results = SeasonSerializer(many=True, read_only=True)


class PaginatedCreatorSerializer(PaginatedListSerializer):
    results = CreatorSerializer(many=True, read_only=True)


class PaginatedUserSerializer(PaginatedListSerializer):
    results = BasicUserSerializer(many=True, read_only=True)


class GlobalSearchResponseSerializer(serializers.Serializer):
    episodes = PaginatedEpisodeSerializer(read_only=True)
    seasons = PaginatedSeasonSerializer(read_only=True)
    creators = PaginatedCreatorSerializer(read_only=True)
    users = PaginatedUserSerializer(read_only=True)
