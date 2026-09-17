from decimal import Decimal

import pytest

from skiflux.models import (
    AdminUser,
    Episode,
    EpisodePurchase,
    EpisodeTask,
    Season,
    TaskSubmission,
    User,
)
from skiflux.models.wallet import SkillcoinTransaction, SystemFinancialConfig
from skiflux.services.content_service import ContentService
from skiflux.services.wallet_service import WalletService


@pytest.fixture
def content_service():
    return ContentService()


@pytest.fixture
def wallet_service():
    return WalletService()


@pytest.fixture
def setup_data(db, wallet_service):
    admin = AdminUser.objects.create(email="creator@test.com", password="pwd")
    user = User.objects.create(email="user@test.com", password="pwd")

    config = SystemFinancialConfig.get_config()
    config.creator_share_percentage = Decimal("70.00")
    config.episode_purchase_price_skillcoins = Decimal("100.00")
    config.max_cashback_amount = Decimal("10.00")
    config.save()

    season = Season.objects.create(
        creator=admin, title="S1", price=Decimal("100.00"), skillworld="tech"
    )
    episode = Episode.objects.create(
        season=season,
        creator=admin,
        title="E1",
        status=Episode.Status.PUBLISHED,
        access_type=Episode.AccessType.PAID,
    )

    wallet_service.credit_wallet(
        owner=user,
        amount=Decimal("200.00"),
        tx_type=SkillcoinTransaction.Type.TOPUP,
        description="Initial funds",
    )

    return {"admin": admin, "user": user, "episode": episode, "season": season}


@pytest.mark.django_db
class TestContentWalletIntegration:
    def test_purchase_episode_revenue_split(
        self, setup_data, content_service, wallet_service
    ):
        user = setup_data["user"]
        episode = setup_data["episode"]
        creator = setup_data["admin"]

        # Action
        purchase = content_service.purchase_episode(user, str(episode.id))

        # Verification
        assert purchase.status == EpisodePurchase.Status.ACTIVE

        user_wallet = wallet_service.get_or_create_wallet(user)
        creator_wallet = wallet_service.get_or_create_wallet(creator)
        platform_wallet = wallet_service.get_platform_wallet()

        # User paid 100
        assert user_wallet.balance == Decimal("100.00")
        # Creator gets 70% of 100
        assert creator_wallet.balance == Decimal("70.00")
        # Platform gets remaining 30 (offset by user liabilities)
        assert platform_wallet.balance == Decimal("-140.00")

    def test_approve_submission_cashback(
        self, setup_data, content_service, wallet_service
    ):
        user = setup_data["user"]
        episode = setup_data["episode"]
        creator = setup_data["admin"]

        wallet_service.credit_platform_wallet(
            Decimal("50.00"), SkillcoinTransaction.Type.PLATFORM_REVENUE, "Funds"
        )

        task = EpisodeTask.objects.create(
            episode=episode, kind=EpisodeTask.Kind.PROJECT_BASED
        )
        submission = TaskSubmission.objects.create(
            task=task, user=user, status=TaskSubmission.Status.PENDING
        )

        from skiflux.models.role import Permission, Role

        role = Role.objects.create(
            name="Admin", permissions=[Permission.CONTENT_MANAGE]
        )
        creator.roles.add(role)
        creator.save()

        content_service.approve_submission(
            creator, str(submission.id), cashback_amount=Decimal("5.00")
        )

        submission.refresh_from_db()
        assert submission.status == TaskSubmission.Status.APPROVED

        user_wallet = wallet_service.get_or_create_wallet(user)
        platform_wallet = wallet_service.get_platform_wallet()

        assert user_wallet.balance == Decimal("205.00")
        assert platform_wallet.balance == Decimal("-155.00")
