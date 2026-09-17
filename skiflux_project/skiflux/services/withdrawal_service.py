import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from fuzzywuzzy import fuzz
from rest_framework.exceptions import PermissionDenied, ValidationError

from skiflux.gateways.registry import PaymentGatewayFactory
from skiflux.models import AdminUser, CurrencyConfig, User
from skiflux.models.wallet import (
    SkillcoinTransaction,
    SystemFinancialConfig,
    WithdrawalAccount,
    WithdrawalRequest,
)
from skiflux.repositories.wallet_repository import WalletRepository
from skiflux.repositories.withdrawal_repository import WithdrawalRepository
from skiflux.services.notification_service import NotificationService
from skiflux.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


class WithdrawalService:
    def __init__(self):
        self.wallet_service = WalletService()
        self.repo = WithdrawalRepository()
        self.wallet_repo = WalletRepository()

    def _verify_name_match(self, user_name: str, bank_name: str, mode: str) -> bool:
        if not user_name or not bank_name:
            return False

        user_name = user_name.lower().strip()
        bank_name = bank_name.lower().strip()

        if mode == "strict":
            return user_name == bank_name
        elif mode == "fuzzy":
            # token_set_ratio treats shared tokens as a full match, so a
            # profile of "John Doe" still matches a bank account
            # "John Smith Doe" (extra middle name).
            return (
                max(
                    fuzz.token_sort_ratio(user_name, bank_name),
                    fuzz.token_set_ratio(user_name, bank_name),
                )
                >= 80
            )
        elif mode == "relaxed":
            user_parts = user_name.split()
            return any(part in bank_name for part in user_parts if len(part) > 2)
        return False

    def _resolve_bank_name(
        self, gateway, bank_code: str, provided_bank_name: str = None
    ) -> str:
        """Prefer the client-provided name; otherwise look it up from the
        gateway bank list by code. Falls back to the raw bank_code."""
        if provided_bank_name and provided_bank_name.strip():
            return provided_bank_name.strip()
        try:
            for bank in gateway.get_banks() or []:
                code = str(bank.get("code") or bank.get("bank_code") or "")
                if code == str(bank_code):
                    return bank.get("name") or bank.get("bank_name") or str(bank_code)
        except Exception:
            logger.warning(
                "Could not resolve bank name for code %s via gateway",
                bank_code,
                exc_info=True,
            )
        return str(bank_code)

    @transaction.atomic
    def add_withdrawal_account(
        self,
        owner,
        bank_code: str,
        account_number: str,
        gateway_name: str,
        bank_name: str = None,
    ) -> WithdrawalAccount:
        config = SystemFinancialConfig.get_config()
        gateway = PaymentGatewayFactory.get_gateway(gateway_name, purpose="withdrawal")

        result = gateway.resolve_bank_account(account_number, bank_code)

        if isinstance(owner, User):
            owner_name = f"{owner.first_name} {owner.last_name}"
            user = owner
            admin_user = None
        else:
            owner_name = f"{owner.first_name} {owner.last_name}"
            user = None
            admin_user = owner

        is_match = self._verify_name_match(
            owner_name, result.account_name, config.name_match_mode
        )
        status = (
            WithdrawalAccount.Status.VERIFIED
            if is_match
            else WithdrawalAccount.Status.REJECTED
        )

        if not is_match:
            raise ValidationError(
                f"Account name '{result.account_name}' does not match profile name '{owner_name}' under '{config.name_match_mode}' mode."  # noqa: E501
            )

        max_accounts = getattr(config, "max_withdrawal_accounts", 3)
        existing_count = self.repo.get_withdrawal_accounts_count(
            user=user, admin_user=admin_user
        )

        if existing_count >= max_accounts:
            raise ValidationError(
                f"Maximum of {max_accounts} withdrawal accounts allowed per user/creator."  # noqa: E501
            )

        resolved_bank_name = self._resolve_bank_name(gateway, bank_code, bank_name)

        account = self.repo.create_withdrawal_account(
            user=user,
            admin_user=admin_user,
            gateway_name=gateway_name,
            bank_code=bank_code,
            bank_name=resolved_bank_name,
            account_number=account_number,
            account_name=result.account_name,
            status=status,
            is_default=(existing_count == 0),
        )
        return account

    @transaction.atomic
    def remove_withdrawal_account(self, owner, account_id: str) -> None:
        if isinstance(owner, User):
            user, admin_user = owner, None
        else:
            user, admin_user = None, owner

        account = self.repo.get_owned_withdrawal_account(
            account_id, user=user, admin_user=admin_user, active_only=True
        )
        if not account:
            raise ValidationError("Withdrawal account not found.")

        if self.repo.has_open_withdrawal_requests(account):
            raise ValidationError(
                "Cannot remove this account while a withdrawal is pending or processing"
            )

        was_default = account.is_default
        self.repo.deactivate_withdrawal_account(account)

        if was_default:
            replacement = self.repo.get_next_default_withdrawal_account(
                user=user, admin_user=admin_user, exclude_id=account.id
            )
            if replacement:
                self.repo.set_default_withdrawal_account(replacement)

    # --- Method discovery (drives the frontend) ---------------------------

    def get_withdrawal_methods(self) -> dict:
        """Available withdrawal methods for any account — no geography
        assumptions. The frontend switches on ``flow``:
        ``bank_form`` renders the bank picker; ``hosted_redirect`` opens the
        returned onboarding URL."""
        config = SystemFinancialConfig.get_config()
        methods = []
        for name in config.enabled_withdrawal_gateways:
            if name == "stripe":
                methods.append(
                    {
                        "method": "stripe_connect",
                        "gateway": "stripe",
                        "flow": "hosted_redirect",
                        "label": "International bank account or debit card (Stripe)",
                    }
                )
            else:
                methods.append(
                    {
                        "method": f"{name}_bank",
                        "gateway": name,
                        "flow": "bank_form",
                        "label": f"Bank account ({name.title()})",
                    }
                )
        fee = Decimal(str(config.withdrawal_fee_percentage)).quantize(Decimal("0.01"))
        return {
            "withdrawal_fee_percentage": str(fee),
            "methods": methods,
        }

    # --- Stripe Connect onboarding ----------------------------------------

    @transaction.atomic
    def start_connect_onboarding(
        self, owner, return_url: str = None, refresh_url: str = None
    ) -> dict:
        """Create (or resume) Stripe Connect onboarding. The user attaches a
        bank account or debit card on Stripe's hosted page; we store only
        the acct_... id."""
        config = SystemFinancialConfig.get_config()
        if "stripe" not in config.enabled_withdrawal_gateways:
            raise ValidationError("Stripe withdrawals are not currently enabled.")

        gateway = PaymentGatewayFactory.get_gateway("stripe", purpose="withdrawal")

        if isinstance(owner, User):
            user, admin_user = owner, None
        else:
            user, admin_user = None, owner

        existing = WithdrawalAccount.objects.filter(
            user=user,
            admin_user=admin_user,
            destination_type=WithdrawalAccount.DestinationType.STRIPE_CONNECT,
        ).first()

        if (
            existing
            and existing.is_active
            and existing.status == WithdrawalAccount.Status.VERIFIED
        ):
            raise ValidationError(
                "Stripe withdrawals are already set up for this account."
            )

        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.save(update_fields=["is_active", "updated_at"])
            account = existing
        else:
            max_accounts = getattr(config, "max_withdrawal_accounts", 3)
            existing_count = self.repo.get_withdrawal_accounts_count(
                user=user, admin_user=admin_user
            )
            if existing_count >= max_accounts:
                raise ValidationError(
                    f"Maximum of {max_accounts} withdrawal accounts allowed per user/creator."  # noqa: E501
                )
            stripe_account_id = gateway.create_connect_account(owner.email)
            account = self.repo.create_withdrawal_account(
                user=user,
                admin_user=admin_user,
                destination_type=WithdrawalAccount.DestinationType.STRIPE_CONNECT,
                gateway_name="stripe",
                stripe_account_id=stripe_account_id,
                bank_name="stripe",
                account_name=f"{owner.first_name} {owner.last_name}".strip()
                or owner.email,
                status=WithdrawalAccount.Status.PENDING,
                is_default=(existing_count == 0),
            )

        default_url = getattr(settings, "PAYMENT_REDIRECT_URL", "") or getattr(
            settings, "PUBLIC_API_BASE_URL", ""
        )
        onboarding_url = gateway.create_onboarding_link(
            account_id=account.stripe_account_id,
            refresh_url=refresh_url or return_url or default_url,
            return_url=return_url or default_url,
        )
        return {
            "account_id": account.id,
            "stripe_account_id": account.stripe_account_id,
            "onboarding_url": onboarding_url,
            "status": account.status,
        }

    @transaction.atomic
    def refresh_connect_status(
        self, owner, return_url: str = None, refresh_url: str = None
    ) -> dict:
        """Poll Stripe for onboarding progress; verify the account once
        payouts are enabled. Called when the user returns from Stripe."""
        if isinstance(owner, User):
            user, admin_user = owner, None
        else:
            user, admin_user = None, owner

        account = WithdrawalAccount.objects.filter(
            user=user,
            admin_user=admin_user,
            destination_type=WithdrawalAccount.DestinationType.STRIPE_CONNECT,
        ).first()
        if not account:
            raise ValidationError("No Stripe withdrawal setup found for this account.")

        gateway = PaymentGatewayFactory.get_gateway("stripe", purpose="withdrawal")
        status = gateway.get_connect_account_status(account.stripe_account_id)

        if (
            status["payouts_enabled"]
            and account.status != WithdrawalAccount.Status.VERIFIED
        ):
            account.status = WithdrawalAccount.Status.VERIFIED
            account.save(update_fields=["status", "updated_at"])

        result = {
            "account_id": account.id,
            "status": account.status,
            "payouts_enabled": status["payouts_enabled"],
            "currently_due": status["currently_due"],
            "next_action": None,
        }
        if not status["payouts_enabled"]:
            default_url = getattr(settings, "PAYMENT_REDIRECT_URL", "") or getattr(
                settings, "PUBLIC_API_BASE_URL", ""
            )
            result["next_action"] = gateway.create_onboarding_link(
                account_id=account.stripe_account_id,
                refresh_url=refresh_url or return_url or default_url,
                return_url=return_url or default_url,
            )
        return result

    def _resolve_gateway_for_account(
        self, account: WithdrawalAccount, config: SystemFinancialConfig
    ) -> str:
        """Pick the gateway that should process a payout for this destination."""
        if account.gateway_name:
            gateway_name = account.gateway_name
        elif (
            account.destination_type == WithdrawalAccount.DestinationType.STRIPE_CONNECT
        ):
            gateway_name = "stripe"
        else:
            enabled = list(config.enabled_withdrawal_gateways or [])
            bank_gateways = [g for g in enabled if g != "stripe"]
            if not bank_gateways:
                raise ValidationError(
                    "No bank withdrawal gateway is enabled for auto-processing."
                )
            for preferred in ("paystack", "flutterwave"):
                if preferred in bank_gateways:
                    gateway_name = preferred
                    break
            else:
                gateway_name = bank_gateways[0]

        if gateway_name not in (config.enabled_withdrawal_gateways or []):
            raise ValidationError(
                f"Gateway '{gateway_name}' is not enabled for withdrawals."
            )
        return gateway_name

    @transaction.atomic
    def request_withdrawal(
        self, owner, account_id: str, amount: Decimal
    ) -> WithdrawalRequest:
        if amount <= Decimal("0.00"):
            raise ValidationError("Withdrawal amount must be greater than zero.")

        config = SystemFinancialConfig.get_config()
        if amount < config.min_withdrawal_amount:
            raise ValidationError(
                f"Minimum withdrawal amount is {config.min_withdrawal_amount}."
            )

        account = self.repo.get_withdrawal_account_by_id(account_id)
        if not account:
            raise ValidationError("Withdrawal account not found.")

        if isinstance(owner, User) and account.user != owner:
            raise ValidationError("Unauthorized account.")
        if isinstance(owner, AdminUser) and account.admin_user != owner:
            raise ValidationError("Unauthorized account.")

        if account.status != WithdrawalAccount.Status.VERIFIED:
            raise ValidationError("Withdrawal account is not verified.")

        if not account.is_active:
            raise ValidationError("Withdrawal account is not available.")

        wallet = self.wallet_service._get_locked_wallet(owner)
        withdrawable = self.wallet_service.get_withdrawable_balance_from_wallet(wallet)

        if withdrawable < amount:
            raise ValidationError(
                f"Insufficient withdrawable balance. You can withdraw up to {withdrawable}."  # noqa: E501
            )

        fee = (amount * config.withdrawal_fee_percentage / Decimal("100.00")).quantize(
            Decimal("0.01")
        )
        net_amount = amount - fee

        request = self.repo.create_withdrawal_request(
            wallet=wallet,
            withdrawal_account=account,
            amount=amount,
            fee=fee,
            net_amount=net_amount,
            status=WithdrawalRequest.Status.PENDING,
        )

        self.repo.create_status_event(
            withdrawal_request=request,
            from_status=None,
            to_status=WithdrawalRequest.Status.PENDING,
            reason="Withdrawal requested",
            actor=owner.email if owner else "system",
        )

        self.wallet_service.create_withdrawal_hold(
            owner=owner,
            amount=amount,
            fee=fee,
            net_amount=net_amount,
            withdrawal_request=request,
        )

        config.refresh_from_db(fields=["require_withdrawal_approval"])
        if not config.require_withdrawal_approval:
            gateway_name = self._resolve_gateway_for_account(account, config)
            request = self.process_withdrawal(
                admin=None,
                request_id=str(request.id),
                gateway_name=gateway_name,
            )

        return request

    @transaction.atomic
    def process_withdrawal(
        self, admin, request_id: str, gateway_name: str
    ) -> WithdrawalRequest:
        request = self.repo.get_withdrawal_request_for_update(request_id)
        if not request:
            raise ValidationError("Withdrawal request not found.")

        if request.status != WithdrawalRequest.Status.PENDING:
            raise ValidationError("Request is not in PENDING state.")

        config = SystemFinancialConfig.get_config()
        if admin and not admin.has_permission("economy_manage"):
            raise PermissionDenied("Not authorized to process withdrawals.")

        if gateway_name not in config.enabled_withdrawal_gateways:
            raise ValidationError(
                f"Gateway {gateway_name} is not enabled for withdrawals."
            )

        account = request.withdrawal_account
        is_connect = (
            account.destination_type == WithdrawalAccount.DestinationType.STRIPE_CONNECT
        )
        if is_connect and gateway_name != "stripe":
            raise ValidationError(
                "This withdrawal destination is a Stripe Connect account and "
                "can only be processed via the 'stripe' gateway."
            )
        if not is_connect and gateway_name == "stripe":
            raise ValidationError(
                "Stripe can only process Stripe Connect withdrawal "
                "destinations, not bank accounts."
            )

        gateway = PaymentGatewayFactory.get_gateway(gateway_name, purpose="withdrawal")
        old_status = request.status
        request.status = WithdrawalRequest.Status.PROCESSING
        request.gateway_name = gateway_name
        request.save(update_fields=["status", "gateway_name", "updated_at"])
        self.repo.create_status_event(
            withdrawal_request=request,
            from_status=old_status,
            to_status=WithdrawalRequest.Status.PROCESSING,
            reason=f"Processing via {gateway_name}",
            actor=admin.email if admin else "system-auto",
        )

        try:
            if is_connect:
                # Convert net Skillcoins to the payout currency using the
                # configured CurrencyConfig rate (units per Skillcoin).
                payout_currency = config.connect_payout_currency
                try:
                    curr_config = CurrencyConfig.objects.get(
                        currency_code=payout_currency, is_active=True
                    )
                except CurrencyConfig.DoesNotExist:
                    raise ValidationError(
                        f"Payout currency '{payout_currency}' is not configured."
                    )
                fiat_amount = (
                    request.net_amount * curr_config.skillcoin_rate
                ).quantize(Decimal("0.01"))
                result = gateway.initiate_connect_payout(
                    account_id=account.stripe_account_id,
                    amount=fiat_amount,
                    currency=payout_currency,
                    reference=f"skf-wd-{request.id}",
                )
            else:
                result = gateway.initiate_transfer(
                    account_number=account.account_number,
                    bank_code=account.bank_code,
                    amount=request.net_amount,
                    narration="SkillFlux Withdrawal",
                    reference=f"skf-wd-{request.id}",
                )

            request.gateway_reference = result.transfer_reference
            request.gateway_response = result.raw_response
            request.save(
                update_fields=["gateway_reference", "gateway_response", "updated_at"]
            )

            if result.status.lower() in ["success", "successful"]:
                request = self.mark_withdrawal_completed(request.id)

        except Exception as e:
            old_status = request.status
            request.status = WithdrawalRequest.Status.FAILED
            request.failure_reason = str(e)
            request.save(update_fields=["status", "failure_reason", "updated_at"])
            self.repo.create_status_event(
                withdrawal_request=request,
                from_status=old_status,
                to_status=WithdrawalRequest.Status.FAILED,
                reason=f"Gateway transfer failed: {str(e)}",
                actor="system",
            )

            self.wallet_service.mark_transactions_status_by_reference(
                reference_ids=[request.id],
                from_status=SkillcoinTransaction.Status.PENDING,
                to_status=SkillcoinTransaction.Status.FAILED,
            )

            self.wallet_service.mark_withdrawal_debit_as_posted(
                request.wallet,
                request.amount,
            )
            fee_tx_qs = self.wallet_repo.get_transactions_for_update(
                reference_ids=[request.id],
                from_status=SkillcoinTransaction.Status.POSTED,
                transaction_types=[SkillcoinTransaction.Type.PLATFORM_REVENUE],
            )
            fee_tx = fee_tx_qs.first()
            if fee_tx:
                self.wallet_service.debit_platform_wallet(
                    amount=fee_tx.amount,
                    tx_type=SkillcoinTransaction.Type.ADMIN_ADJUSTMENT,
                    description="Withdrawal failed, fee reversed",
                    reference_id=request.id,
                    idempotency_key=f"withdrawal-fee-reversal-{request.id}",
                )

            if hasattr(request, "hold") and request.hold:
                self.wallet_service.release_hold(request.hold)

        return request

    @transaction.atomic
    def mark_withdrawal_completed(self, request_id: str):
        # Capture the current status for the audit event before the atomic
        # transition (best-effort label; the UPDATE below is the source of
        # truth for idempotency).
        current = self.repo.get_withdrawal_request_by_id(request_id)
        prior_status = current.status if current else None

        # Requests are PENDING when completed directly (auto-approval flows)
        # and PROCESSING when completed after a gateway transfer (inline
        # success or transfer webhook). The atomic UPDATE guarantees exactly
        # one caller performs the completion.
        updated = self.repo.update_withdrawal_request_status(
            request_id=request_id,
            from_status=[
                WithdrawalRequest.Status.PENDING,
                WithdrawalRequest.Status.PROCESSING,
            ],
            to_status=WithdrawalRequest.Status.COMPLETED,
            processed_at=timezone.now(),
        )

        if updated == 0:
            return self.repo.get_withdrawal_request_by_id(request_id)
        request = self.repo.get_withdrawal_request_by_id(request_id)

        self.repo.create_status_event(
            withdrawal_request=request,
            from_status=prior_status,
            to_status=WithdrawalRequest.Status.COMPLETED,
            reason="Withdrawal completed successfully",
            actor="system",
        )
        if hasattr(request, "hold") and request.hold:
            self.wallet_service.convert_hold_to_ledger(request.hold)

        # Notify owner of completion (push)
        try:
            acct = request.withdrawal_account
            owner_user = getattr(acct, "user", None)
            owner_admin = getattr(acct, "admin_user", None)
            amount = getattr(request, "amount", None) or "your request"
            NotificationService().send_push_for_event(
                user=owner_user,
                admin_user=owner_admin,
                event_type="withdrawal_processed",
                title="Withdrawal Processed",
                body=f"Your withdrawal of {amount} has been completed.",
                data={"type": "withdrawal_completed", "request_id": str(request.id)},
            )
            # Persisted for owner history (was missing)
            NotificationService().create_notification(
                user=owner_user,
                admin_user=owner_admin,
                type="withdrawal_processed",
                title="Withdrawal Processed",
                body=f"Your withdrawal of {amount} has been completed.",
                data={"request_id": str(request.id)},
            )
        except Exception:
            logger.warning("Push notify withdrawal completed failed (non-fatal)")

        # Realtime wallet update
        try:
            acct = request.withdrawal_account
            owner_user = getattr(acct, "user", None)
            owner_admin = getattr(acct, "admin_user", None)
        except Exception:
            logger.warning("Realtime wallet update after withdrawal failed (non-fatal)")

        return request

    @transaction.atomic
    def reject_withdrawal(
        self, admin, request_id: str, reason: str
    ) -> WithdrawalRequest:
        request = self.repo.get_withdrawal_request_by_id(request_id)

        if request.status != WithdrawalRequest.Status.PENDING:
            raise ValidationError(
                f"Cannot reject request in status '{request.status}'."
            )

        old_status = request.status
        request.status = WithdrawalRequest.Status.REJECTED
        request.failure_reason = reason
        request.save(update_fields=["status", "failure_reason", "updated_at"])

        self.repo.create_status_event(
            withdrawal_request=request,
            from_status=old_status,
            to_status=WithdrawalRequest.Status.REJECTED,
            reason=f"Rejected by Admin {admin.email}: {reason}",
            actor=admin.email,
        )

        if hasattr(request, "hold") and request.hold:
            self.wallet_service.release_hold(request.hold)

        return request
