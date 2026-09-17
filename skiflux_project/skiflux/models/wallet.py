import uuid
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MinValueValidator
from django.db import models


class SystemFinancialConfig(models.Model):
    creator_share_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("00.00"),
        help_text="Percentage of purchase amount "
        "that goes to the creator (e.g., 70.00).",
    )
    max_cashback_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("00.00"),
        help_text="Max cashback amount (cap) awarded for task completion "
        "in skillcoins.",
    )
    project_task_cashback_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("50.00"),
        help_text="Fixed Skillcoin cashback awarded when a project task "
        "submission is approved (set by superadmin).",
    )
    assessment_task_cashback_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("25.00"),
        help_text="Fixed Skillcoin cashback awarded when a user passes an "
        "assessment task (set by superadmin).",
    )
    episode_purchase_price_skillcoins = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("25.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Skillcoin price charged when a learner purchases a paid episode.",
    )

    default_currency = models.CharField(
        max_length=3,
        default="NGN",
        help_text="Default currency code (e.g., NGN, USD).",
    )
    registration_bonus_skillcoins = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="One-time Skillcoins credited when a user verifies their account.",
    )
    max_manual_adjustment_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("00.00"),
        help_text="Maximum absolute amount for a single manual wallet adjustment.",
    )
    enabled_topup_gateways = models.JSONField(
        default=list,
        help_text="List of payment gateways available for user "
        "top-ups (e.g., ['flutterwave', 'paystack']).",
    )
    enabled_withdrawal_gateways = models.JSONField(
        default=list,
        help_text="List of payment gateways available for admin-processed withdrawals.",
    )
    min_withdrawal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("00.00"),
        help_text="Minimum withdrawal amount in fiat currency.",
    )
    withdrawal_fee_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Percentage fee deducted from withdrawals.",
    )
    require_withdrawal_approval = models.BooleanField(
        default=True,
        help_text="If True, withdrawals require admin "
        "approval. If False, auto-processed.",
    )
    name_match_mode = models.CharField(
        max_length=10,
        default="fuzzy",
        help_text="Bank account name match mode: strict, fuzzy, or relaxed.",
    )
    max_withdrawal_accounts = models.PositiveSmallIntegerField(
        default=3,
        help_text="Maximum number of withdrawal bank accounts "
        "(for users or creators) that can be registered. Set by superadmin.",
    )
    max_saved_cards = models.PositiveSmallIntegerField(
        default=3,
        help_text="Maximum number of saved (tokenized) cards per user/creator.",
    )
    card_verification_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("50.00"),
        help_text="Small charge used to tokenize a card on gateways that "
        "require a charge (e.g. Paystack). Refunded to the customer's card "
        "after verification, so the user loses nothing.",
    )
    connect_payout_currency = models.CharField(
        max_length=3,
        default="USD",
        help_text="Currency used for Stripe Connect payouts.",
    )
    pass_gateway_fees_to_customer = models.BooleanField(
        default=False,
        help_text="If True, gateway processing fees are added on top of the "
        "customer's top-up amount so SkillFlux always receives the full "
        "intended fiat value.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_configs",
    )

    class Meta:
        db_table = "skiflux_system_financial_config"
        verbose_name = "System Financial Config"
        verbose_name_plural = "System Financial Configs"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete("system_financial_config")

    @classmethod
    def get_config(cls) -> "SystemFinancialConfig":
        config, created = cls.objects.get_or_create(
            id=1,
            defaults={
                "creator_share_percentage": Decimal("70.00"),
                "max_cashback_amount": Decimal("100.00"),
                "project_task_cashback_amount": Decimal("50.00"),
                "assessment_task_cashback_amount": Decimal("25.00"),
                "episode_purchase_price_skillcoins": Decimal("25.00"),
                "default_currency": "NGN",
                "registration_bonus_skillcoins": Decimal("0.00"),
                "max_manual_adjustment_amount": Decimal("10000.00"),
                "enabled_topup_gateways": ["flutterwave"],
                "enabled_withdrawal_gateways": ["flutterwave"],
                "min_withdrawal_amount": Decimal("500.00"),
                "withdrawal_fee_percentage": Decimal("0.00"),
                "require_withdrawal_approval": True,
                "name_match_mode": "fuzzy",
                "max_withdrawal_accounts": 3,
            },
        )
        return config


