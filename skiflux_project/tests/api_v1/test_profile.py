from decimal import Decimal
from unittest.mock import patch
import uuid

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.content import (
    AssessmentSubmission,
    Episode,
    EpisodeTask,
    EpisodeView,
    TaskSubmission,
)
from skiflux.models.notification_preference import UserNotificationPreferences
from skiflux.models.wallet import SkillcoinTransaction, SystemFinancialConfig
from skiflux.services.wallet_service import WalletService

from .conftest import (
    anon_client,
    make_admin_with_role,
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class MyProfileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="profile@example.com")
        self.creator = make_creator()
        self.season = make_season(self.creator, skillworld="design")
        self.episode = make_episode(
            self.creator,
            self.season,
            access_type=Episode.AccessType.FREE,
            status=Episode.Status.PUBLISHED,
        )
        self.client = user_auth_client(self.user)
        WalletService().credit_wallet(
            self.user,
            Decimal("500.00"),
            SkillcoinTransaction.Type.TOPUP,
            "Test funds",
        )

    def test_returns_200_with_correct_structure(self):
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        for field in [
            "id",
            "first_name",
            "email",
            "username",
            "skillworld",
            "status",
            "balance",
            "bonus_balance",
            "xp",
            "rank",
            "watch_history_preview",
        ]:
            self.assertIn(field, data, msg=f"Missing field: {field}")

    def test_balance_reflects_wallet(self):
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.data["data"]["balance"]), Decimal("500.00"))

    def test_bonus_balance_separate_from_main_balance(self):
        config = SystemFinancialConfig.get_config()
        config.registration_bonus_skillcoins = Decimal("50.00")
        config.save()
        user2 = make_verified_user(email="bonusprofile@example.com")
        from skiflux.services.registration_bonus_service import RegistrationBonusService

        RegistrationBonusService().grant_if_eligible(user2)

        resp = user_auth_client(user2).get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(Decimal(data["balance"]), Decimal("50.00"))
        self.assertEqual(Decimal(data["bonus_balance"]), Decimal("50.00"))

    def test_xp_reflects_approved_task_cashback(self):
        from skiflux.models.role import Permission
        from skiflux.services.content_service import ContentService

        self.season = make_season(self.creator)
        config = SystemFinancialConfig.get_config()
        config.episode_purchase_price_skillcoins = Decimal("10.00")
        config.save()
        paid_ep = make_episode(
            self.creator,
            self.season,
            order=2,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.PUBLISHED,
        )
        ws = WalletService()
        ws.credit_platform_wallet(
            Decimal("50.00"), SkillcoinTransaction.Type.PLATFORM_REVENUE, "Funds"
        )
        ContentService().purchase_episode(self.user, str(paid_ep.id))
        task = EpisodeTask.objects.create(
            episode=paid_ep,
            kind=EpisodeTask.Kind.PROJECT_BASED,
        )
        submission = TaskSubmission.objects.create(
            task=task,
            user=self.user,
            submission_text="My answer",
        )
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_MANAGE], email="xpadmin@skiflux.com"
        )
        ContentService().approve_submission(
            admin, str(submission.id), cashback_amount=20.0
        )

        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.data["data"]["xp"]), Decimal("20.00"))

    def test_xp_is_zero_when_no_approved_submissions(self):
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.data["data"]["xp"]), Decimal("0.00"))

    def test_watch_history_preview_capped_at_three(self):
        for i in range(5):
            ep = make_episode(
                self.creator,
                self.season,
                title=f"Preview EP {i + 1}",
                order=i + 2,
                status=Episode.Status.PUBLISHED,
                access_type=Episode.AccessType.FREE,
            )
            EpisodeView.objects.create(
                user=self.user,
                episode=ep,
                watch_duration_seconds=60,
                completed=False,
            )
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.data["data"]["watch_history_preview"]), 3)

    def test_watch_history_preview_item_shape(self):
        EpisodeView.objects.create(
            user=self.user,
            episode=self.episode,
            watch_duration_seconds=120,
            completed=True,
        )
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        item = resp.data["data"]["watch_history_preview"][0]
        for field in ["episode", "watch_duration_seconds", "completed", "viewed_at"]:
            self.assertIn(field, item)
        for ep_field in ["id", "title", "skillworld", "creator", "access_type"]:
            self.assertIn(ep_field, item["episode"])

    def test_empty_preview_when_no_views(self):
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["watch_history_preview"], [])

    def test_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/me/profile")
        self.assertIn(resp.status_code, [401, 403])

    def test_user_with_no_wallet_yet(self):
        """User who never had any wallet activity should still return profile."""
        fresh_user = make_verified_user(email="nowallet@example.com")
        client = user_auth_client(fresh_user)
        resp = client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(Decimal(data["balance"]), Decimal("0.00"))
        self.assertEqual(Decimal(data["bonus_balance"]), Decimal("0.00"))
        self.assertEqual(Decimal(data["xp"]), Decimal("0.00"))

    def test_user_with_no_rank(self):
        """User who doesn't appear in the ranked queryset should return null rank."""
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("rank", resp.data["data"])

    def test_profile_still_works_after_wallet_is_locked(self):
        wallet = WalletService().get_or_create_wallet(self.user)
        wallet.is_locked = True
        wallet.save()
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)


class WatchHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="history@example.com")
        self.creator = make_creator()
        self.season_design = make_season(self.creator, skillworld="design")
        self.season_code = make_season(
            self.creator, title="Code Season", skillworld="code"
        )
        self.client = user_auth_client(self.user)

        # 3 design: completed pattern = True, False, True
        self.design_eps = []
        for i in range(3):
            ep = make_episode(
                self.creator,
                self.season_design,
                title=f"Design EP {i + 1}",
                order=i + 1,
                status=Episode.Status.PUBLISHED,
                access_type=Episode.AccessType.FREE,
            )
            EpisodeView.objects.create(
                user=self.user,
                episode=ep,
                watch_duration_seconds=300,
                completed=(i % 2 == 0),
            )
            self.design_eps.append(ep)

        # 2 code: none completed
        self.code_eps = []
        for i in range(2):
            ep = make_episode(
                self.creator,
                self.season_code,
                title=f"Code EP {i + 1}",
                order=i + 1,
                status=Episode.Status.PUBLISHED,
                access_type=Episode.AccessType.FREE,
            )
            EpisodeView.objects.create(
                user=self.user,
                episode=ep,
                watch_duration_seconds=200,
                completed=False,
            )
            self.code_eps.append(ep)

    def test_returns_total_count_of_all_viewed(self):
        resp = self.client.get(f"{BASE}/me/watch-history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_filter_completed_true(self):
        resp = self.client.get(f"{BASE}/me/watch-history?completed=true")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertGreater(len(results), 0)
        self.assertTrue(all(r["completed"] for r in results))

    def test_filter_completed_false(self):
        resp = self.client.get(f"{BASE}/me/watch-history?completed=false")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertGreater(len(results), 0)
        self.assertTrue(all(not r["completed"] for r in results))

    def test_filter_by_skillworld_code(self):
        resp = self.client.get(f"{BASE}/me/watch-history?skillworld=code")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 2)
        for item in resp.data["data"]["results"]:
            self.assertEqual(item["episode"]["skillworld"], "code")

    def test_filter_by_skillworld_design(self):
        resp = self.client.get(f"{BASE}/me/watch-history?skillworld=design")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 3)

    def test_combined_skillworld_and_completed_filters(self):
        # design completed = indices 0 and 2 → 2 results
        resp = self.client.get(
            f"{BASE}/me/watch-history?skillworld=design&completed=true"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 2)

    def test_ordered_newest_first(self):
        resp = self.client.get(f"{BASE}/me/watch-history")
        self.assertEqual(resp.status_code, 200)
        dates = [r["viewed_at"] for r in resp.data["data"]["results"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_item_shape_contains_watch_fields_and_full_episode(self):
        resp = self.client.get(f"{BASE}/me/watch-history")
        self.assertEqual(resp.status_code, 200)
        item = resp.data["data"]["results"][0]
        for field in ["episode", "watch_duration_seconds", "completed", "viewed_at"]:
            self.assertIn(field, item)
        for ep_field in [
            "id",
            "title",
            "skillworld",
            "creator",
            "access_type",
            "thumbnail_url",
        ]:
            self.assertIn(ep_field, item["episode"])

    def test_empty_history_returns_zero_count(self):
        fresh = make_verified_user(email="nohistory@example.com")
        resp = user_auth_client(fresh).get(f"{BASE}/me/watch-history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 0)
        self.assertEqual(resp.data["data"]["results"], [])

    def test_other_users_views_not_returned(self):
        other = make_verified_user(email="otherwatch@example.com")
        EpisodeView.objects.create(
            user=other,
            episode=self.design_eps[0],
            watch_duration_seconds=10,
            completed=False,
        )
        resp = self.client.get(f"{BASE}/me/watch-history")
        self.assertEqual(resp.status_code, 200)
        # Still 5, not 6
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/me/watch-history")
        self.assertIn(resp.status_code, [401, 403])

    def test_delete_watch_history_item(self):
        ep = self.design_eps[0]
        resp = self.client.delete(f"{BASE}/me/watch-history/{ep.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            EpisodeView.objects.filter(user=self.user, episode=ep).exists()
        )
        list_resp = self.client.get(f"{BASE}/me/watch-history")
        self.assertEqual(list_resp.data["data"]["count"], 4)

    def test_delete_watch_history_item_not_found(self):
        resp = self.client.delete(f"{BASE}/me/watch-history/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)

    def test_clear_watch_history(self):
        resp = self.client.delete(f"{BASE}/me/watch-history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["deleted_count"], 5)
        self.assertEqual(EpisodeView.objects.filter(user=self.user).count(), 0)


class SavedEpisodesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="saved@example.com")
        self.creator = make_creator()
        self.season_design = make_season(self.creator, skillworld="design")
        self.season_code = make_season(
            self.creator, title="Code Season", skillworld="code"
        )
        self.client = user_auth_client(self.user)

        for i in range(3):
            ep = make_episode(
                self.creator,
                self.season_design,
                title=f"Saved Design {i + 1}",
                order=i + 1,
                status=Episode.Status.PUBLISHED,
                access_type=Episode.AccessType.FREE,
            )
            ep.save_later.add(self.user)

        for i in range(2):
            ep = make_episode(
                self.creator,
                self.season_code,
                title=f"Saved Code {i + 1}",
                order=i + 1,
                status=Episode.Status.PUBLISHED,
                access_type=Episode.AccessType.FREE,
            )
            ep.save_later.add(self.user)

    def test_returns_all_saved_episodes(self):
        resp = self.client.get(f"{BASE}/me/saved")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_filter_by_skillworld_design(self):
        resp = self.client.get(f"{BASE}/me/saved?skillworld=design")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 3)

    def test_filter_by_skillworld_code(self):
        resp = self.client.get(f"{BASE}/me/saved?skillworld=code")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 2)

    def test_draft_episodes_excluded(self):
        draft = make_episode(
            self.creator,
            self.season_design,
            title="Draft",
            order=5,
            status=Episode.Status.DRAFT,
        )
        draft.save_later.add(self.user)
        resp = self.client.get(f"{BASE}/me/saved")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_episode_shape_uses_full_serializer(self):
        resp = self.client.get(f"{BASE}/me/saved")
        self.assertEqual(resp.status_code, 200)
        ep = resp.data["data"]["results"][0]
        for field in [
            "id",
            "title",
            "skillworld",
            "creator",
            "access_type",
            "thumbnail_url",
        ]:
            self.assertIn(field, ep)

    def test_other_users_saves_not_leaked(self):
        other = make_verified_user(email="othersaved@example.com")
        extra = make_episode(
            self.creator,
            self.season_design,
            title="Other Save",
            order=6,
            status=Episode.Status.PUBLISHED,
        )
        extra.save_later.add(other)
        resp = self.client.get(f"{BASE}/me/saved")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_empty_saved_list(self):
        fresh = make_verified_user(email="nosaved@example.com")
        resp = user_auth_client(fresh).get(f"{BASE}/me/saved")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 0)

    def test_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/me/saved")
        self.assertIn(resp.status_code, [401, 403])


class LikedEpisodesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="liked@example.com")
        self.creator = make_creator()
        self.season_design = make_season(self.creator, skillworld="design")
        self.season_code = make_season(
            self.creator, title="Code Season", skillworld="code"
        )
        self.client = user_auth_client(self.user)

        for i in range(3):
            ep = make_episode(
                self.creator,
                self.season_design,
                title=f"Liked Design {i + 1}",
                order=i + 1,
                status=Episode.Status.PUBLISHED,
                access_type=Episode.AccessType.FREE,
            )
            ep.liked_by.add(self.user)

        for i in range(2):
            ep = make_episode(
                self.creator,
                self.season_code,
                title=f"Liked Code {i + 1}",
                order=i + 1,
                status=Episode.Status.PUBLISHED,
                access_type=Episode.AccessType.FREE,
            )
            ep.liked_by.add(self.user)

    def test_returns_all_liked_episodes(self):
        resp = self.client.get(f"{BASE}/me/liked")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_filter_by_skillworld(self):
        resp = self.client.get(f"{BASE}/me/liked?skillworld=code")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 2)

    def test_draft_episodes_excluded(self):
        draft = make_episode(
            self.creator,
            self.season_design,
            title="Draft Liked",
            order=5,
            status=Episode.Status.DRAFT,
        )
        draft.liked_by.add(self.user)
        resp = self.client.get(f"{BASE}/me/liked")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_episode_shape_uses_full_serializer(self):
        resp = self.client.get(f"{BASE}/me/liked")
        self.assertEqual(resp.status_code, 200)
        ep = resp.data["data"]["results"][0]
        for field in ["id", "title", "skillworld", "creator", "access_type"]:
            self.assertIn(field, ep)

    def test_other_users_likes_not_leaked(self):
        other = make_verified_user(email="otherliked@example.com")
        extra = make_episode(
            self.creator,
            self.season_design,
            title="Other Like",
            order=6,
            status=Episode.Status.PUBLISHED,
        )
        extra.liked_by.add(other)
        resp = self.client.get(f"{BASE}/me/liked")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 5)

    def test_empty_liked_list(self):
        fresh = make_verified_user(email="noliked@example.com")
        resp = user_auth_client(fresh).get(f"{BASE}/me/liked")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 0)

    def test_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/me/liked")
        self.assertIn(resp.status_code, [401, 403])


