from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from skiflux.models import User
from skiflux.models.gamification import PlatformTask, UserPlatformTask
from skiflux.models.platform_settings import SystemGamificationConfig
from skiflux.models.wallet import SkillcoinTransaction
from skiflux.services.gamification_service import GamificationService
from skiflux.services.platform_task_service import PlatformTaskService
from skiflux.services.wallet_service import WalletService


@pytest.fixture
def gamification_service():
    return GamificationService()


@pytest.fixture
def platform_task_service():
    return PlatformTaskService()


@pytest.fixture
def test_user(db):
    user = User.objects.create(
        email="learner@test.com", password="pwd", first_name="Learner"
    )
    WalletService().get_or_create_wallet(user)
    return user


@pytest.mark.django_db
class TestGamificationService:
    def test_determine_level(self, gamification_service):
        SystemGamificationConfig.get_config()
        assert gamification_service.determine_level(0) == "novice"
        assert gamification_service.determine_level(500) == "novice"
        assert gamification_service.determine_level(1000) == "amateur"
        assert gamification_service.determine_level(4999) == "amateur"
        assert gamification_service.determine_level(5000) == "senior"
        assert gamification_service.determine_level(14999) == "senior"
        assert gamification_service.determine_level(15000) == "expert"
        assert gamification_service.determine_level(49999) == "expert"
        assert gamification_service.determine_level(50000) == "professional"
        assert gamification_service.determine_level(100000) == "professional"

    def test_add_xp_updates_level(self, gamification_service, test_user):
        assert test_user.xp == 0
        assert test_user.current_level == "novice"

        user = gamification_service.add_xp(test_user, 1000)
        assert user.xp == 1000
        assert user.current_level == "amateur"

        user = gamification_service.add_xp(user, 4000)
        assert user.xp == 5000
        assert user.current_level == "senior"

    def test_process_daily_activity_streak_continuation(
        self, gamification_service, test_user
    ):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        gamification_service.process_daily_activity(test_user)
        test_user.refresh_from_db()
        assert test_user.streak_count == 1
        assert test_user.best_streak_count == 1
        assert test_user.last_active_date == today

        test_user.last_active_date = yesterday
        test_user.save()

        gamification_service.process_daily_activity(test_user)
        test_user.refresh_from_db()
        assert test_user.streak_count == 2
        assert test_user.best_streak_count == 2
        assert test_user.last_active_date == today

    def test_process_daily_activity_streak_reset(self, gamification_service, test_user):
        today = timezone.localdate()
        three_days_ago = today - timedelta(days=3)

        test_user.last_active_date = three_days_ago
        test_user.streak_count = 5
        test_user.best_streak_count = 5
        test_user.save()

        gamification_service.process_daily_activity(test_user)
        test_user.refresh_from_db()
        assert test_user.streak_count == 1
        assert test_user.best_streak_count == 5
        assert test_user.last_active_date == today

    def test_7_day_streak_bonus(self, gamification_service, test_user):
        config = SystemGamificationConfig.get_config()
        config.xp_per_7_day_streak = 50
        config.save()

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        test_user.streak_count = 6
        test_user.last_active_date = yesterday
        test_user.best_streak_count = 6
        test_user.xp = 0
        test_user.total_streak_xp_earned = 0
        test_user.save()

        gamification_service.process_daily_activity(test_user)
        test_user.refresh_from_db()
        assert test_user.streak_count == 7
        assert test_user.best_streak_count == 7
        assert test_user.xp == 50
        assert test_user.total_streak_xp_earned == 50

    def test_14_day_streak_bonus(self, gamification_service, test_user):
        config = SystemGamificationConfig.get_config()
        config.xp_per_7_day_streak = 50
        config.save()

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        test_user.streak_count = 13
        test_user.last_active_date = yesterday
        test_user.best_streak_count = 13
        test_user.xp = 50
        test_user.total_streak_xp_earned = 50
        test_user.save()

        gamification_service.process_daily_activity(test_user)
        test_user.refresh_from_db()
        assert test_user.streak_count == 14
        assert test_user.best_streak_count == 14
        assert test_user.xp == 100
        assert test_user.total_streak_xp_earned == 100

    def test_get_streak_summary_no_activity(self, gamification_service, test_user):
        summary = gamification_service.get_streak_summary(test_user)

        assert summary["current_streak_count"] == 1
        assert summary["is_streak_active"] is True
        assert summary["best_streak"] == 1
        assert summary["total_streak_xp_earned"] == 0
        assert len(summary["week"]["days"]) == 7
        today = timezone.localdate().isoformat()
        today_status = next(
            day for day in summary["week"]["days"] if day["date"] == today
        )
        assert today_status["status"] == "completed"
        assert summary["milestone"]["days_remaining"] == 6
        assert summary["milestone"]["reached_today"] is False

    def test_get_streak_summary_active_streak(self, gamification_service, test_user):
        today = timezone.localdate()
        test_user.streak_count = 5
        test_user.last_active_date = today
        test_user.best_streak_count = 5
        test_user.save()

        summary = gamification_service.get_streak_summary(test_user)

        assert summary["current_streak_count"] == 5
        assert summary["is_streak_active"] is True
        assert summary["best_streak"] == 5
        completed = [
            day for day in summary["week"]["days"] if day["status"] == "completed"
        ]
        assert 1 <= len(completed) <= 5
        assert summary["milestone"]["days_remaining"] == 2
        assert summary["milestone"]["next_at_streak"] == 7

    def test_get_streak_summary_broken_streak(self, gamification_service, test_user):
        today = timezone.localdate()
        test_user.streak_count = 5
        test_user.last_active_date = today - timedelta(days=3)
        test_user.best_streak_count = 5
        test_user.save()

        summary = gamification_service.get_streak_summary(test_user)

        assert summary["current_streak_count"] == 1
        assert summary["is_streak_active"] is True
        assert summary["best_streak"] == 5
        today = timezone.localdate().isoformat()
        today_status = next(
            day for day in summary["week"]["days"] if day["date"] == today
        )
        assert today_status["status"] == "completed"

    def test_get_streak_summary_milestone_reached_today(
        self, gamification_service, test_user
    ):
        today = timezone.localdate()
        test_user.streak_count = 7
        test_user.last_active_date = today
        test_user.best_streak_count = 7
        test_user.total_streak_xp_earned = 50
        test_user.save()

        summary = gamification_service.get_streak_summary(test_user)

        assert summary["current_streak_count"] == 7
        assert summary["milestone"]["reached_today"] is True
        assert summary["milestone"]["next_at_streak"] == 14
        assert summary["milestone"]["days_remaining"] == 0