class GatewayFeeConfig(models.Model):
    gateway_name = models.CharField(max_length=50)
    currency_code = models.CharField(
        max_length=3,
        help_text="ISO currency code (e.g. 'USD', 'NGN') or 'ALL' for international fallback",  # noqa: E501
    )

    fee_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Percentage to charge (e.g., 3.95 for 3.95%)",
    )
    flat_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Flat amount to add in the transaction currency",
    )
    flat_fee_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Minimum transaction amount before flat fee applies",
    )
    cap_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum allowable fee",
    )

    vat_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="VAT charged as a percentage of the base transaction fee (e.g., 7.5)",
    )
    vat_flat = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Flat VAT amount added directly (e.g., 0.30)",
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_gateway_fees",
    )

    class Meta:
        db_table = "skiflux_gateway_fee_config"
        unique_together = ("gateway_name", "currency_code")
        verbose_name = "Gateway Fee Config"
        verbose_name_plural = "Gateway Fee Configs"

    def __str__(self):
        return f"{self.gateway_name} ({self.currency_code})"


class UserWallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
        null=True,
        blank=True,
    )
    admin_user = models.OneToOneField(
        "skiflux.AdminUser",
        on_delete=models.CASCADE,
        related_name="wallet",
        null=True,
        blank=True,
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    is_locked = models.BooleanField(
        default=False,
        help_text="If True, all transaction activities (credits/debits) are blocked.",
    )
    bonus_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Non-withdrawable registration bonus balance.",
    )
    is_platform_wallet = models.BooleanField(
        default=False,
        help_text="True for the singleton platform revenue wallet.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_state", None).adding:
            from django.db.models import Sum

            total = self.transactions.filter(
                status__in=SkillcoinTransaction.BALANCE_STATUSES
            ).aggregate(total=Sum("amount"))["total"]
            self.balance = total or Decimal("0.00")
        super().save(*args, **kwargs)

    class Meta:
        db_table = "skiflux_user_wallet"
        verbose_name = "User Wallet"
        verbose_name_plural = "User Wallets"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(balance__gte=Decimal("0.00"))
                | models.Q(is_platform_wallet=True),
                name="wallet_balance_cannot_be_negative",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(user__isnull=False)
                        & models.Q(admin_user__isnull=True)
                        & models.Q(is_platform_wallet=False)
                    )
                    | (
                        models.Q(user__isnull=True)
                        & models.Q(admin_user__isnull=False)
                        & models.Q(is_platform_wallet=False)
                    )
                    | (
                        models.Q(user__isnull=True)
                        & models.Q(admin_user__isnull=True)
                        & models.Q(is_platform_wallet=True)
                    )
                ),
                name="wallet_must_have_exactly_one_owner",
            ),
        ]

    def __str__(self):
        if self.is_platform_wallet:
            status = "LOCKED" if self.is_locked else "ACTIVE"
            return f"Platform Wallet - {self.balance} Skillcoins ({status})"
        status = "LOCKED" if self.is_locked else "ACTIVE"
        owner = self.user.email if self.user else self.admin_user.email
        return f"{owner} Wallet - {self.balance} Skillcoins ({status})"


