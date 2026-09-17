from django.test import TestCase

from skiflux.models.content import EpisodeTask, TaskSubmission, AssessmentSubmission
from skiflux.models.role import Permission
from .conftest import (
    admin_auth_client,
    make_creator,
    make_episode,
    make_season,
    make_admin_with_role,
    make_admin,
    make_verified_user,
)

BASE = "/api/v1"


class EpisodeFullDetailsTests(TestCase):
    def setUp(self):
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(self.creator, self.season)

    def test_creator_can_fetch_full_details(self):
        client = admin_auth_client(self.creator)

        # create tasks
        project = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Do it",
        )
        assessment = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.ASSESSMENT,
            pass_score_percent=50,
        )

        # create users and submissions
        user = make_verified_user(email="student@example.com")
        TaskSubmission.objects.create(task=project, user=user, submission_text="here")
        AssessmentSubmission.objects.create(
            task=assessment,
            user=user,
            score_percent=80,
            passed=True,
            answers={"q": "A"},
            attempt_number=1,
            cashback_amount=0.0,
        )

        resp = client.get(f"{BASE}/creator/episode/{self.episode.id}/full-details")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("episode", data)
        self.assertIn("tasks", data)
        self.assertIn("task_submissions", data)
        self.assertIn("assessment_submissions", data)
        self.assertIn("comments", data)

    def test_admin_with_permission_can_fetch_any_episode(self):
        admin, role = make_admin_with_role(
            [Permission.CONTENT_VIEW], email="perm-admin@skiflux.com"
        )
        client = admin_auth_client(admin)

        # episode belongs to another creator from setUp
        resp = client.get(f"{BASE}/creator/episode/{self.episode.id}/full-details")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_permission_gets_forbidden(self):
        admin = make_admin(email="regular@skiflux.com")
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/creator/episode/{self.episode.id}/full-details")
        self.assertEqual(resp.status_code, 403)