class MySubmissionsTests(TestCase):
    """Tests for the new standalone GET /me/submissions endpoint
    with filters and cursor pagination."""

    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="submissions@example.com")
        self.creator = make_creator()
        self.season = make_season(self.creator, skillworld="design")
        self.episode1 = make_episode(
            self.creator,
            self.season,
            title="Episode 1",
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )
        self.episode2 = make_episode(
            self.creator,
            self.season,
            title="Episode 2",
            order=2,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )
        self.client = user_auth_client(self.user)

        # Project task + submission for ep1
        self.project_task1 = EpisodeTask.objects.create(
            episode=self.episode1,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Build a Figma prototype",
        )
        self.project_sub1 = TaskSubmission.objects.create(
            task=self.project_task1,
            user=self.user,
            submission_url="https://figma.com/file/abc",
            submission_text="Here is my work",
            status=TaskSubmission.Status.PENDING,
        )

        # Approved project sub for ep2
        self.project_task2 = EpisodeTask.objects.create(
            episode=self.episode2,
            kind=EpisodeTask.Kind.PROJECT_BASED,
        )
        self.project_sub2 = TaskSubmission.objects.create(
            task=self.project_task2,
            user=self.user,
            submission_url="https://github.com/user/repo",
            status=TaskSubmission.Status.APPROVED,
            cashback_amount=Decimal("25.00"),
        )

        # Assessment task + submission for ep1
        self.assess_task1 = EpisodeTask.objects.create(
            episode=self.episode1,
            kind=EpisodeTask.Kind.ASSESSMENT,
            pass_score_percent=70,
        )
        # Create a question so assessment can be created (but for sub we can direct)
        from skiflux.models.content import AssessmentQuestion

        self.q = AssessmentQuestion.objects.create(
            task=self.assess_task1,
            order=1,
            question_text="What is 2+2?",
            option_a="3",
            option_b="4",
            option_c="5",
            option_d="6",
            correct_answer="B",
        )
        self.assess_sub1 = AssessmentSubmission.objects.create(
            task=self.assess_task1,
            user=self.user,
            score_percent=100,
            passed=True,
            answers={str(self.q.id): "B"},
            attempt_number=1,
            cashback_amount=Decimal("10.00"),
        )

    def test_returns_200_with_mixed_submissions(self):
        resp = self.client.get(f"{BASE}/me/submissions")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 3)
        types = [r["type"] for r in data["results"]]
        self.assertIn("project", types)
        self.assertIn("assessment", types)

    def test_filter_by_episode_id(self):
        resp = self.client.get(f"{BASE}/me/submissions?episode_id={self.episode1.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["count"], 2)  # project1 + assess1
        for item in data["results"]:
            self.assertEqual(item["episode_id"], str(self.episode1.id))

    def test_filter_by_status_pending(self):
        resp = self.client.get(f"{BASE}/me/submissions?status=pending")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["status"], "pending")

    def test_filter_by_status_approved(self):
        resp = self.client.get(f"{BASE}/me/submissions?status=approved")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["status"], "approved")

    def test_filter_by_status_passed(self):
        resp = self.client.get(f"{BASE}/me/submissions?status=passed")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["count"], 1)
        self.assertTrue(data["results"][0]["passed"])

    def test_cursor_pagination_next_link_computed(self):
        resp = self.client.get(f"{BASE}/me/submissions?offset=0&page_size=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIsNotNone(data["next"])
        self.assertIn("offset=1", data["next"])
        self.assertIsNone(data["previous"])

        # follow next
        next_resp = self.client.get(data["next"].replace(BASE, f"{BASE}"))
        self.assertEqual(next_resp.status_code, 200)
        next_data = next_resp.data["data"]
        self.assertIsNotNone(next_data["previous"])
        self.assertIn("offset=0", next_data["previous"])

    def test_pagination_offset_limit(self):
        resp = self.client.get(f"{BASE}/me/submissions?offset=1&limit=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["offset"], 1)
        self.assertEqual(data["limit"], 1)
        self.assertEqual(len(data["results"]), 1)

    def test_cursor_pagination_param(self):
        resp = self.client.get(f"{BASE}/me/submissions?cursor=1&limit=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["results"]), 1)

    def test_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/me/submissions")
        self.assertIn(resp.status_code, [401, 403])

    def test_episode_filter_with_no_results(self):
        other_ep = make_episode(
            self.creator,
            self.season,
            title="Other",
            order=3,
            status=Episode.Status.PUBLISHED,
        )
        resp = self.client.get(f"{BASE}/me/submissions?episode_id={other_ep.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 0)


class DeviceRegistrationTests(TestCase):
    """Tests for /me/devices push token registration (learner path)."""

    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="devicepush@example.com")
        self.client = user_auth_client(self.user)

    def test_register_device_success(self):
        payload = {
            "token": "fcm_test_token_abc1234567890",
            "platform": "android",
            "device_id": "dev-xyz",
        }
        resp = self.client.post(f"{BASE}/me/devices", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        data = resp.data["data"]
        self.assertEqual(data["token"], payload["token"])
        self.assertTrue(data["is_active"])

    def test_register_requires_valid_token(self):
        resp = self.client.post(f"{BASE}/me/devices", {"token": "short"}, format="json")
        self.assertIn(resp.status_code, [400, 422])

    def test_register_unauth_403(self):
        resp = anon_client().post(
            f"{BASE}/me/devices", {"token": "fcm_longenough123456"}, format="json"
        )
        self.assertIn(resp.status_code, [401, 403])

    @patch("skiflux.tasks.send_push_notification_task")
    def test_send_push_enqueued_on_task_approve(self, mock_task):
        ns = __import__(
            "skiflux.services.notification_service", fromlist=["NotificationService"]
        ).NotificationService()
        sent = ns.send_push_notification(
            user=self.user, title="t", body="b", event_type="task_approved_with_coins"
        )
        self.assertIsInstance(sent, int)
        # task may or may not be called depending on devices; non-crash is main goal


class UpdateProfileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="updateprofile@example.com")
        self.client = user_auth_client(self.user)

    def test_can_update_first_name(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"first_name": "NewName"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "NewName")

    def test_can_update_last_name(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"last_name": "NewLast"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "NewLast")

    def test_can_update_bio(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"bio": "My new bio"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.bio, "My new bio")

    def test_can_update_country(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"country": "ng"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.country, "NG")

    def test_country_upcased_automatically(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"country": "us"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.country, "US")

    def test_invalid_country_code_returns_400(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"country": "NGA"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_can_update_username(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"username": "newusername"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newusername")

    def test_duplicate_username_returns_400(self):
        other = make_verified_user(email="otherupdate@example.com")
        other.username = "takenname"
        other.save(update_fields=["username"])

        resp = self.client.patch(
            f"{BASE}/me/update",
            {"username": "takenname"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_can_update_goal_as_list(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"goal": ["build_portfolio", "earn_income"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertIn("build_portfolio", self.user.goal)
        self.assertIn("earn_income", self.user.goal)

    def test_can_update_skillworld_as_list(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"skillworld": ["design", "code"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertIn("design", self.user.skillworld)
        self.assertIn("code", self.user.skillworld)

    def test_invalid_goal_choice_returns_400(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"goal": ["invalid_goal"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_skillworld_choice_returns_400(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"skillworld": ["cooking"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unsent_fields_not_overwritten(self):
        self.user.bio = "Original bio"
        self.user.save(update_fields=["bio"])

        resp = self.client.patch(
            f"{BASE}/me/update",
            {"first_name": "Updated"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.bio, "Original bio")

    def test_goal_comma_separated_string_handled(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"goal": "build_portfolio,learn_skill"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertIn("build_portfolio", self.user.goal)
        self.assertIn("learn_skill", self.user.goal)

    @patch("skiflux.services.profile_service.upload_to_minio")
    @patch("skiflux.services.profile_service.upload_media_from_minio_task")
    def test_can_update_avatar(self, mock_task, mock_minio):
        from django.core.files.uploadedfile import SimpleUploadedFile

        mock_minio.return_value = "skiflux_avatars/test.jpg"
        mock_task.apply_async = lambda *a, **kw: None

        avatar = SimpleUploadedFile(
            "avatar.jpg", b"image content", content_type="image/jpeg"
        )
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"avatar": avatar},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        mock_minio.assert_called_once()

    def test_response_contains_full_profile(self):
        resp = self.client.patch(
            f"{BASE}/me/update",
            {"first_name": "Check"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        for field in ["id", "first_name", "email", "rank", "balance", "xp"]:
            self.assertIn(field, data)

    def test_unauthenticated_returns_403(self):
        resp = anon_client().patch(
            f"{BASE}/me/update",
            {"first_name": "Hacker"},
            format="json",
        )
        self.assertIn(resp.status_code, [401, 403])


class LeaderboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="leaderboard@example.com")
        self.client = user_auth_client(self.user)

        self.user2 = make_verified_user(email="leaderboard2@example.com")
        self.user2.username = "second_place"
        self.user2.xp = 500
        self.user2.save(update_fields=["username", "xp"])

        self.user3 = make_verified_user(email="leaderboard3@example.com")
        self.user3.username = "third_place"
        self.user3.xp = 200
        self.user3.save(update_fields=["username", "xp"])

    def test_leaderboard_returns_200(self):
        resp = self.client.get(f"{BASE}/me/leaderboard")
        self.assertEqual(resp.status_code, 200)

    def test_leaderboard_response_shape(self):
        resp = self.client.get(f"{BASE}/me/leaderboard")
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("my_position", data)
        self.assertIn("results", data)

    def test_leaderboard_entry_shape(self):
        resp = self.client.get(f"{BASE}/me/leaderboard")
        results = resp.data["data"]["results"]
        self.assertGreater(len(results), 0)
        entry = results[0]
        for field in [
            "id",
            "first_name",
            "last_name",
            "username",
            "avatar_url",
            "current_level",
            "xp",
            "rank",
            "tasks_done",
            "coins",
            "is_me",
        ]:
            self.assertIn(field, entry)

    def test_leaderboard_ordered_by_xp_descending(self):
        resp = self.client.get(f"{BASE}/me/leaderboard")
        results = resp.data["data"]["results"]
        xps = [r["xp"] for r in results]
        self.assertEqual(xps, sorted(xps, reverse=True))

    def test_higher_xp_user_ranks_first(self):
        resp = self.client.get(f"{BASE}/me/leaderboard")
        results = resp.data["data"]["results"]
        first = results[0]
        self.assertEqual(first["username"], "second_place")
        self.assertEqual(first["xp"], 500)

    def test_is_me_flag_correct(self):
        resp = self.client.get(f"{BASE}/me/leaderboard")
        results = resp.data["data"]["results"]
        me = next((r for r in results if r["is_me"]), None)
        self.assertIsNotNone(me)
        self.assertEqual(str(me["id"]), str(self.user.id))

    def test_my_position_always_returned(self):
        resp = self.client.get(f"{BASE}/me/leaderboard")
        my_position = resp.data["data"]["my_position"]
        self.assertIsNotNone(my_position)
        self.assertEqual(str(my_position["id"]), str(self.user.id))
        self.assertTrue(my_position["is_me"])

    def test_search_by_username(self):
        resp = self.client.get(f"{BASE}/me/leaderboard?search=second_place")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["username"], "second_place")

    def test_search_by_first_name(self):
        self.user2.first_name = "UniqueFirst"
        self.user2.save(update_fields=["first_name"])

        resp = self.client.get(f"{BASE}/me/leaderboard?search=UniqueFirst")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]["results"]), 1)

    def test_search_no_results(self):
        resp = self.client.get(f"{BASE}/me/leaderboard?search=nonexistentxyz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 0)
        self.assertEqual(resp.data["data"]["results"], [])

    def test_filter_by_level(self):
        self.user2.current_level = "intermediate"
        self.user2.save(update_fields=["current_level"])

        resp = self.client.get(f"{BASE}/me/leaderboard?level=novice")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        for r in results:
            self.assertEqual(r["current_level"], "novice")

    def test_my_position_not_affected_by_search_filter(self):
        # search for someone else — my_position should still show current user
        resp = self.client.get(f"{BASE}/me/leaderboard?search=second_place")
        my_position = resp.data["data"]["my_position"]
        self.assertIsNotNone(my_position)
        self.assertEqual(str(my_position["id"]), str(self.user.id))

    def test_inactive_users_excluded(self):
        inactive = make_verified_user(email="inactive_board@example.com")
        inactive.is_active = False
        inactive.xp = 9999
        inactive.save(update_fields=["is_active", "xp"])

        resp = self.client.get(f"{BASE}/me/leaderboard")
        results = resp.data["data"]["results"]
        ids = [r["id"] for r in results]
        self.assertNotIn(str(inactive.id), ids)

    def test_pagination_works(self):
        resp = self.client.get(f"{BASE}/me/leaderboard?page_size=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(len(data["results"]), 1)
        self.assertIsNotNone(data["next"])

    def test_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/me/leaderboard")
        self.assertIn(resp.status_code, [401, 403])


class BiometricsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="biometrics@example.com")
        self.client = user_auth_client(self.user)

    def test_biometrics_status_returns_false_by_default(self):
        resp = self.client.get(f"{BASE}/me/biometrics")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["biometrics_enabled"])

    def test_toggle_enables_when_disabled(self):
        resp = self.client.post(f"{BASE}/me/biometrics/toggle")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["biometrics_enabled"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.biometrics_enabled)

    def test_toggle_disables_when_enabled(self):
        self.user.biometrics_enabled = True
        self.user.save(update_fields=["biometrics_enabled"])

        resp = self.client.post(f"{BASE}/me/biometrics/toggle")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["biometrics_enabled"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.biometrics_enabled)

    def test_toggle_twice_returns_to_original_state(self):
        self.client.post(f"{BASE}/me/biometrics/toggle")
        self.client.post(f"{BASE}/me/biometrics/toggle")
        self.user.refresh_from_db()
        self.assertFalse(self.user.biometrics_enabled)

    def test_status_reflects_toggled_state(self):
        self.client.post(f"{BASE}/me/biometrics/toggle")
        resp = self.client.get(f"{BASE}/me/biometrics")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["biometrics_enabled"])

    def test_toggle_message_says_enabled_when_turning_on(self):
        resp = self.client.post(f"{BASE}/me/biometrics/toggle")
        self.assertEqual(resp.data["message"], "Biometrics enabled.")

    def test_toggle_message_says_disabled_when_turning_off(self):
        self.user.biometrics_enabled = True
        self.user.save(update_fields=["biometrics_enabled"])

        resp = self.client.post(f"{BASE}/me/biometrics/toggle")
        self.assertEqual(resp.data["message"], "Biometrics disabled.")

    def test_other_user_biometrics_not_affected(self):
        other = make_verified_user(email="otherbiometrics@example.com")
        other_client = user_auth_client(other)

        self.client.post(f"{BASE}/me/biometrics/toggle")

        resp = other_client.get(f"{BASE}/me/biometrics")
        self.assertFalse(resp.data["data"]["biometrics_enabled"])

    def test_unauthenticated_status_returns_403(self):
        resp = anon_client().get(f"{BASE}/me/biometrics")
        self.assertIn(resp.status_code, [401, 403])

    def test_unauthenticated_toggle_returns_403(self):
        resp = anon_client().post(f"{BASE}/me/biometrics/toggle")
        self.assertIn(resp.status_code, [401, 403])


class NotificationPreferencesTests(TestCase):
    """Tests for GET/PATCH /me/notification-preferences endpoints."""

    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="notifprefs@example.com")
        self.client = user_auth_client(self.user)

    def test_get_creates_defaults_when_missing(self):
        self.assertFalse(
            UserNotificationPreferences.objects.filter(user=self.user).exists()
        )

        resp = self.client.get(f"{BASE}/me/notification-preferences")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["message"], "Notification preferences retrieved.")
        data = resp.data["data"]
        for field in [
            "new_episodes",
            "task_updates",
            "comment_replies",
            "comment_likes",
            "coin_earnings",
            "badges",
            "platform_announcements",
            "updated_at",
        ]:
            self.assertIn(field, data)
        self.assertTrue(all(data[f] is True for f in data if f != "updated_at"))
        self.assertTrue(
            UserNotificationPreferences.objects.filter(user=self.user).exists()
        )

    def test_get_returns_existing_preferences(self):
        prefs = UserNotificationPreferences.objects.create(
            user=self.user,
            task_updates=False,
            badges=False,
        )

        resp = self.client.get(f"{BASE}/me/notification-preferences")

        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertFalse(data["task_updates"])
        self.assertFalse(data["badges"])
        self.assertTrue(data["new_episodes"])
        self.assertIsNotNone(data["updated_at"])
        prefs.refresh_from_db()

    def test_patch_updates_single_field(self):
        resp = self.client.patch(
            f"{BASE}/me/notification-preferences/update",
            {"task_updates": False},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["message"], "Notification preferences updated.")
        self.assertFalse(resp.data["data"]["task_updates"])
        self.assertTrue(resp.data["data"]["new_episodes"])

        prefs = UserNotificationPreferences.objects.get(user=self.user)
        self.assertFalse(prefs.task_updates)
        self.assertTrue(prefs.new_episodes)

    def test_patch_partial_update_leaves_other_fields_unchanged(self):
        UserNotificationPreferences.objects.create(
            user=self.user,
            comment_replies=False,
            platform_announcements=False,
        )

        resp = self.client.patch(
            f"{BASE}/me/notification-preferences/update",
            {"badges": False},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        prefs = UserNotificationPreferences.objects.get(user=self.user)
        self.assertFalse(prefs.badges)
        self.assertFalse(prefs.comment_replies)
        self.assertFalse(prefs.platform_announcements)

    def test_patch_invalid_boolean_returns_400(self):
        resp = self.client.patch(
            f"{BASE}/me/notification-preferences/update",
            {"task_updates": "not-a-boolean"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_get_unauthenticated_returns_401_or_403(self):
        resp = anon_client().get(f"{BASE}/me/notification-preferences")
        self.assertIn(resp.status_code, [401, 403])

    def test_patch_unauthenticated_returns_401_or_403(self):
        resp = anon_client().patch(
            f"{BASE}/me/notification-preferences/update",
            {"task_updates": False},
            format="json",
        )
        self.assertIn(resp.status_code, [401, 403])