class SkillcoinTransaction(models.Model):
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Deposit (Credit)"
        DEBIT_PURCHASE = "debit_purchase", "Purchase Episode (Debit)"
        CREATOR_REVENUE = "creator_revenue", "Creator Revenue Split (Credit)"
        CREATOR_REVENUE_REVERSAL = (
            "creator_revenue_reversal",
            "Creator Revenue Reversal (Debit)",
        )
        CASHBACK_REWARD = "cashback_reward", "Cashback Reward (Credit)"
        REFUND = "refund", "Refund (Credit)"
        ADMIN_ADJUSTMENT = "admin_adjustment", "Manual Admin Adjustment (Adjustment)"
        TOPUP = "topup", "Top-up via Payment Gateway (Credit)"
        WITHDRAWAL = "withdrawal", "Withdrawal to Bank (Debit)"
        WITHDRAWAL_FEE = "withdrawal_fee", "Withdrawal Fee (Debit)"
        PLATFORM_REVENUE = "platform_revenue", "Platform Revenue (Credit)"
        PLATFORM_CASHBACK_DEBIT = (
            "platform_cashback_debit",
            "Platform Cashback Source (Debit)",
        )
        REGISTRATION_BONUS = "registration_bonus", "Registration Welcome Bonus (Credit)"

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        PENDING = "pending", "Pending"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"
        FAILED = "failed", "Failed"

    BALANCE_STATUSES = (Status.POSTED, Status.REFUNDED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        UserWallet, on_delete=models.CASCADE, related_name="transactions"
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Positive for credits, negative for debits",
    )
    transaction_type = models.CharField(max_length=30, choices=Type.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.POSTED,
        help_text="Lifecycle state for audit; posted rows count toward wallet balance.",
    )
    description = models.CharField(max_length=255)
    reference_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="ID of EpisodePurchase, TaskSubmission, etc.",
    )
    idempotency_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="Unique key to prevent duplicate transactions.",
    )

    admin_user = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_wallet_transactions",
        help_text="The administrator who authorized this manual adjustment or refund.",
    )
    parent_transaction = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_transactions",
        help_text="Groups related transactions, like a withdrawal and its fee.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_skillcoin_transaction"
        verbose_name = "Skillcoin Transaction"
        verbose_name_plural = "Skillcoin Transactions"
        ordering = ["-created_at"]
        managed = True
        indexes = [
            models.Index(fields=["wallet", "status"]),
        ]

    def delete(self, *args, **kwargs):
        raise PermissionError(
            "Ledger entries cannot be deleted. Use status changes for reversals."
        )

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            update_fields = kwargs.get("update_fields")
            if update_fields and set(update_fields) <= {"status", "updated_at"}:
                return super().save(*args, **kwargs)
            raise PermissionError(
                "Ledger entries are immutable. Only status can be updated."
            )
        return super().save(*args, **kwargs)

    def __str__(self):
        admin_prefix = f"[Admin: {self.admin_user.email}] " if self.admin_user else ""
        if self.wallet.is_platform_wallet:
            owner = "Platform Wallet"
        else:
            owner = (
                self.wallet.user.email
                if self.wallet.user
                else self.wallet.admin_user.email
            )
        return f"{admin_prefix}{owner} - {self.transaction_type} - {self.amount}"


