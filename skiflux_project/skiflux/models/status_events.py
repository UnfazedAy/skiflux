import uuid

from django.db import models


class TransactionStatusEvent(models.Model):
    """Immutable append-only log of every status transition."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Polymorphic reference — exactly one FK is non-null
    skillcoin_transaction = models.ForeignKey(
        "skiflux.SkillcoinTransaction",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    payment_transaction = models.ForeignKey(
        "skiflux.PaymentTransaction",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    withdrawal_request = models.ForeignKey(
        "skiflux.WithdrawalRequest",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="status_events",
    )

    from_status = models.CharField(max_length=20, null=True, blank=True)
    to_status = models.CharField(max_length=20)
    reason = models.TextField(blank=True)
    actor = models.CharField(
        max_length=100, blank=True, help_text="system|admin_email|webhook"
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skiflux_transaction_status_event"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise PermissionError("Status events are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Status events cannot be deleted.")
