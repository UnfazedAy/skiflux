from django.db.models import Avg, Count, Q
from django.utils import timezone

from skiflux.models import AdminUser, Permission
from skiflux.models.support import SupportTicket, TicketAttachment, TicketMessage


class SupportRepository:
    def get_stats(self) -> dict:
        today = timezone.localdate()

        open_tickets = SupportTicket.objects.filter(
            status=SupportTicket.Status.OPEN,
        ).count()

        in_progress = SupportTicket.objects.filter(
            status=SupportTicket.Status.IN_PROGRESS,
        ).count()

        unassigned = SupportTicket.objects.filter(
            assigned_to__isnull=True,
        ).count()

        resolved_today = SupportTicket.objects.filter(
            status=SupportTicket.Status.RESOLVED,
            resolved_at__date=today,
        ).count()

        # SQLite-compatible: get first outbound message per ticket in Python
        outbound_messages = (
            TicketMessage.objects.filter(
                direction=TicketMessage.Direction.OUTBOUND,
            )
            .select_related("ticket")
            .order_by("ticket_id", "created_at")
        )

        seen_tickets = set()
        response_times = []
        for msg in outbound_messages:
            if msg.ticket_id in seen_tickets:
                continue
            seen_tickets.add(msg.ticket_id)
            delta = (msg.created_at - msg.ticket.created_at).total_seconds() / 60
            response_times.append(delta)

        avg_response_minutes = (
            round(sum(response_times) / len(response_times), 1)
            if response_times
            else None
        )

        satisfaction = SupportTicket.objects.filter(
            satisfaction_score__isnull=False,
        ).aggregate(avg=Avg("satisfaction_score"))

        return {
            "open_tickets": open_tickets,
            "in_progress": in_progress,
            "unassigned": unassigned,
            "resolved_today": resolved_today,
            "avg_response_minutes": avg_response_minutes,
            "satisfaction_rate": round(satisfaction["avg"], 1)
            if satisfaction["avg"]
            else None,
        }

    def get_ticket_list(
        self,
        status: str = None,
        category: str = None,
        assigned_to_id: str = None,
        search: str = None,
        unassigned: bool = False,
    ):
        qs = (
            SupportTicket.objects.all()
            .select_related("user", "assigned_to", "resolved_by")
            .annotate(message_count=Count("messages"))
            .order_by("-created_at")
        )

        if status:
            qs = qs.filter(status=status)

        if category:
            qs = qs.filter(category=category)

        if assigned_to_id:
            qs = qs.filter(assigned_to_id=assigned_to_id)

        if unassigned:
            qs = qs.filter(assigned_to__isnull=True)

        if search:
            qs = qs.filter(
                Q(subject__icontains=search)
                | Q(sender_email__icontains=search)
                | Q(sender_name__icontains=search)
                | Q(ticket_number__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__username__icontains=search)
            )

        return qs

    def get_ticket_by_id(self, ticket_id: str) -> SupportTicket | None:
        try:
            return SupportTicket.objects.select_related(
                "user", "assigned_to", "resolved_by"
            ).get(id=ticket_id)
        except SupportTicket.DoesNotExist:
            return None

    def get_ticket_by_user(self, user_id: str):
        return (
            SupportTicket.objects.select_related(
                "user",
                "assigned_to",
                "resolved_by",
            )
            .filter(user_id=user_id)
            .annotate(message_count=Count("messages"))
            .order_by("-created_at")
        )

    def get_agent_stats(self, admin_id: str) -> dict:
        """
        Stats scoped to tickets assigned to a specific agent —
        mirrors get_stats() but filtered to this admin's queue.
        """
        today = timezone.localdate()

        assigned_qs = SupportTicket.objects.filter(assigned_to_id=admin_id)

        open_tickets = assigned_qs.filter(
            status=SupportTicket.Status.OPEN,
        ).count()

        in_progress = assigned_qs.filter(
            status=SupportTicket.Status.IN_PROGRESS,
        ).count()

        resolved_today = assigned_qs.filter(
            status=SupportTicket.Status.RESOLVED,
            resolved_at__date=today,
        ).count()

        total_resolved = assigned_qs.filter(
            status=SupportTicket.Status.RESOLVED,
        ).count()

        outbound_messages = (
            TicketMessage.objects.filter(
                direction=TicketMessage.Direction.OUTBOUND,
                ticket__assigned_to_id=admin_id,
            )
            .select_related("ticket")
            .order_by("ticket_id", "created_at")
        )

        seen_tickets = set()
        response_times = []
        for msg in outbound_messages:
            if msg.ticket_id in seen_tickets:
                continue
            seen_tickets.add(msg.ticket_id)
            delta = (msg.created_at - msg.ticket.created_at).total_seconds() / 60
            response_times.append(delta)

        avg_response_minutes = (
            round(sum(response_times) / len(response_times), 1)
            if response_times
            else None
        )

        satisfaction = assigned_qs.filter(
            satisfaction_score__isnull=False,
        ).aggregate(avg=Avg("satisfaction_score"))

        return {
            "total_assigned": assigned_qs.count(),
            "open_tickets": open_tickets,
            "in_progress": in_progress,
            "resolved_today": resolved_today,
            "total_resolved": total_resolved,
            "avg_response_minutes": avg_response_minutes,
            "satisfaction_rate": round(satisfaction["avg"], 1)
            if satisfaction["avg"]
            else None,
        }

    def get_ticket_by_number(self, ticket_number: str) -> SupportTicket | None:
        try:
            return SupportTicket.objects.select_related(
                "user", "assigned_to", "resolved_by"
            ).get(ticket_number=ticket_number)
        except SupportTicket.DoesNotExist:
            return None

    def create_ticket(
        self,
        sender_email: str,
        sender_name: str,
        subject: str,
        category: str,
        body: str,
        user=None,
    ) -> SupportTicket:
        ticket = SupportTicket.objects.create(
            user=user,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            category=category,
            status=SupportTicket.Status.OPEN,
        )
        TicketMessage.objects.create(
            ticket=ticket,
            direction=TicketMessage.Direction.INBOUND,
            body=body,
            received_at=timezone.now(),
        )
        return ticket

    def assign_ticket(
        self,
        ticket: SupportTicket,
        admin: AdminUser,
    ) -> SupportTicket:
        ticket.assigned_to = admin
        ticket.status = SupportTicket.Status.IN_PROGRESS
        ticket.save(update_fields=["assigned_to", "status", "updated_at"])
        return ticket

    def unassign_ticket(self, ticket: SupportTicket) -> SupportTicket:
        ticket.assigned_to = None
        ticket.status = SupportTicket.Status.OPEN
        ticket.save(update_fields=["assigned_to", "status", "updated_at"])
        return ticket

    def resolve_ticket(
        self,
        ticket: SupportTicket,
        resolved_by: AdminUser,
    ) -> SupportTicket:
        ticket.status = SupportTicket.Status.RESOLVED
        ticket.resolved_by = resolved_by
        ticket.resolved_at = timezone.now()
        ticket.save(
            update_fields=["status", "resolved_by", "resolved_at", "updated_at"]
        )
        return ticket

    def reopen_ticket(self, ticket: SupportTicket) -> SupportTicket:
        ticket.status = SupportTicket.Status.OPEN
        ticket.resolved_by = None
        ticket.resolved_at = None
        ticket.save(
            update_fields=["status", "resolved_by", "resolved_at", "updated_at"]
        )
        return ticket

    def submit_satisfaction_score(
        self,
        ticket: SupportTicket,
        score: int,
    ) -> SupportTicket:
        ticket.satisfaction_score = score
        ticket.save(update_fields=["satisfaction_score", "updated_at"])
        return ticket

    def get_messages(self, ticket: SupportTicket):
        return (
            TicketMessage.objects.filter(ticket=ticket)
            .select_related("sender_admin")
            .prefetch_related("attachments")
            .order_by("created_at")
        )

    def create_message(
        self,
        ticket: SupportTicket,
        body: str,
        direction: str,
        sender_admin: AdminUser | None = None,
        body_html: str = "",
        email_message_id: str = "",
    ) -> TicketMessage:
        return TicketMessage.objects.create(
            ticket=ticket,
            direction=direction,
            sender_admin=sender_admin,
            body=body,
            body_html=body_html,
            email_message_id=email_message_id,
            received_at=timezone.now(),
        )

    def create_attachment(
        self,
        message: TicketMessage,
        file_url: str,
        file_name: str,
        file_size: int,
        content_type: str,
    ) -> TicketAttachment:
        return TicketAttachment.objects.create(
            message=message,
            file_url=file_url,
            file_name=file_name,
            file_size=file_size,
            content_type=content_type,
        )

    def get_assignable_admins(self):
        """
        Returns admin users who have SUPPORT_MANAGE permission
        and are active — shown in the assign dropdown.
        """

        admins = (
            AdminUser.objects.filter(
                is_active=True,
                status=AdminUser.Status.ACTIVE,
            )
            .prefetch_related("roles")
            .order_by("first_name")
        )

        result = []
        for admin in admins:
            if admin.role_type == AdminUser.RoleType.SUPER_ADMIN:
                result.append(admin)
                continue
            for role in admin.roles.all():
                if Permission.SUPPORT_MANAGE in (role.permissions or []):
                    result.append(admin)
                    break

        return result