class SavedCard(models.Model):
    """A tokenized payment card. We never store the full PAN — only the
    gateway token (Paystack ``authorization_code`` / Stripe ``payment_method``
    id, encrypted at rest) plus display metadata (brand, last4, expiry)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_cards",
        null=True,
        blank=True,
    )
    admin_user = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.CASCADE,
        related_name="saved_cards",
        null=True,
        blank=True,
    )
    gateway_name = models.CharField(
        max_length=30, help_text="Gateway that issued the card token."
    )
    token = models.TextField(
        help_text="Encrypted gateway card token "
        "(Paystack authorization_code / Stripe payment_method id)."
    )
    gateway_customer_code = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Gateway customer identifier "
        "(Paystack customer_code / Stripe customer id).",
    )
    card_brand = models.CharField(max_length=30, blank=True, default="")
    last4 = models.CharField(max_length=4)
    exp_month = models.CharField(max_length=2, blank=True, default="")
    exp_year = models.CharField(max_length=4, blank=True, default="")
    bank_name = models.CharField(max_length=100, blank=True, default="")
    card_type = models.CharField(
        max_length=30, blank=True, default="", help_text="e.g. debit, credit"
    )
    currency = models.CharField(max_length=3, blank=True, default="")
    signature = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Gateway card fingerprint used to dedupe the same "
        "physical card (Paystack signature / Stripe fingerprint).",
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_saved_card"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(user__isnull=False) & models.Q(admin_user__isnull=True))
                    | (models.Q(user__isnull=True) & models.Q(admin_user__isnull=False))
                ),
                name="saved_card_must_have_exactly_one_owner",
            ),
        ]

    @property
    def masked_number(self) -> str:
        return f"**** **** **** {self.last4}"

    def __str__(self):
        owner = self.user.email if self.user else self.admin_user.email
        return f"{owner} - {self.card_brand} {self.masked_number}"


class WithdrawalAccount(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    class DestinationType(models.TextChoices):
        BANK = "bank", "Bank Account"
        STRIPE_CONNECT = "stripe_connect", "Stripe Connect (bank/card on file)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="withdrawal_accounts",
        null=True,
        blank=True,
    )
    admin_user = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.CASCADE,
        related_name="withdrawal_accounts",
        null=True,
        blank=True,
    )
    destination_type = models.CharField(
        max_length=20,
        choices=DestinationType.choices,
        default=DestinationType.BANK,
    )
    gateway_name = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Gateway used to register or pay out to this destination "
        "(e.g. paystack, stripe).",
    )
    bank_code = models.CharField(max_length=10, blank=True, default="")
    bank_name = models.CharField(max_length=100, blank=True, default="")
    account_number = models.CharField(max_length=20, blank=True, default="")
    account_name = models.CharField(
        max_length=255, help_text="Name returned by bank verification API"
    )
    stripe_account_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Stripe Connect account id (acct_...) for "
        "stripe_connect destinations.",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(
        default=True,
        help_text="False when the owner removes this destination.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_withdrawal_account"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(user__isnull=False) & models.Q(admin_user__isnull=True))
                    | (models.Q(user__isnull=True) & models.Q(admin_user__isnull=False))
                ),
                name="withdrawal_account_must_have_exactly_one_owner",
            ),
        ]

    @property
    def display_name(self) -> str:
        if self.destination_type == self.DestinationType.STRIPE_CONNECT:
            return "Stripe — bank/card on file"
        masked = (
            f"•••• {self.account_number[-4:]}"
            if len(self.account_number) >= 4
            else self.account_number
        )
        return f"{self.bank_name} {masked}".strip()


class WithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Processing"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        UserWallet, on_delete=models.CASCADE, related_name="withdrawal_requests"
    )
    withdrawal_account = models.ForeignKey(WithdrawalAccount, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    gateway_reference = models.CharField(max_length=255, null=True, blank=True)
    gateway_name = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        help_text="Gateway used to process this withdrawal",
    )
    gateway_response = models.JSONField(null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_withdrawal_request"
        ordering = ["-created_at"]


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        PENDING = "pending", "Pending"
        SUCCESSFUL = "successful", "Successful"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_transactions",
        null=True,
        blank=True,
    )
    admin_user = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.CASCADE,
        related_name="payment_transactions",
        null=True,
        blank=True,
    )
    amount_fiat = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Amount in local currency"
    )
    currency = models.CharField(max_length=3, default="NGN", help_text="Currency code")
    amount_skillcoins = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Skillcoins to be credited"
    )
    gateway = models.CharField(max_length=30, help_text="Payment gateway used")
    gateway_reference = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    gateway_response = models.JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.INITIATED
    )
    tx_ref = models.CharField(
        max_length=255, unique=True, help_text="Our internal unique reference"
    )
    save_card = models.BooleanField(
        default=False,
        help_text="If True, tokenize and save the card used for this "
        "payment once it succeeds.",
    )
    idempotency_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="Client-provided key to prevent duplicate payment initiations.",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_payment_transaction"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(user__isnull=False) & models.Q(admin_user__isnull=True))
                    | (models.Q(user__isnull=True) & models.Q(admin_user__isnull=False))
                ),
                name="payment_tx_must_have_exactly_one_owner",
            ),
        ]


class WithdrawalHold(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"
        CONVERTED = "converted", "Converted to Ledger"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        UserWallet, on_delete=models.CASCADE, related_name="holds"
    )
    withdrawal_request = models.OneToOneField(
        "WithdrawalRequest",
        on_delete=models.CASCADE,
        related_name="hold",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_withdrawal_hold"
        indexes = [
            models.Index(fields=["wallet", "status"], name="idx_hold_wallet_status"),
        ]

    def __str__(self):
        return f"Hold {self.net_amount} for {self.wallet} [{self.status}]"
