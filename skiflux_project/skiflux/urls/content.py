from django.urls import path

from skiflux.views import ContentViewSet
from skiflux.views.episode_resource import (
    EpisodeResourceStudioViewSet,
    EpisodeResourceLearnerViewSet,
)

urlpatterns = [
    path(
        "episodes/track-view",
        ContentViewSet.as_view({"post": "track_view"}),
    ),
    path(
        "episodes/purchase",
        ContentViewSet.as_view({"post": "purchase_episode"}),
    ),
    path(
        "episodes/recommendations",
        ContentViewSet.as_view(
            {"get": "recommendations"},
        ),
    ),
    path(
        "episodes/<uuid:episode_id>",
        ContentViewSet.as_view({"get": "get_episode"}),
        name="episode-detail",
    ),
    path(
        "episodes/task/submit",
        ContentViewSet.as_view({"post": "submit_task"}),
    ),
    path(
        "episodes/watched/tasks",
        ContentViewSet.as_view({"get": "get_watched_episode_tasks"}),
    ),
    path(
        "episodes/like",
        ContentViewSet.as_view({"post": "like_episode"}),
    ),
    path(
        "episodes/save",
        ContentViewSet.as_view({"post": "save_episode"}),
    ),
    path(
        "episodes/not-interested",
        ContentViewSet.as_view({"post": "not_interested_episode"}),
    ),
    path(
        "episodes/comment",
        ContentViewSet.as_view({"post": "add_comment"}),
    ),
    path(
        "episodes/<uuid:pk>/comments",
        ContentViewSet.as_view({"get": "get_comments"}),
    ),
    path(
        "comments/like",
        ContentViewSet.as_view({"post": "like_comment"}),
    ),
    path(
        "comments/<int:comment_id>/",
        ContentViewSet.as_view({"delete": "delete_comment", "patch": "edit_comment"}),
    ),
    path(
        "comments/<int:comment_id>/reply/",
        ContentViewSet.as_view({"post": "reply_to_comment"}),
    ),
    path(
        "seasons",
        ContentViewSet.as_view({"get": "list_seasons"}),
        name="seasons-list",
    ),
    path(
        "seasons/<uuid:season_id>/episodes",
        ContentViewSet.as_view({"get": "get_season_episodes"}),
        name="season-episodes",
    ),
    path(
        "creators/<uuid:creator_id>",
        ContentViewSet.as_view({"get": "get_creator_profile"}),
        name="creator-public-profile",
    ),
    path(
        "creators/<uuid:creator_id>/seasons",
        ContentViewSet.as_view({"get": "get_creator_seasons"}),
        name="creator-seasons",
    ),
    path(
        "creators/<uuid:creator_id>/episodes",
        ContentViewSet.as_view({"get": "get_creator_episodes"}),
        name="creator-episodes",
    ),
    path(
        "creators/<uuid:creator_id>/follow/",
        ContentViewSet.as_view({"post": "toggle_follow"}),
        name="creator-toggle-follow",
    ),
    path(
        "creators/following/",
        ContentViewSet.as_view({"get": "get_followed_creators"}),
        name="creators-following",
    ),
    path(
        "episodes/following/",
        ContentViewSet.as_view({"get": "get_latest_followed_episodes"}),
        name="episodes-following",
    ),
    path(
        "episodes/<uuid:episode_id>/rate/",
        ContentViewSet.as_view({"post": "rate_episode"}),
        name="episode-rate",
    ),
    path(
        "episodes/<uuid:episode_id>/resources/",
        EpisodeResourceStudioViewSet.as_view({"get": "list_resources"}),
        name="studio-episode-resources-list",
    ),
    path(
        "episodes/<uuid:episode_id>/resources/files/",
        EpisodeResourceStudioViewSet.as_view({"post": "add_files"}),
        name="studio-episode-resources-add-files",
    ),
    path(
        "episodes/<uuid:episode_id>/resources/links/",
        EpisodeResourceStudioViewSet.as_view({"post": "add_links"}),
        name="studio-episode-resources-add-link",
    ),
    path(
        "episodes/<uuid:episode_id>/resources/reorder/",
        EpisodeResourceStudioViewSet.as_view({"patch": "reorder_resources"}),
        name="studio-episode-resources-reorder",
    ),
    path(
        "episodes/<uuid:episode_id>/resources/<uuid:resource_id>/link/",
        EpisodeResourceStudioViewSet.as_view({"patch": "update_link"}),
        name="studio-episode-resources-update-link",
    ),
    path(
        "episodes/<uuid:episode_id>/resources/<uuid:resource_id>/",
        EpisodeResourceStudioViewSet.as_view({"delete": "delete_resource"}),
        name="studio-episode-resources-delete",
    ),
    # ─────────────────────────────────────────
    # Learner
    # ─────────────────────────────────────────
    path(
        "episodes/<uuid:episode_id>/resources/",
        EpisodeResourceLearnerViewSet.as_view({"get": "list_resources"}),
        name="learner-episode-resources-list",
    ),
]
