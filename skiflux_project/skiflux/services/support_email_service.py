import email
import imaplib
import logging
import re
import smtplib
import uuid as _uuid
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr, parsedate_to_datetime
from email.mime.base import MIMEBase
from email import encoders

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from skiflux.models import User
from skiflux.models.support import SupportTicket, TicketMessage

logger = logging.getLogger(__name__)


def decode_mime_words(value: str) -> str:
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(encoding or "utf-8", errors="ignore")
        else:
            result += part
    return result.strip()


def extract_email_body(msg) -> tuple[str, str]:
    body_text = ""
    body_html = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="ignore")

                if content_type == "text/plain":
                    body_text += decoded
                elif content_type == "text/html":
                    body_html += decoded
            except Exception:
                continue
    else:
        content_type = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            if payload:
                decoded = payload.decode(charset, errors="ignore")
                if content_type == "text/plain":
                    body_text = decoded
                elif content_type == "text/html":
                    body_html = decoded
        except Exception:
            pass

    return body_text.strip(), body_html.strip()


def extract_attachments(msg) -> list[dict]:
    """
    Returns a list of attachment dicts for later storage.
    {filename, content_type, payload (bytes)}
    """
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition"))
            if "attachment" not in content_disposition:
                continue
            filename = part.get_filename()
            if not filename:
                continue
            filename = decode_mime_words(filename)
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append(
                    {
                        "filename": filename,
                        "content_type": part.get_content_type(),
                        "payload": payload,
                        "size": len(payload),
                    }
                )
    return attachments


def _connect_imap() -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(
        settings.SUPPORT_EMAIL_HOST,
        settings.SUPPORT_EMAIL_PORT,
    )
    mail.login(
        settings.SUPPORT_EMAIL_USERNAME,
        settings.SUPPORT_EMAIL_PASSWORD,
    )
    return mail


def _find_existing_ticket(msg) -> SupportTicket | None:
    """
    Check In-Reply-To and References headers to find
    if this email belongs to an existing ticket thread.
    """
    in_reply_to = msg.get("In-Reply-To", "").strip()
    references = msg.get("References", "").strip()

    # collect all message IDs mentioned in threading headers
    candidates = set()
    if in_reply_to:
        candidates.add(in_reply_to)
    if references:
        for ref in references.split():
            candidates.add(ref.strip())

    if not candidates:
        return None

    # check if any of those IDs match a known ticket or message
    ticket = SupportTicket.objects.filter(email_message_id__in=candidates).first()

    if ticket:
        return ticket

    # also check TicketMessage level — reply to an outbound message
    message = (
        TicketMessage.objects.filter(email_message_id__in=candidates)
        .select_related("ticket")
        .first()
    )

    return message.ticket if message else None


def _resolve_user(sender_email: str) -> User | None:
    return User.objects.filter(
        email__iexact=sender_email,
        is_active=True,
    ).first()


def _auto_categorise(subject: str, body: str) -> str:
    """Improved categorization with notification detection"""
    text = f"{subject} {body}".lower()

    # Check if it's a notification/newsletter first
    notification_patterns = [
        r"notification",
        r"alert",
        r"update from",
        r"newsletter",
        r"weekly digest",
        r"monthly report",
        r"no-reply",
        r"do not reply",
        r"automated message",
        r"system notification",
    ]

    # Also check if sender looks like automated (add to calling function)

    for pattern in notification_patterns:
        if re.search(pattern, text):
            return SupportTicket.Category.OTHER.value

    # Payment/transaction issues
    payment_patterns = [
        r"\bdeposit\b",
        r"\bpayment\b",
        r"\btransaction\b",
        r"\bcoin\b",
        r"\bcredit\b",
        r"\bpaystack\b",
        r"\bwithdraw\b",
        r"\bwithdrawal\b",
        r"\brefund\b",
        r"\bcharge\b",
        r"\binvoice\b",
        r"\bbilling\b",
        r"payment failed",
        r"transaction failed",
        r"card declined",
    ]

    for pattern in payment_patterns:
        if re.search(pattern, text):
            return SupportTicket.Category.FAILED_TRANSACTION.value

    # Verification issues
    verification_patterns = [
        r"\bverify\b",
        r"\bverification\b",
        r"\botp\b",
        r"\bcode\b",
        r"\bkyc\b",
        r"verify your",
        r"verification code",
        r"email verification",
        r"identity verification",
        r"document verification",
    ]

    for pattern in verification_patterns:
        if re.search(pattern, text):
            return SupportTicket.Category.VERIFICATION_DELAY.value

    # Bug reports
    bug_patterns = [
        r"\bbug\b",
        r"\berror\b",
        r"\bcrash\b",
        r"\bbroken\b",
        r"not working",
        r"doesn't work",
        r"issue with",
        r"problem with",
        r"glitch",
        r"freeze",
        r"lag",
    ]

    for pattern in bug_patterns:
        if re.search(pattern, text):
            return SupportTicket.Category.BUG_REPORT.value

    # Account access issues
    access_patterns = [
        r"\blogin\b",
        r"\bpassword\b",
        r"\baccess\b",
        r"can't log in",
        r"cannot log in",
        r"\blocked\b",
        r"forgot password",
        r"reset password",
        r"account locked",
        r"unauthorized",
        r"suspicious activity",
        r"hacked",
        r"compromised",
        r"2fa",
        r"two factor",
    ]

    for pattern in access_patterns:
        if re.search(pattern, text):
            return SupportTicket.Category.ACCOUNT_ACCESS.value

    return SupportTicket.Category.OTHER.value


