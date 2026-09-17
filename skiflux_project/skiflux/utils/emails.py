import textwrap

from skiflux.tasks import send_app_email_task


def send_warning_email(
    email: str,
    category: str,
    message: str,
) -> bool:
    subject = "Community Guidelines Warning"

    body = textwrap.dedent(
        f"""\
        Hello,

        We are reaching out regarding activity on your SkiFlux account.

        Warning Category: {category}

        Details:
        {message}

        Please ensure your future interactions comply with our community
        guidelines. Continued violations may result in account restrictions
        or suspension.

        Best,
        The SkiFlux Moderation Team
        """
    )

    send_app_email_task.apply_async(args=[subject, body, email])
    return True


def send_comment_removed_email(
    email: str,
    reason: str,
) -> bool:
    subject = "Your Comment Has Been Removed"

    body = textwrap.dedent(
        f"""\
        Hello,

        One of your comments has been removed by our moderation team.

        Reason:
        {reason}

        This action was taken because the content was found to violate
        SkiFlux community guidelines.

        Please review our community standards before posting again.

        Best,
        The SkiFlux Moderation Team
        """
    )

    send_app_email_task.apply_async(args=[subject, body, email])
    return True


def send_suspension_email(
    email: str,
    reason: str,
    duration_days: int | None,
) -> bool:
    subject = "Account Suspension Notice"

    duration_text = f"{duration_days} day(s)" if duration_days else "permanently"

    body = textwrap.dedent(
        f"""\
        Hello,

        Your SkiFlux account has been suspended.

        Suspension Duration:
        {duration_text}

        Reason:
        {reason}

        During this period, you may be unable to access certain features
        or your account entirely.

        If you believe this action was taken in error, please contact
        our support team.

        Best,
        The SkiFlux Moderation Team
        """
    )

    send_app_email_task.apply_async(args=[subject, body, email])
    return True


def send_suspension_lifted_email(
    email: str,
) -> bool:
    subject = "Account Suspension Lifted"

    body = textwrap.dedent(
        """\
        Hello,

        We are pleased to inform you that your account suspension has
        been lifted.

        You may now continue using SkiFlux normally.

        Please continue to follow our community guidelines to help
        maintain a positive learning environment for everyone.

        Welcome back!

        Best,
        The SkiFlux Moderation Team
        """
    )

    send_app_email_task.apply_async(args=[subject, body, email])
    return True
