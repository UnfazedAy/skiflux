import logging
from decimal import Decimal

from django.db import transaction

from skiflux.models.user import User
from skiflux.models.wallet import SkillcoinTransaction, SystemFinancialConfig
from skiflux.repositories.user_repository import UserRepository
from skiflux.services.wallet_service import WalletService

logger = logging.getLogger(__name__)

REGISTRATION_BONUS_DESCRIPTION = "Registration welcome bonus"


class RegistrationBonusService:
    def __init__(self):
        self.wallet_service = WalletService()
        self.user_repo = UserRepository()

    @transaction.atomic
    def grant_if_eligible(self, user: User) -> bool:
        """
        Idempotently credit the configured registration bonus once per user.
        Returns True when a new bonus credit was applied.
        """
        user = self.user_repo.get_for_update_by_pk(user.pk)
        if user.registration_bonus_granted:
            return False

        config = SystemFinancialConfig.get_config()
        amount = Decimal(str(config.registration_bonus_skillcoins))
        if amount <= Decimal("0.00"):
            user.registration_bonus_granted = True
            user.save(update_fields=["registration_bonus_granted", "updated_at"])
            return False

        if amount > Decimal("0.00"):
            self.wallet_service.credit_bonus_balance(
                user,
                amount,
                SkillcoinTransaction.Type.REGISTRATION_BONUS,
                REGISTRATION_BONUS_DESCRIPTION,
                idempotency_key=f"bonus-{user.id}",
            )
        user.registration_bonus_granted = True
        user.save(update_fields=["registration_bonus_granted", "updated_at"])
        logger.info(
            "Registration bonus of %s Skillcoins granted to %s",
            amount,
            user.email,
        )
        return True
