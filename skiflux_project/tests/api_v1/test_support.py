import uuid
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from skiflux.models.role import Permission
from skiflux.models.support import SupportTicket, TicketMessage
from skiflux.services.support_email_service import _auto_categorise

from .conftest import (
    admin_auth_client,
    make_admin_with_role,
    make_super_admin,
    make_verified_user,
)

BASE = "/api/v1"

patch("skiflux.views.support.poll_support_inbox").start()

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────


def make_ticket(
    sender_email="user@example.com",
    sender_name="Test User",
    subject="Test Issue",
    category=SupportTicket.Category.OTHER,
    status=SupportTicket.Status.OPEN,
    user=None,
    assigned_to=None,
):
    ticket = SupportTicket.objects.create(
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        category=category,
        status=status,
        user=user,
        assigned_to=assigned_to,
    )
    TicketMessage.objects.create(
        ticket=ticket,
        direction=TicketMessage.Direction.INBOUND,
        body="Initial message body.",
        received_at=timezone.now(),
    )
    return ticket


def make_support_admin(email="support@skiflux.com"):
    from skiflux.models.role import Permission

    admin, _ = make_admin_with_role(
        [
            Permission.SUPPORT_VIEW,
            Permission.SUPPORT_MANAGE,
            Permission.SUPPORT_ASSIGN,
        ],
        email=email,
    )
    return admin


# ─────────────────────────────────────────
# Stats
# ─────────────────────────────────────────


class SupportStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

    def test_stats_returns_expected_shape(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("open_tickets", data)
        self.assertIn("in_progress", data)
        self.assertIn("resolved_today", data)
        self.assertIn("avg_response_minutes", data)
        self.assertIn("satisfaction_rate", data)

    def test_open_tickets_count(self):
        make_ticket(sender_email="a@example.com", status=SupportTicket.Status.OPEN)
        make_ticket(sender_email="b@example.com", status=SupportTicket.Status.OPEN)
        make_ticket(sender_email="c@example.com", status=SupportTicket.Status.RESOLVED)
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertEqual(resp.data["data"]["open_tickets"], 2)

    def test_in_progress_count(self):
        make_ticket(
            sender_email="d@example.com",
            status=SupportTicket.Status.IN_PROGRESS,
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertEqual(resp.data["data"]["in_progress"], 1)

    def test_resolved_today_count(self):
        ticket = make_ticket(
            sender_email="e@example.com",
            status=SupportTicket.Status.RESOLVED,
        )
        SupportTicket.objects.filter(id=ticket.id).update(resolved_at=timezone.now())
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertEqual(resp.data["data"]["resolved_today"], 1)

    def test_satisfaction_rate_with_scores(self):
        t1 = make_ticket(sender_email="f@example.com")
        t2 = make_ticket(sender_email="g@example.com")
        SupportTicket.objects.filter(id=t1.id).update(satisfaction_score=5)
        SupportTicket.objects.filter(id=t2.id).update(satisfaction_score=3)
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertEqual(resp.data["data"]["satisfaction_rate"], 4.0)

    def test_satisfaction_rate_null_when_no_scores(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertIsNone(resp.data["data"]["satisfaction_rate"])

    def test_admin_with_support_view_can_get_stats(self):
        admin = make_support_admin(email="statsviewer@skiflux.com")
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_support_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="statsblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/support/stats/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Ticket list
# ─────────────────────────────────────────


class SupportTicketListTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.t1 = make_ticket(
            sender_email="list1@example.com",
            subject="Payment failed",
            category=SupportTicket.Category.FAILED_TRANSACTION,
            status=SupportTicket.Status.OPEN,
        )
        self.t2 = make_ticket(
            sender_email="list2@example.com",
            subject="Cannot login",
            category=SupportTicket.Category.ACCOUNT_ACCESS,
            status=SupportTicket.Status.IN_PROGRESS,
        )
        self.t3 = make_ticket(
            sender_email="list3@example.com",
            subject="Bug in app",
            category=SupportTicket.Category.BUG_REPORT,
            status=SupportTicket.Status.RESOLVED,
        )

    def test_super_admin_can_list_tickets(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 3)

    def test_filter_by_status(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/?status=open")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_superadmin_can_view_user_tickets(self):
        user = make_verified_user(email="testuser@example.com")

        # Create tickets associated with that user
        make_ticket(
            sender_email=user.email,
            subject="Payment failed",
            category=SupportTicket.Category.FAILED_TRANSACTION,
            status=SupportTicket.Status.OPEN,
            user=user,
        )
        make_ticket(
            sender_email=user.email,
            subject="Cannot login",
            category=SupportTicket.Category.ACCOUNT_ACCESS,
            status=SupportTicket.Status.IN_PROGRESS,
            user=user,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/user/{user.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 2)

    def test_filter_by_category(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/support/tickets/"
            f"?category={SupportTicket.Category.BUG_REPORT}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_filter_unassigned(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/?unassigned=true")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 3)

    def test_filter_assigned_to(self):
        admin = make_support_admin(email="assignedto@skiflux.com")
        SupportTicket.objects.filter(id=self.t1.id).update(assigned_to=admin)
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/?assigned_to_id={admin.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_search_by_subject(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/?search=Payment")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_search_by_email(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/?search=list2@example.com")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_search_by_ticket_number(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/support/tickets/?search={self.t1.ticket_number}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_invalid_status_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/?status=invalid")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_category_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/?category=invalid")
        self.assertEqual(resp.status_code, 400)

    def test_ticket_list_includes_message_count(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/")
        results = resp.data["data"]["results"]
        for r in results:
            self.assertIn("message_count", r)

    def test_admin_without_support_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="listblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/support/tickets/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Ticket detail
# ─────────────────────────────────────────


class SupportTicketDetailTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.ticket = make_ticket(
            sender_email="detail@example.com",
            subject="Detail Test",
        )

    def test_super_admin_can_get_ticket_detail(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{self.ticket.id}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["ticket_number"], self.ticket.ticket_number)
        self.assertEqual(data["subject"], "Detail Test")

    def test_detail_includes_messages(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{self.ticket.id}/")
        self.assertIn("messages", resp.data["data"])
        self.assertEqual(len(resp.data["data"]["messages"]), 1)

    def test_detail_includes_sender_display(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{self.ticket.id}/")
        sender = resp.data["data"]["sender_display"]
        self.assertIn("name", sender)
        self.assertIn("email", sender)
        self.assertIn("is_registered", sender)
        self.assertFalse(sender["is_registered"])

    def test_detail_sender_display_registered_user(self):
        user = make_verified_user(email="reguser@example.com")
        ticket = make_ticket(
            sender_email="reguser@example.com",
            user=user,
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{ticket.id}/")
        sender = resp.data["data"]["sender_display"]
        self.assertTrue(sender["is_registered"])

    def test_nonexistent_ticket_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{uuid.uuid4()}/")
        self.assertEqual(resp.status_code, 404)

    def test_admin_without_support_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="detailblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{self.ticket.id}/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Ticket messages
# ─────────────────────────────────────────


class TicketMessagesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.ticket = make_ticket(sender_email="msgs@example.com")
        TicketMessage.objects.create(
            ticket=self.ticket,
            direction=TicketMessage.Direction.OUTBOUND,
            sender_admin=self.super_admin,
            body="Thanks for reaching out.",
            received_at=timezone.now(),
        )

    def test_can_get_ticket_messages(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{self.ticket.id}/messages/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 2)

    def test_messages_ordered_by_created_at(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{self.ticket.id}/messages/")
        messages = resp.data["data"]["results"]
        self.assertEqual(messages[0]["direction"], "inbound")
        self.assertEqual(messages[1]["direction"], "outbound")

    def test_nonexistent_ticket_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/tickets/{uuid.uuid4()}/messages/")
        self.assertEqual(resp.status_code, 404)


# ─────────────────────────────────────────
# Assign ticket
# ─────────────────────────────────────────


class AssignTicketTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.ticket = make_ticket(sender_email="assign@example.com")
        self.assignee = make_support_admin(email="assignee@skiflux.com")

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_super_admin_can_assign_ticket(self, mock_push, mock_notif):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/assign/",
            {"admin_id": str(self.assignee.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(str(self.ticket.assigned_to_id), str(self.assignee.id))

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_assign_updates_status_to_in_progress(self, mock_push, mock_notif):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/assign/",
            {"admin_id": str(self.assignee.id)},
            format="json",
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, SupportTicket.Status.IN_PROGRESS)

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_assign_sends_notification_to_assignee(self, mock_push, mock_notif):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/assign/",
            {"admin_id": str(self.assignee.id)},
            format="json",
        )
        mock_notif.assert_called_once()
        mock_push.assert_called_once()

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_assign_same_admin_twice_returns_400(self, mock_push, mock_notif):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            assigned_to=self.assignee
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/assign/",
            {"admin_id": str(self.assignee.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_assign_resolved_ticket(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            status=SupportTicket.Status.RESOLVED
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/assign/",
            {"admin_id": str(self.assignee.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_assign_nonexistent_admin_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/assign/",
            {"admin_id": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_without_support_assign_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.SUPPORT_VIEW],
            email="assignblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/assign/",
            {"admin_id": str(self.assignee.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Unassign ticket
# ─────────────────────────────────────────


class UnassignTicketTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.assignee = make_support_admin(email="unassignee@skiflux.com")
        self.ticket = make_ticket(
            sender_email="unassign@example.com",
            status=SupportTicket.Status.IN_PROGRESS,
            assigned_to=self.assignee,
        )

    def test_can_unassign_ticket(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/unassign/")
        self.assertEqual(resp.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to_id)

    def test_unassign_reverts_status_to_open(self):
        client = admin_auth_client(self.super_admin)
        client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/unassign/")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, SupportTicket.Status.OPEN)

    def test_unassign_unassigned_ticket_returns_400(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(assigned_to=None)
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/unassign/")
        self.assertEqual(resp.status_code, 400)

    def test_cannot_unassign_resolved_ticket(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            status=SupportTicket.Status.RESOLVED
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/unassign/")
        self.assertEqual(resp.status_code, 400)


# ─────────────────────────────────────────
# Resolve ticket
# ─────────────────────────────────────────


class ResolveTicketTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.ticket = make_ticket(sender_email="resolve@example.com")

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_can_resolve_ticket(self, mock_push, mock_notif):
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/resolve/")
        self.assertEqual(resp.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, SupportTicket.Status.RESOLVED)

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_resolve_sets_resolved_by_and_at(self, mock_push, mock_notif):
        client = admin_auth_client(self.super_admin)
        client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/resolve/")
        self.ticket.refresh_from_db()
        self.assertEqual(str(self.ticket.resolved_by_id), str(self.super_admin.id))
        self.assertIsNotNone(self.ticket.resolved_at)

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_resolve_notifies_registered_user(self, mock_push, mock_notif):
        user = make_verified_user(email="resolveuser@example.com")
        ticket = make_ticket(
            sender_email="resolveuser@example.com",
            user=user,
        )
        client = admin_auth_client(self.super_admin)
        client.post(f"{BASE}/admin/support/tickets/{ticket.id}/resolve/")
        mock_notif.assert_called_once()
        mock_push.assert_called_once()

    @patch("skiflux.services.support_service.NotificationService.create_notification")
    @patch("skiflux.services.support_service.NotificationService.send_push_for_event")
    def test_resolve_does_not_notify_unregistered_user(self, mock_push, mock_notif):
        client = admin_auth_client(self.super_admin)
        client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/resolve/")
        mock_notif.assert_not_called()
        mock_push.assert_not_called()

    def test_resolve_already_resolved_returns_400(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            status=SupportTicket.Status.RESOLVED
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/resolve/")
        self.assertEqual(resp.status_code, 400)

    def test_admin_without_support_manage_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.SUPPORT_VIEW],
            email="resolveblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/resolve/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Reopen ticket
# ─────────────────────────────────────────


class ReopenTicketTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.ticket = make_ticket(
            sender_email="reopen@example.com",
            status=SupportTicket.Status.RESOLVED,
        )

    def test_can_reopen_resolved_ticket(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/reopen/")
        self.assertEqual(resp.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, SupportTicket.Status.OPEN)

    def test_reopen_clears_resolved_by_and_at(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            resolved_by=self.super_admin,
            resolved_at=timezone.now(),
        )
        client = admin_auth_client(self.super_admin)
        client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/reopen/")
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.resolved_by_id)
        self.assertIsNone(self.ticket.resolved_at)

    def test_cannot_reopen_open_ticket(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            status=SupportTicket.Status.OPEN
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/reopen/")
        self.assertEqual(resp.status_code, 400)

    def test_can_reopen_closed_ticket(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            status=SupportTicket.Status.CLOSED
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/reopen/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_support_manage_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.SUPPORT_VIEW],
            email="reopenblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(f"{BASE}/admin/support/tickets/{self.ticket.id}/reopen/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Reply to ticket
# ─────────────────────────────────────────


class ReplyToTicketTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.ticket = make_ticket(sender_email="reply@example.com")

    @patch("skiflux.services.support_email_service.smtplib.SMTP_SSL")
    def test_can_reply_to_ticket(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/reply/",
            {"body": "Thank you for reaching out."},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    @patch("skiflux.services.support_email_service.smtplib.SMTP_SSL")
    def test_reply_creates_outbound_message(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/reply/",
            {"body": "We are looking into this."},
            format="json",
        )
        self.assertTrue(
            TicketMessage.objects.filter(
                ticket=self.ticket,
                direction=TicketMessage.Direction.OUTBOUND,
            ).exists()
        )

    @patch("skiflux.services.support_email_service.smtplib.SMTP_SSL")
    def test_reply_updates_status_to_in_progress(self, mock_smtp):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/reply/",
            {"body": "We are looking into this."},
            format="json",
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, SupportTicket.Status.IN_PROGRESS)

    def test_reply_to_resolved_ticket_returns_400(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            status=SupportTicket.Status.RESOLVED
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/reply/",
            {"body": "Hello"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_body_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/reply/",
            {"body": ""},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unsupported_attachment_type_returns_400(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        exe_file = SimpleUploadedFile(
            "virus.exe",
            b"malicious",
            content_type="application/x-msdownload",
        )
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/reply/",
            {"body": "See attached.", "attachments": [exe_file]},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_without_support_manage_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.SUPPORT_VIEW],
            email="replyblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(
            f"{BASE}/admin/support/tickets/{self.ticket.id}/reply/",
            {"body": "Hello"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Assignable admins
# ─────────────────────────────────────────


class AssignableAdminsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.support_admin = make_support_admin(email="assignableadmin@skiflux.com")

    def test_can_get_assignable_admins(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/admins/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data["data"], list)

    def test_assignable_admins_includes_support_manage(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/admins/")
        ids = [str(a["id"]) for a in resp.data["data"]]
        self.assertIn(str(self.support_admin.id), ids)

    def test_admin_without_support_assign_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.SUPPORT_VIEW],
            email="assignableblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/support/admins/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Satisfaction score
# ─────────────────────────────────────────


class SatisfactionScoreTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="ratinguser@example.com")
        self.ticket = make_ticket(
            sender_email="ratinguser@example.com",
            status=SupportTicket.Status.RESOLVED,
            user=self.user,
        )

    def _user_client(self):
        from skiflux.utils.auth import create_access_token

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(str(self.user.id))}"
        )
        return client

    def test_user_can_submit_satisfaction_score(self):
        client = self._user_client()
        resp = client.post(
            f"{BASE}/support/tickets/{self.ticket.id}/rate/",
            {"score": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.satisfaction_score, 5)

    def test_cannot_submit_score_twice(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(satisfaction_score=4)
        client = self._user_client()
        resp = client.post(
            f"{BASE}/support/tickets/{self.ticket.id}/rate/",
            {"score": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_rate_open_ticket(self):
        SupportTicket.objects.filter(id=self.ticket.id).update(
            status=SupportTicket.Status.OPEN
        )
        client = self._user_client()
        resp = client.post(
            f"{BASE}/support/tickets/{self.ticket.id}/rate/",
            {"score": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_score_below_1_returns_400(self):
        client = self._user_client()
        resp = client.post(
            f"{BASE}/support/tickets/{self.ticket.id}/rate/",
            {"score": 0},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_score_above_5_returns_400(self):
        client = self._user_client()
        resp = client.post(
            f"{BASE}/support/tickets/{self.ticket.id}/rate/",
            {"score": 6},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_wrong_user_cannot_rate_ticket(self):
        other_user = make_verified_user(email="otheruser@example.com")
        from skiflux.utils.auth import create_access_token

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(str(other_user.id))}"
        )
        resp = client.post(
            f"{BASE}/support/tickets/{self.ticket.id}/rate/",
            {"score": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


# ─────────────────────────────────────────
# IMAP service
# ─────────────────────────────────────────


class IMAPServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def _make_raw_email(
        self,
        subject="Test Subject",
        from_addr="customer@example.com",
        from_name="Customer",
        body="Hello support team.",
        message_id="<test-message-id-001@example.com>",
        in_reply_to=None,
    ):
        from email.mime.text import MIMEText

        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_addr}>"
        msg["Message-ID"] = message_id
        msg["Date"] = "Mon, 01 Jan 2026 10:00:00 +0000"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        return msg.as_bytes()

    def test_new_email_creates_ticket(self):
        from skiflux.services.support_email_service import _process_raw_email
        import email as email_lib

        raw = self._make_raw_email()
        msg = email_lib.message_from_bytes(raw)
        ticket, created = _process_raw_email(msg)
        self.assertIsNotNone(ticket)
        self.assertTrue(created)
        self.assertEqual(ticket.sender_email, "customer@example.com")
        self.assertEqual(ticket.subject, "Test Subject")

    def test_new_email_creates_inbound_message(self):
        from skiflux.services.support_email_service import _process_raw_email
        import email as email_lib

        raw = self._make_raw_email()
        msg = email_lib.message_from_bytes(raw)
        ticket, _ = _process_raw_email(msg)
        self.assertEqual(
            ticket.messages.filter(direction=TicketMessage.Direction.INBOUND).count(),
            1,
        )

    def test_duplicate_message_id_is_skipped(self):
        from skiflux.services.support_email_service import _process_raw_email
        import email as email_lib

        raw = self._make_raw_email(message_id="<duplicate@example.com>")
        msg = email_lib.message_from_bytes(raw)
        ticket1, created1 = _process_raw_email(msg)
        ticket2, created2 = _process_raw_email(msg)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertIsNone(ticket2)

    def test_reply_email_attaches_to_existing_ticket(self):
        from skiflux.services.support_email_service import _process_raw_email
        import email as email_lib

        # first email creates ticket
        raw1 = self._make_raw_email(message_id="<original@example.com>")
        msg1 = email_lib.message_from_bytes(raw1)
        ticket, _ = _process_raw_email(msg1)

        # reply email references original
        raw2 = self._make_raw_email(
            message_id="<reply@example.com>",
            in_reply_to="<original@example.com>",
            subject="Re: Test Subject",
            body="Thanks for the reply.",
        )
        msg2 = email_lib.message_from_bytes(raw2)
        reply_ticket, created = _process_raw_email(msg2)

        self.assertFalse(created)
        self.assertEqual(str(reply_ticket.id), str(ticket.id))
        self.assertEqual(ticket.messages.count(), 2)

    def test_reply_reopens_resolved_ticket(self):
        from skiflux.services.support_email_service import _process_raw_email
        import email as email_lib

        raw1 = self._make_raw_email(message_id="<reopen@example.com>")
        msg1 = email_lib.message_from_bytes(raw1)
        ticket, _ = _process_raw_email(msg1)
        SupportTicket.objects.filter(id=ticket.id).update(
            status=SupportTicket.Status.RESOLVED
        )

        raw2 = self._make_raw_email(
            message_id="<reopen-reply@example.com>",
            in_reply_to="<reopen@example.com>",
        )
        msg2 = email_lib.message_from_bytes(raw2)
        _process_raw_email(msg2)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, SupportTicket.Status.OPEN)

    def test_email_links_to_registered_user(self):
        from skiflux.services.support_email_service import _process_raw_email
        import email as email_lib

        user = make_verified_user(email="linkeduser@example.com")
        raw = self._make_raw_email(
            from_addr="linkeduser@example.com",
            message_id="<linked@example.com>",
        )
        msg = email_lib.message_from_bytes(raw)
        ticket, _ = _process_raw_email(msg)
        self.assertIsNotNone(ticket.user)
        self.assertEqual(str(ticket.user_id), str(user.id))

    def test_email_from_own_support_address_is_skipped(self):
        from skiflux.services.support_email_service import _process_raw_email
        from django.conf import settings
        import email as email_lib

        raw = self._make_raw_email(
            from_addr=settings.SUPPORT_EMAIL_USERNAME,
            message_id="<self@example.com>",
        )
        msg = email_lib.message_from_bytes(raw)
        ticket, created = _process_raw_email(msg)
        self.assertIsNone(ticket)
        self.assertFalse(created)

    def test_auto_categorise_failed_transaction(self):

        result = _auto_categorise("Payment failed", "My deposit was not credited")
        self.assertEqual(result, SupportTicket.Category.FAILED_TRANSACTION)

    def test_auto_categorise_bug_report(self):
        result = _auto_categorise("App crash", "The app is broken on my phone")
        self.assertEqual(result, SupportTicket.Category.BUG_REPORT)

    def test_auto_categorise_defaults_to_other(self):

        result = _auto_categorise("Random question", "Just wanted to ask something")
        self.assertEqual(result, SupportTicket.Category.OTHER)

    def test_ticket_number_is_generated(self):
        from skiflux.services.support_email_service import _process_raw_email
        import email as email_lib

        raw = self._make_raw_email(message_id="<ticketnum@example.com>")
        msg = email_lib.message_from_bytes(raw)
        ticket, _ = _process_raw_email(msg)
        self.assertTrue(ticket.ticket_number.startswith("TKT-"))

    @patch("skiflux.tasks.support.poll_support_inbox")
    def test_manual_trigger_fires_celery_task(self, mock_fetch):
        mock_fetch.return_value = {
            "fetched": 2,
            "new_tickets": 1,
            "replies": 1,
        }
        client = admin_auth_client(make_super_admin())
        with patch("skiflux.views.support.poll_support_inbox") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(f"{BASE}/admin/support/fetch/")
        self.assertEqual(resp.status_code, 200)


# ─────────────────────────────────────────
# Agent stats (logged-in agent's own queue)
# ─────────────────────────────────────────


class AgentStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.agent = make_support_admin(email="agentstats@skiflux.com")
        self.other_agent = make_support_admin(email="otheragentstats@skiflux.com")

    def test_stats_returns_expected_shape(self):
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("total_assigned", data)
        self.assertIn("open_tickets", data)
        self.assertIn("in_progress", data)
        self.assertIn("resolved_today", data)
        self.assertIn("total_resolved", data)
        self.assertIn("avg_response_minutes", data)
        self.assertIn("satisfaction_rate", data)

    def test_open_tickets_count_for_logged_in_agent(self):
        make_ticket(
            sender_email="agentopen1@example.com",
            status=SupportTicket.Status.OPEN,
            assigned_to=self.agent,
        )
        make_ticket(
            sender_email="agentopen2@example.com",
            status=SupportTicket.Status.OPEN,
            assigned_to=self.agent,
        )
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.data["data"]["open_tickets"], 2)

    def test_in_progress_count_for_logged_in_agent(self):
        make_ticket(
            sender_email="agentinprogress@example.com",
            status=SupportTicket.Status.IN_PROGRESS,
            assigned_to=self.agent,
        )
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.data["data"]["in_progress"], 1)

    def test_resolved_today_count_for_logged_in_agent(self):
        ticket = make_ticket(
            sender_email="agentresolved@example.com",
            status=SupportTicket.Status.RESOLVED,
            assigned_to=self.agent,
        )
        SupportTicket.objects.filter(id=ticket.id).update(resolved_at=timezone.now())
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.data["data"]["resolved_today"], 1)

    def test_total_assigned_count(self):
        make_ticket(
            sender_email="agenttotal1@example.com",
            status=SupportTicket.Status.OPEN,
            assigned_to=self.agent,
        )
        make_ticket(
            sender_email="agenttotal2@example.com",
            status=SupportTicket.Status.RESOLVED,
            assigned_to=self.agent,
        )
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.data["data"]["total_assigned"], 2)

    def test_total_resolved_count(self):
        make_ticket(
            sender_email="agentresolvedtotal1@example.com",
            status=SupportTicket.Status.RESOLVED,
            assigned_to=self.agent,
        )
        make_ticket(
            sender_email="agentresolvedtotal2@example.com",
            status=SupportTicket.Status.RESOLVED,
            assigned_to=self.agent,
        )
        make_ticket(
            sender_email="agentopenuntouched@example.com",
            status=SupportTicket.Status.OPEN,
            assigned_to=self.agent,
        )
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.data["data"]["total_resolved"], 2)

    def test_satisfaction_rate_for_logged_in_agent(self):
        t1 = make_ticket(
            sender_email="agentsat1@example.com",
            status=SupportTicket.Status.RESOLVED,
            assigned_to=self.agent,
        )
        t2 = make_ticket(
            sender_email="agentsat2@example.com",
            status=SupportTicket.Status.RESOLVED,
            assigned_to=self.agent,
        )
        SupportTicket.objects.filter(id=t1.id).update(satisfaction_score=5)
        SupportTicket.objects.filter(id=t2.id).update(satisfaction_score=3)
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.data["data"]["satisfaction_rate"], 4.0)

    def test_satisfaction_rate_null_when_no_scores(self):
        make_ticket(
            sender_email="agentnosat@example.com",
            status=SupportTicket.Status.RESOLVED,
            assigned_to=self.agent,
        )
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertIsNone(resp.data["data"]["satisfaction_rate"])

    def test_stats_only_counts_own_tickets_not_other_agents(self):
        make_ticket(
            sender_email="ownticket@example.com",
            status=SupportTicket.Status.OPEN,
            assigned_to=self.agent,
        )
        make_ticket(
            sender_email="otheragentticket@example.com",
            status=SupportTicket.Status.OPEN,
            assigned_to=self.other_agent,
        )
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.data["data"]["total_assigned"], 1)
        self.assertEqual(resp.data["data"]["open_tickets"], 1)

    def test_stats_for_agent_with_no_tickets(self):
        client = admin_auth_client(self.agent)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["total_assigned"], 0)
        self.assertEqual(data["open_tickets"], 0)
        self.assertEqual(data["in_progress"], 0)
        self.assertIsNone(data["avg_response_minutes"])
        self.assertIsNone(data["satisfaction_rate"])

    def test_super_admin_with_no_assigned_tickets_gets_zeroed_stats(self):
        make_ticket(
            sender_email="agenttickets@example.com",
            status=SupportTicket.Status.OPEN,
            assigned_to=self.agent,
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["total_assigned"], 0)

    def test_admin_without_support_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="agentstatsblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_request_is_blocked(self):
        resp = APIClient().get(f"{BASE}/admin/support/agents/me/stats/")
        self.assertEqual(resp.status_code, 403)