def _process_raw_email(msg) -> tuple[SupportTicket | None, bool]:
    """
    Parse a raw email message and create or update
    the appropriate SupportTicket + TicketMessage.

    Returns (ticket, created) or (None, False) if skipped.
    """
    message_id = msg.get("Message-ID", "").strip()
    subject = decode_mime_words(msg.get("Subject", "(No Subject)"))
    from_header = msg.get("From", "")
    sender_name, sender_email = parseaddr(from_header)
    sender_name = decode_mime_words(sender_name)

    if not sender_email:
        logger.warning("Skipping email with no sender.")
        return None, False

    # skip emails sent from our own support address
    if sender_email.lower() == settings.SUPPORT_EMAIL_USERNAME.lower():
        return None, False

    # deduplication — skip if this message_id already stored
    if (
        message_id
        and TicketMessage.objects.filter(email_message_id=message_id).exists()
    ):
        return None, False

    date_header = msg.get("Date")
    try:
        received_at = parsedate_to_datetime(date_header)
        if received_at and timezone.is_naive(received_at):
            received_at = timezone.make_aware(received_at)
    except Exception:
        received_at = timezone.now()

    body_text, body_html = extract_email_body(msg)
    body = body_text or body_html
    attachments = extract_attachments(msg)

    user = _resolve_user(sender_email)
    existing_ticket = _find_existing_ticket(msg)

    with transaction.atomic():
        if existing_ticket:
            # this is a reply — attach to existing ticket
            ticket = existing_ticket
            ticket_created = False

            # re-open if it was resolved
            if ticket.status == SupportTicket.Status.RESOLVED:
                ticket.status = SupportTicket.Status.OPEN
                ticket.save(update_fields=["status", "updated_at"])
        else:
            # new ticket
            category = _auto_categorise(subject, body)
            ticket = SupportTicket.objects.create(
                user=user,
                sender_email=sender_email,
                sender_name=sender_name or sender_email,
                subject=subject,
                category=category,
                status=SupportTicket.Status.OPEN,
                email_message_id=message_id,
            )
            ticket_created = True

        # store the inbound message
        ticket_message = TicketMessage.objects.create(
            ticket=ticket,
            direction=TicketMessage.Direction.INBOUND,
            body=body,
            body_html=body_html,
            email_message_id=message_id,
            received_at=received_at,
        )

        # store attachments
        if attachments:
            _store_attachments(ticket_message, attachments)

    return ticket, ticket_created


def _store_attachments(message: TicketMessage, attachments: list[dict]) -> None:
    from skiflux.models.support import TicketAttachment
    from skiflux.utils.media import upload_to_minio
    from skiflux.tasks.content import upload_media_from_minio_task

    for att in attachments:
        try:
            import io

            file_obj = io.BytesIO(att["payload"])
            file_obj.name = att["filename"]
            minio_key = upload_to_minio(file_obj, folder="skiflux_support_attachments")

            attachment = TicketAttachment.objects.create(
                message=message,
                file_name=att["filename"],
                file_size=att["size"],
                content_type=att["content_type"],
            )

            upload_media_from_minio_task.delay(
                instance_id=attachment.id,
                minio_object_key=minio_key,
                field_name="file_url",
                model_name="TicketAttachment",
                resource_type="raw"
                if attachment.content_type.startswith("application/")
                else "image",
                content_type=attachment.content_type,
            )
        except Exception as e:
            logger.error(f"Failed to store attachment {att['filename']}: {e}")


