# flake8: noqa: E501
import html
import textwrap

from skiflux.models.investor import InvestorReview
from skiflux.tasks import send_app_email_task
from skiflux.utils.media import plain_text_safe


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0] if full_name.strip() else "there"


def _summary_rows(review: InvestorReview) -> list[tuple[str, str]]:
    return [
        ("Name", review.full_name),
        ("Email", review.email),
        ("Country", review.country),
        ("City", review.city),
        ("Investor Type", review.investor_type),
        ("Cheque Size", review.cheque_size_label),
        ("Decision Timeline", review.decision_timeline_label),
        ("Deck Preference", review.deck_preference_label),
        ("Scheduling", review.scheduling_note),
    ]


def _build_plain_text(review: InvestorReview) -> str:
    greeting_name = plain_text_safe(_first_name(review.full_name))
    rows = _summary_rows(review)
    summary_lines = "\n".join(
        f"{label}: {plain_text_safe(value)}" for label, value in rows
    )
    return textwrap.dedent(
        f"""\
        Hello {greeting_name},

        Thank you for submitting your Skiflux investor review. We have received
        your profile and preferences and our team will follow up with you shortly.

        Your submission summary:
        {summary_lines}

        Next steps:
        - If you have not booked your investor call yet, please use the Calendly
          link on the investor portal to schedule a 30-minute conversation with us.
        - Our team will review your submission and reach out if we need anything else.

        We appreciate your interest in Skiflux.

        Best,
        The Skiflux Team
        """
    )


def _build_html(review: InvestorReview) -> str:
    greeting_name = html.escape(_first_name(review.full_name))
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #2d1f4e;color:#b8a9d4;font-size:13px;width:38%;">{html.escape(label)}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #2d1f4e;color:#ffffff;font-size:14px;font-weight:600;">{html.escape(value)}</td>
        </tr>
        """
        for label, value in _summary_rows(review)
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
  <body style="margin:0;padding:0;background-color:#0f0818;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#0f0818;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background-color:#160f24;border-radius:16px;overflow:hidden;border:1px solid #2d1f4e;">
            <tr>
              <td style="background:linear-gradient(135deg,#5b21b6,#7c3aed);padding:28px 32px;">
                <p style="margin:0;color:#ede9fe;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;">Skiflux Investor Review</p>
                <h1 style="margin:8px 0 0;color:#ffffff;font-size:28px;line-height:1.2;">Submission Received</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 16px;color:#ffffff;font-size:16px;line-height:1.6;">Hello {greeting_name},</p>
                <p style="margin:0 0 24px;color:#d1c4e9;font-size:15px;line-height:1.7;">
                  Thank you for submitting your investor review. Your profile and preferences
                  have been saved securely, and our team will follow up with you shortly.
                </p>
                <h2 style="margin:0 0 12px;color:#ffffff;font-size:18px;">Your submission summary</h2>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#1a112b;border-radius:12px;overflow:hidden;margin-bottom:24px;">
                  {rows_html}
                </table>
                <div style="background-color:#1a112b;border-radius:12px;padding:20px 22px;margin-bottom:24px;">
                  <h3 style="margin:0 0 10px;color:#ffffff;font-size:16px;">Next steps</h3>
                  <p style="margin:0 0 10px;color:#d1c4e9;font-size:14px;line-height:1.7;">
                    If you have not booked your investor call yet, please use the Calendly link
                    on the investor portal to schedule a 30-minute conversation with us.
                  </p>
                  <p style="margin:0;color:#d1c4e9;font-size:14px;line-height:1.7;">
                    Our team will review your submission and reach out if we need anything else.
                  </p>
                </div>
                <p style="margin:0;color:#ffffff;font-size:15px;line-height:1.6;">
                  We appreciate your interest in Skiflux.
                </p>
                <p style="margin:18px 0 0;color:#d1c4e9;font-size:14px;line-height:1.6;">
                  Best,<br>
                  <strong style="color:#ffffff;">The Skiflux Team</strong>
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def send_investor_confirmation_email(review: InvestorReview) -> bool:
    subject = "Your Skiflux Investor Review — Received"
    plain_text = _build_plain_text(review)
    html_content = _build_html(review)
    send_app_email_task.apply_async(
        args=[subject, plain_text, review.email],
        kwargs={"html_message": html_content},
    )
    return True
