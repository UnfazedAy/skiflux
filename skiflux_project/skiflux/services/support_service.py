import logging

from django.db import transaction
from rest_framework.exceptions import ValidationError

from skiflux.models import AdminUser
from skiflux.models.support import SupportTicket
from skiflux.repositories.user_repository import UserRepository
from skiflux.repositories.support_repository import SupportRepository
from skiflux.services.notification_service import NotificationService
from skiflux.services.support_email_service import send_support_reply
from skiflux.models.support import TicketMessage

logger = logging.getLogger(__name__)


class SupportService:
    def __init__(self):
        self.repo = SupportRepository()
        self.user_repo = UserRepository()
        self.notification_service = NotificationService()

    def get_stats(self) -> dict:
        return self.repo.get_stats()

    def get_agent_stats(self, admin_id: str) -> dict:
        return self.repo.get_agent_stats(admin_id)

    def _get_ticket_or_raise(self, ticket_id: str) -> SupportTicket:
        ticket = self.repo.get_ticket_by_id(ticket_id)
        if not ticket:
            raise ValidationError("Ticket not found.")
        return ticket

    def get_ticket_list(
        self,
        status: str = None,
        category: str = None,
        assigned_to_id: str = None,
        search: str = None,
        unassigned: bool = False,
    ):
        valid_statuses = SupportTicket.Status.values
        if status and status not in valid_statuses:
            raise ValidationError(
                f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )

        valid_categories = SupportTicket.Category.values
        if category and category not in valid_categories:
            raise ValidationError(
                f"Invalid category. Must be one of: {', '.join(valid_categories)}"
            )

        return self.repo.get_ticket_list(
            status=status,
            category=category,
            assigned_to_id=assigned_to_id,
            search=search,
            unassigned=unassigned,
        )

    def get_ticket_detail(self, ticket_id: str) -> SupportTicket:
        return self._get_ticket_or_raise(ticket_id)

    def assign_ticket(
        self,
        ticket_id: str,
        admin_id: str,
        assigned_by: AdminUser,
    ) -> SupportTicket:
        ticket = self._get_ticket_or_raise(ticket_id)

        if ticket.status == SupportTicket.Status.RESOLVED:
            raise ValidationError("Cannot assign a resolved ticket.")

        if ticket.status == SupportTicket.Status.CLOSED:
            raise ValidationError("Cannot assign a closed ticket.")

        try:
            assignee = AdminUser.objects.get(
                id=admin_id,
                is_active=True,
                status=AdminUser.Status.ACTIVE,
            )
        except AdminUser.DoesNotExist:
            raise ValidationError("Admin user not found or inactive.")

        if ticket.assigned_to_id and str(ticket.assigned_to_id) == str(admin_id):
            raise ValidationError("Ticket is already assigned to this admin.")

        with transaction.atomic():
            ticket = self.repo.assign_ticket(ticket, assignee)

        msg = (
            f"Ticket {ticket.ticket_number} has been assigned to you: {ticket.subject}"
        )
        # in-app notification to assignee
        self.notification_service.create_notification(
            admin_user=assignee,
            type="ticket_assigned",
            title="Ticket Assigned",
            body=msg,
            data={
                "ticket_id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "assigned_by": str(assigned_by.id),
            },
        )

        # push notification to assignee
        self.notification_service.send_push_for_event(
            admin_user=assignee,
            event_type="ticket_assigned",
            title="Ticket Assigned",
            body=f"Ticket {ticket.ticket_number} has been assigned to you.",
            data={
                "ticket_id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
            },
        )

        return ticket

    def unassign_ticket(
        self,
        ticket_id: str,
        admin: AdminUser,
    ) -> SupportTicket:
        ticket = self._get_ticket_or_raise(ticket_id)

        if not ticket.assigned_to_id:
            raise ValidationError("Ticket is not assigned to anyone.")

        if ticket.status in (
            SupportTicket.Status.RESOLVED,
            SupportTicket.Status.CLOSED,
        ):
            raise ValidationError("Cannot unassign a resolved or closed ticket.")

        return self.repo.unassign_ticket(ticket)

    def resolve_ticket(
        self,
        ticket_id: str,
        admin: AdminUser,
    ) -> SupportTicket:
        ticket = self._get_ticket_or_raise(ticket_id)

        if ticket.status == SupportTicket.Status.RESOLVED:
            raise ValidationError("Ticket is already resolved.")

        if ticket.status == SupportTicket.Status.CLOSED:
            raise ValidationError("Ticket is already closed.")

        with transaction.atomic():
            ticket = self.repo.resolve_ticket(ticket, resolved_by=admin)

        # notify registered user only
        if ticket.user:
            self.notification_service.create_notification(
                user=ticket.user,
                type="support_ticket_resolved",
                title="Support Ticket Resolved",
                body=f"Your support ticket ({ticket.ticket_number}) has been resolved.",
                data={"ticket_id": str(ticket.id)},
            )
            self.notification_service.send_push_for_event(
                user=ticket.user,
                event_type="support_ticket_resolved",
                title="Support Ticket Resolved",
                body=f"Your ticket {ticket.ticket_number} has been resolved.",
                data={"ticket_id": str(ticket.id)},
            )

        return ticket

    def reopen_ticket(
        self,
        ticket_id: str,
        admin: AdminUser,
    ) -> SupportTicket:
        ticket = self._get_ticket_or_raise(ticket_id)

        if ticket.status not in (
            SupportTicket.Status.RESOLVED,
            SupportTicket.Status.CLOSED,
        ):
            raise ValidationError("Only resolved or closed tickets can be reopened.")

        return self.repo.reopen_ticket(ticket)

    def submit_satisfaction_score(
        self,
        ticket_id: str,
        score: int,
        user,
    ) -> SupportTicket:
        ticket = self._get_ticket_or_raise(ticket_id)

        if ticket.status != SupportTicket.Status.RESOLVED:
            raise ValidationError(
                "Satisfaction score can only be submitted for resolved tickets."
            )

        if ticket.sender_email.lower() != user.email.lower():
            raise ValidationError("You can only rate your own tickets.")

        if ticket.satisfaction_score is not None:
            raise ValidationError(
                "You have already submitted a satisfaction score for this ticket."
            )

        if not 1 <= score <= 5:
            raise ValidationError("Score must be between 1 and 5.")

        return self.repo.submit_satisfaction_score(ticket, score)

    def get_messages(self, ticket_id: str):
        ticket = self._get_ticket_or_raise(ticket_id)
        return self.repo.get_messages(ticket)

    def reply_to_ticket(
        self,
        ticket_id: str,
        body: str,
        admin: AdminUser,
        attachments: list = None,
    ) -> TicketMessage:
        ticket = self._get_ticket_or_raise(ticket_id)

        if ticket.status == SupportTicket.Status.RESOLVED:
            raise ValidationError("Cannot reply to a resolved ticket.")

        if ticket.status == SupportTicket.Status.CLOSED:
            raise ValidationError("Cannot reply to a closed ticket.")

        try:
            message = send_support_reply(
                ticket=ticket,
                body=body,
                sender_admin=admin,
                attachments=attachments or [],
            )
        except Exception as e:
            raise ValidationError(f"Failed to send reply: {str(e)}")

        return message

    def get_assignable_admins(self):
        return self.repo.get_assignable_admins()

    def get_ticket_by_user(self, user_id: str):
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise ValidationError("User not found.")
        user_tickets = self.repo.get_ticket_by_user(user_id)
        print(user_tickets)
        return user_tickets