def fetch_support_emails(limit: int = 20) -> dict:
    """
    Connect to the support mailbox via IMAP,
    fetch recent unseen emails, and process each one.
    """
    if not settings.SUPPORT_EMAIL_USERNAME or not settings.SUPPORT_EMAIL_PASSWORD:
        raise ValueError("Support email credentials are not configured.")

    mail = _connect_imap()

    try:
        mail.select("inbox")

        # fetch only UNSEEN emails — more efficient than ALL
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            raise Exception("Failed to search inbox.")

        email_ids = messages[0].split()
        if not email_ids:
            logger.info("fetch_support_emails: no new emails.")
            return {"fetched": 0, "new_tickets": 0, "replies": 0}

        # take the most recent `limit` unseen emails
        latest_ids = email_ids[-limit:]

        new_tickets = 0
        replies = 0
        fetched = 0

        for email_id in reversed(latest_ids):
            try:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                ticket, created = _process_raw_email(msg)

                if ticket:
                    fetched += 1
                    if created:
                        new_tickets += 1
                    else:
                        replies += 1

                    # mark as seen in mailbox
                    mail.store(email_id, "+FLAGS", "\\Seen")

            except Exception as e:
                logger.error(
                    f"fetch_support_emails: failed to process email {email_id}: {e}"
                )
                continue

    finally:
        mail.logout()

    logger.info(
        f"fetch_support_emails: fetched={fetched} "
        f"new_tickets={new_tickets} replies={replies}"
    )
    return {"fetched": fetched, "new_tickets": new_tickets, "replies": replies}


def send_support_reply(
    ticket,
    body: str,
    sender_admin,
    attachments=None,
) -> TicketMessage:

    attachments = attachments or []

    outbound_message_id = f"<{_uuid.uuid4()}@skiflux.com>"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Re: {ticket.subject}"
    msg["From"] = f"Skiflux Support <{settings.SUPPORT_EMAIL_USERNAME}>"
    msg["To"] = ticket.sender_email

    if ticket.email_message_id:
        msg["In-Reply-To"] = ticket.email_message_id
        msg["References"] = ticket.email_message_id

    msg["Message-ID"] = outbound_message_id

    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body, "plain"))
    body_part.attach(MIMEText(f"<p>{body}</p>", "html"))
    msg.attach(body_part)

    stored_attachments = []

    for file in attachments:
        file_data = file.read()

        mime = MIMEBase("application", "octet-stream")
        mime.set_payload(file_data)
        encoders.encode_base64(mime)

        mime.add_header(
            "Content-Disposition",
            "attachment",
            filename=file.name,
        )
        mime.add_header(
            "Content-Type",
            file.content_type or "application/octet-stream",
            name=file.name,
        )

        msg.attach(mime)

        stored_attachments.append(
            {
                "filename": file.name,
                "content_type": file.content_type or "application/octet-stream",
                "payload": file_data,
                "size": len(file_data),
            }
        )

        file.seek(0)

    try:
        with smtplib.SMTP_SSL(
            settings.SUPPORT_SMTP_HOST,
            settings.SUPPORT_SMTP_PORT,
        ) as server:
            server.login(
                settings.SUPPORT_EMAIL_USERNAME,
                settings.SUPPORT_EMAIL_PASSWORD,
            )
            server.sendmail(
                settings.SUPPORT_EMAIL_USERNAME,
                ticket.sender_email,
                msg.as_string(),
            )

    except Exception as e:
        logger.error(f"Email send failed: {e}")
        raise

    with transaction.atomic():
        ticket_message = TicketMessage.objects.create(
            ticket=ticket,
            direction=TicketMessage.Direction.OUTBOUND,
            sender_admin=sender_admin,
            body=body,
            body_html=f"<p>{body}</p>",
            email_message_id=outbound_message_id,
            received_at=timezone.now(),
        )

        if stored_attachments:
            _store_attachments(ticket_message, stored_attachments)

        if ticket.status == SupportTicket.Status.OPEN:
            ticket.status = SupportTicket.Status.IN_PROGRESS
            ticket.save(update_fields=["status", "updated_at"])

    return ticket_message
