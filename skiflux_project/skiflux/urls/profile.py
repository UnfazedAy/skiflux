from django.urls import include, path
from rest_framework.routers import DefaultRouter

from skiflux.views.profile import UserProfileViewSet
from skiflux.views.gamification import (
    get_user_badges,
    get_user_streak,
    list_platform_tasks,
    start_platform_task,
    submit_platform_task,
    claim_platform_task,
    complete_platform_task,
)

router = DefaultRouter(trailing_slash=False)
router.register(r"me", UserProfileViewSet, basename="me")

urlpatterns = [
    path("me/badges", get_user_badges, name="learner-badges"),
    path("me/streak", get_user_streak, name="learner-streak"),
    path("me/platform-tasks", list_platform_tasks, name="learner-platform-tasks"),
    path(
        "me/platform-tasks/<str:task_id>/start",
        start_platform_task,
        name="learner-start-platform-task",
    ),
    path(
        "me/platform-tasks/<str:task_id>/submit",
        submit_platform_task,
        name="learner-submit-platform-task",
    ),
    path(
        "me/platform-tasks/<str:task_id>/claim",
        claim_platform_task,
        name="learner-claim-platform-task",
    ),
    path(
        "me/platform-tasks/<str:task_id>/complete",
        complete_platform_task,
        name="learner-complete-platform-task",
    ),
    path("", include(router.urls)),
]
