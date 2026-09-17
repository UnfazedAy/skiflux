import uuid

from django.db import models, transaction
from .admin_user import AdminUser
from .user import User


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Category(models.TextChoices):
        FAILED_TRANSACTION = "failed_transaction", "Failed Transaction"
        VERIFICATION_DELAY = "verification_delay", "Verification Delay"
        BUG_REPORT = "bug_report", "Bug Report"
        ACCOUNT_ACCESS = "account_access", "Account Access"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # who raised it
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
        help_text="Null if ticket came from an unregistered email.",
    )
    # raw email details for non-registered senders
    sender_email = models.EmailField()
    sender_name = models.CharField(max_length=255, blank=True)

    subject = models.CharField(max_length=500)
    category = models.CharField(
        max_length=50,
        choices=Category.choices,
        default=Category.OTHER,
    )

    ticket_number = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        help_text="Human readable ID e.g. TKT-004",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    assigned_to = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    resolved_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_tickets",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    # email threading — so replies attach to the right ticket
    email_message_id = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="The Message-ID header of the original email.",
    )
    email_thread_id = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Used to match reply emails back to this ticket.",
    )

    # satisfaction
    satisfaction_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="1-5 score submitted by user after resolution.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["email_message_id"]),
            models.Index(fields=["sender_email"]),
        ]

    def __str__(self):
        return f"#{self.ticket_number} — {self.subject}"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            with transaction.atomic():
                last = (
                    SupportTicket.objects.select_for_update()
                    .order_by("-created_at", "-ticket_number")
                    .first()
                )
                if not last or not last.ticket_number:
                    next_num = 1
                else:
                    try:
                        next_num = int(last.ticket_number.replace("TKT-", "")) + 1
                    except ValueError:
                        next_num = 1
                self.ticket_number = f"TKT-{next_num:03d}"
        super().save(*args, **kwargs)


class TicketMessage(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"  # from user
        OUTBOUND = "outbound", "Outbound"  # from admin

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    sender_admin = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_messages",
        help_text="Set when direction is outbound.",
    )
    body = models.TextField()
    body_html = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(null=True, blank=True)
    email_message_id = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Message-ID header for threading.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["ticket", "direction"]),
        ]

    def __str__(self):
        return f"{self.direction} message on ticket {self.ticket_id}"


class TicketAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file_url = models.URLField(null=True, blank=True)
    file_public_id = models.CharField(max_length=500, null=True, blank=True)
    file_name = models.CharField(max_length=255)
    is_processing = models.BooleanField(default=False)
    file_size = models.PositiveIntegerField(help_text="Size in bytes.")
    content_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.file_name