@pytest.mark.django_db
class TestPlatformTaskService:
    def test_get_tasks_with_status(self, platform_task_service, test_user):
        task1 = PlatformTask.objects.create(
            slug="complete-profile",
            title="Complete Profile",
            description="Fill out profile",
            trigger_type=PlatformTask.TriggerType.COMPLETE_PROFILE,
            xp_reward=100,
            skillcoin_reward=Decimal("10.00"),
            is_active=True,
        )
        PlatformTask.objects.create(
            slug="refer-friend",
            title="Refer Friend",
            description="Refer a friend",
            trigger_type=PlatformTask.TriggerType.REFER_FRIEND,
            xp_reward=150,
            skillcoin_reward=Decimal("0.00"),
            is_active=True,
        )
        PlatformTask.objects.create(
            slug="inactive-task",
            title="Inactive Task",
            description="This is inactive",
            trigger_type=PlatformTask.TriggerType.LINK_SOCIAL,
            xp_reward=50,
            is_active=False,
        )

        UserPlatformTask.objects.create(
            user=test_user,
            platform_task=task1,
            status=UserPlatformTask.Status.CLAIMED,
            progress_current=1,
            claimed_at=timezone.now(),
        )

        tasks = platform_task_service.get_tasks_with_status(test_user)
        assert len(tasks) == 2

        t1_status = next(t for t in tasks if t["id"] == str(task1.id))
        assert t1_status["completed"] is True
        assert t1_status["completed_at"] is not None

        t2_status = next(t for t in tasks if t["title"] == "Refer Friend")
        assert t2_status["completed"] is False
        assert t2_status["status"] == "not_started"

    def test_get_tasks_with_status_includes_untouched_admin_tasks(
        self, platform_task_service, test_user
    ):
        PlatformTask.objects.create(
            slug="admin-task-no-user-row",
            title="Untouched Task",
            description="User has never interacted",
            trigger_type="",
            verification_mode=PlatformTask.VerificationMode.MANUAL,
            is_active=True,
        )

        tasks = platform_task_service.get_tasks_with_status(test_user)
        assert len(tasks) == 1
        assert tasks[0]["status"] == "not_started"
        assert tasks[0]["progress_current"] == 0

    def test_manual_submit_and_claim_flow(self, platform_task_service, test_user):
        task = PlatformTask.objects.create(
            slug="manual-task",
            title="Follow Instagram",
            description="Follow us",
            trigger_type="",
            verification_mode=PlatformTask.VerificationMode.MANUAL,
            xp_reward=100,
            skillcoin_reward=Decimal("10.00"),
            is_active=True,
        )

        submitted = platform_task_service.submit_task(test_user, str(task.id))
        assert submitted["claimable"] is True

        claimed = platform_task_service.claim_task(test_user, str(task.id))
        assert claimed["completed"] is True

        test_user.refresh_from_db()
        assert test_user.xp == 100
        assert test_user.streak_count == 1

        wallet = test_user.wallet
        assert wallet.balance == Decimal("10.00")
        assert wallet.bonus_balance == Decimal("10.00")

        tx = SkillcoinTransaction.objects.filter(wallet=wallet).first()
        assert tx is not None
        assert tx.amount == Decimal("10.00")
        assert tx.transaction_type == SkillcoinTransaction.Type.CASHBACK_REWARD
        assert tx.status == SkillcoinTransaction.Status.POSTED

    def test_complete_task_rewards_and_wallet_credit_manual(
        self, platform_task_service, test_user
    ):
        task = PlatformTask.objects.create(
            slug="manual-complete-profile",
            title="Complete Profile",
            description="Fill out profile",
            trigger_type="",
            verification_mode=PlatformTask.VerificationMode.MANUAL,
            xp_reward=100,
            skillcoin_reward=Decimal("10.00"),
            is_active=True,
        )

        result = platform_task_service.complete_task(test_user, str(task.id))

        assert result["completed"] is True
        test_user.refresh_from_db()
        assert test_user.xp == 100
        assert test_user.streak_count == 1

        wallet = test_user.wallet
        assert wallet.balance == Decimal("10.00")
        assert wallet.bonus_balance == Decimal("10.00")

    def test_handle_trigger_marks_automatic_task_claimable(
        self, platform_task_service, test_user
    ):
        task = PlatformTask.objects.create(
            slug="complete-profile-auto",
            title="Complete Profile",
            description="Finish onboarding",
            trigger_type=PlatformTask.TriggerType.COMPLETE_PROFILE,
            verification_mode=PlatformTask.VerificationMode.AUTOMATIC,
            xp_reward=100,
            skillcoin_reward=Decimal("5.00"),
            is_active=True,
        )
        test_user.is_onboarded = True
        test_user.username = "learner123"
        test_user.save()

        platform_task_service.handle_trigger(
            test_user,
            PlatformTask.TriggerType.COMPLETE_PROFILE,
        )

        user_task = UserPlatformTask.objects.get(user=test_user, platform_task=task)
        assert user_task.status == UserPlatformTask.Status.CLAIMABLE

    def test_follow_creator_progress_task(self, platform_task_service, test_user):
        PlatformTask.objects.create(
            slug="follow-3-creators",
            title="Follow 3 Creators",
            description="Follow three creators",
            trigger_type=PlatformTask.TriggerType.FOLLOW_CREATOR,
            progress_target=3,
            xp_reward=50,
            is_active=True,
        )

        for _ in range(3):
            platform_task_service.handle_trigger(
                test_user,
                PlatformTask.TriggerType.FOLLOW_CREATOR,
            )

        user_task = UserPlatformTask.objects.get(user=test_user)
        assert user_task.progress_current == 3
        assert user_task.status == UserPlatformTask.Status.CLAIMABLE

    def test_complete_task_validation_checks(self, platform_task_service, test_user):
        with pytest.raises(
            ValidationError, match="Platform task not found or inactive."
        ):
            platform_task_service.complete_task(
                test_user, "00000000-0000-0000-0000-000000000000"
            )

        inactive_task = PlatformTask.objects.create(
            slug="inactive-task-validation",
            title="Inactive Task",
            description="Inactive description",
            trigger_type="",
            verification_mode=PlatformTask.VerificationMode.MANUAL,
            is_active=False,
        )
        with pytest.raises(
            ValidationError, match="Platform task not found or inactive."
        ):
            platform_task_service.complete_task(test_user, str(inactive_task.id))

        inactive_task.is_active = True
        inactive_task.save()

        platform_task_service.complete_task(test_user, str(inactive_task.id))

        with pytest.raises(ValidationError, match="already completed"):
            platform_task_service.complete_task(test_user, str(inactive_task.id))

    def test_claim_validation(self, platform_task_service, test_user):
        task = PlatformTask.objects.create(
            slug="claim-validation",
            title="Manual",
            description="Manual",
            trigger_type="",
            verification_mode=PlatformTask.VerificationMode.MANUAL,
            is_active=True,
        )

        with pytest.raises(ValidationError, match="not ready to claim"):
            platform_task_service.claim_task(test_user, str(task.id))

        platform_task_service.submit_task(test_user, str(task.id))
        platform_task_service.claim_task(test_user, str(task.id))

        with pytest.raises(ValidationError, match="already completed"):
            platform_task_service.complete_task(test_user, str(task.id))

    def test_automatic_task_cannot_use_complete_without_being_claimable(
        self, platform_task_service, test_user
    ):
        task = PlatformTask.objects.create(
            slug="auto-complete-profile",
            title="Complete Profile",
            description="Automatic task",
            trigger_type=PlatformTask.TriggerType.COMPLETE_PROFILE,
            verification_mode=PlatformTask.VerificationMode.AUTOMATIC,
            is_active=True,
        )

        with pytest.raises(ValidationError, match="must be completed in the app"):
            platform_task_service.complete_task(test_user, str(task.id))

        test_user.is_onboarded = True
        test_user.username = "learner123"
        test_user.save()
        platform_task_service.handle_trigger(
            test_user,
            PlatformTask.TriggerType.COMPLETE_PROFILE,
        )

        result = platform_task_service.claim_task(test_user, str(task.id))
        assert result["completed"] is True
