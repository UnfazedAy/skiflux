from django.urls import path

from skiflux.views import CreatorManagementViewSet, StudioViewSet

urlpatterns = [
    path(
        "creator/register",
        StudioViewSet.as_view({"post": "register_creator"}),
        name="creator-register",
    ),
    path(
        "creator/verify-email",
        StudioViewSet.as_view({"post": "verify_creator_email"}),
        name="creator-verify-email",
    ),
    path(
        "creator/create-season",
        StudioViewSet.as_view({"post": "create_season"}),
        name="creator-season-create",
    ),
    path(
        "creator/list-seasons",
        StudioViewSet.as_view({"get": "list_seasons"}),
        name="creator-season-list",
    ),
    path(
        "creator/list-episodes",
        StudioViewSet.as_view({"get": "list_episodes"}),
        name="creator-episode-list",
    ),
    path(
        "creator/create-episode",
        StudioViewSet.as_view({"post": "create_episode"}),
        name="creator-episode-create",
    ),
    path(
        "creator/create-episode-review",
        StudioViewSet.as_view({"post": "create_episode_for_review"}),
        name="creator-episode-review-create",
    ),
    path(
        "creator/episode/<uuid:pk>/attach-task",
        StudioViewSet.as_view({"post": "attach_task"}),
        name="creator-episode-attach-task",
    ),
    path(
        "creator/episode/<uuid:pk>/update-task",
        StudioViewSet.as_view({"patch": "update_task"}),
        name="creator-episode-update-task",
    ),
    path(
        "creator/episode/<uuid:pk>/full-details",
        StudioViewSet.as_view({"get": "episode_full_details"}),
        name="creator-episode-full-details",
    ),
    path(
        "creator/episode/<uuid:pk>/reupload-video",
        StudioViewSet.as_view({"post": "reupload_episode_video"}),
        name="creator-episode-reupload-video",
    ),
    path(
        "creator/episode/<uuid:episode_id>/",
        StudioViewSet.as_view({"get": "get_episode_stats"}),
        name="creator-episode-stats",
    ),
    path(
        "creator/episode/<uuid:pk>/tasks/<uuid:task_id>/",
        StudioViewSet.as_view({"get": "get_episode_task"}),
        name="creator-episode-task",
    ),
    path(
        "creator/episode/<uuid:pk>/tasks/<uuid:task_id>/submissions/",
        StudioViewSet.as_view({"get": "get_task_submissions"}),
        name="creator-task-submissions",
    ),
    path(
        "creator/episode/<uuid:pk>/tasks/<uuid:task_id>/submissions/<uuid:submission_id>/reject/",
        StudioViewSet.as_view({"post": "reject_task_submission"}),
        name="creator-reject-task-submission",
    ),
    path(
        "creator/episode/<uuid:pk>/comments/",
        StudioViewSet.as_view({"get": "get_episode_comments"}),
        name="creator-episode-comments",
    ),
    path(
        "creator/resend-otp",
        StudioViewSet.as_view({"post": "resend_creator_otp"}),
        name="creator-resend-otp",
    ),
    path(
        "creator/profile",
        StudioViewSet.as_view({"get": "profile"}),
        name="creator-profile",
    ),
    path(
        "creator/stats",
        StudioViewSet.as_view({"get": "stats"}),
        name="creator-stats",
    ),
    path(
        "creator/update-profile",
        StudioViewSet.as_view({"post": "update_profile"}),
        name="creator-update-profile",
    ),
    path(
        "creator/devices",
        StudioViewSet.as_view({"post": "register_device"}),
        name="creator-devices-register",
    ),
    path(
        "creator/notifications",
        StudioViewSet.as_view({"get": "notifications"}),
        name="creator-notifications-list",
    ),
    path(
        "creator/notifications/<uuid:pk>/read",
        StudioViewSet.as_view({"post": "mark_notification_read"}),
        name="creator-notification-read",
    ),
    path(
        "admin/creators/",
        CreatorManagementViewSet.as_view({"get": "list"}),
        name="admin-creator-list",
    ),
    path(
        "admin/creators/<uuid:pk>/oversight/",
        CreatorManagementViewSet.as_view({"get": "oversight"}),
        name="admin-creator-oversight",
    ),
    path(
        "admin/creators/<uuid:pk>/profile/",
        CreatorManagementViewSet.as_view({"get": "profile"}),
        name="admin-creator-profile",
    ),
    path(
        "admin/creators/<uuid:pk>/override/",
        CreatorManagementViewSet.as_view({"patch": "override_episode"}),
        name="admin-creator-override",
    ),
    path(
        "admin/creators/<uuid:pk>/analytics/",
        CreatorManagementViewSet.as_view({"get": "analytics"}),
        name="admin-creator-analytics",
    ),
    path(
        "admin/creators/<uuid:pk>/episodes/",
        CreatorManagementViewSet.as_view({"get": "creator_episodes"}),
        name="admin-creator-episodes",
    ),
    path(
        "admin/creators/directory/stats/",
        CreatorManagementViewSet.as_view({"get": "directory_stats"}),
        name="admin-creator-directory-stats",
    ),
    path(
        "admin/creators/directory/",
        CreatorManagementViewSet.as_view({"get": "directory"}),
        name="admin-creator-directory",
    ),
    path(
        "creator/season/<uuid:season_id>/update",
        StudioViewSet.as_view({"patch": "update_season"}),
        name="creator-season-update",
    ),
    path(
        "creator/season/<uuid:season_id>/unpublish",
        StudioViewSet.as_view({"post": "unpublish_season"}),
        name="creator-season-unpublish",
    ),
    path(
        "creator/season/<uuid:season_id>/remove",
        StudioViewSet.as_view({"delete": "remove_season"}),
        name="creator-season-remove",
    ),
    path(
        "creator/episode/<uuid:episode_id>/update",
        StudioViewSet.as_view({"patch": "update_episode"}),
        name="creator-episode-update",
    ),
    path(
        "creator/episode/<uuid:episode_id>/unpublish",
        StudioViewSet.as_view({"post": "unpublish_episode"}),
        name="creator-episode-unpublish",
    ),
    path(
        "creator/episode/<uuid:episode_id>/remove",
        StudioViewSet.as_view({"delete": "remove_episode"}),
        name="creator-episode-remove",
    ),
]
