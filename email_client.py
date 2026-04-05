"""Email delivery module for AIFitnessSummary.

Converts Markdown reports to styled HTML and sends them via Gmail SMTP (SSL).
All configuration is read from environment variables; if any required variable
is missing, get_email_client() returns None and email is silently skipped.
"""
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown as md_lib

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 465


class EmailClient:
    """Send HTML fitness-review emails via Gmail SMTP (SSL/port 465)."""

    def __init__(self, sender: str, recipient: str, app_password: str) -> None:
        self._sender = sender
        self._recipient = recipient
        self._app_password = app_password

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_report(self, period: str, end_date: str, markdown_content: str) -> bool:
        """Convert *markdown_content* to HTML and send it as an email.

        Parameters
        ----------
        period:
            ``"weekly"`` or ``"monthly"`` — used to build the subject line.
        end_date:
            ISO-8601 string (``YYYY-MM-DD``) representing the last day of the
            review period — also used in the subject line.
        markdown_content:
            The full Markdown report text.

        Returns
        -------
        bool
            ``True`` on success, ``False`` if an exception is raised.
        """
        subject = self._build_subject(period, end_date)
        html_body = self._markdown_to_html(markdown_content)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._sender
        msg["To"] = self._recipient

        # Plain-text fallback (raw Markdown is perfectly readable as plain text)
        msg.attach(MIMEText(markdown_content, "plain", "utf-8"))
        # Rich HTML part (preferred by mail clients that support it)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context) as server:
                server.login(self._sender, self._app_password)
                server.sendmail(self._sender, self._recipient, msg.as_string())
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[EmailClient] Failed to send email: {exc}")
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_subject(self, cadence: str, end_date: str) -> str:
        """Return the formatted email subject line.

        weekly          → "Weekly Fitness Digest — April 5, 2026"
        block_checkin   → "Block Check-In — April 5, 2026"
        end_of_programme → "End of Programme Review — April 5, 2026"
        """
        dt = datetime.strptime(end_date, "%Y-%m-%d")
        date_str = dt.strftime("%B %-d, %Y")
        label_map = {
            "weekly": "Weekly Fitness Digest",
            "block_checkin": "Block Check-In",
            "end_of_programme": "End of Programme Review",
        }
        label = label_map.get(cadence, cadence.replace("_", " ").title())
        return f"{label} \u2014 {date_str}"

    def _markdown_to_html(self, md: str) -> str:
        """Convert Markdown to a complete, self-contained styled HTML document.

        All styles are inlined so they survive email-client CSS stripping.
        """
        body_html = md_lib.markdown(
            md,
            extensions=["tables", "fenced_code", "nl2br"],
        )

        today_str = datetime.now().strftime("%B %-d, %Y")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<title>Fitness Review</title>
<style>
  /* ── Reset & base ─────────────────────────────────────────────── */
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
                 Roboto, Helvetica, Arial, sans-serif;
    font-size: 16px;
    line-height: 1.6;
    color: #333;
    background-color: #f0f2f5;
  }}

  /* ── Outer wrapper ────────────────────────────────────────────── */
  .wrapper {{
    max-width: 680px;
    margin: 24px auto;
    background-color: #ffffff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,.12);
  }}

  /* ── Header band ──────────────────────────────────────────────── */
  .header {{
    background-color: #1a1a2e;
    padding: 28px 32px;
    text-align: center;
  }}
  .header h1 {{
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: .5px;
    margin: 0;
  }}
  .header p {{
    color: #a0a8c0;
    font-size: 13px;
    margin-top: 6px;
  }}

  /* ── Content area ─────────────────────────────────────────────── */
  .content {{
    padding: 28px 32px;
  }}

  /* ── Headings ─────────────────────────────────────────────────── */
  .content h1 {{
    font-size: 20px;
    color: #1a1a2e;
    margin: 24px 0 12px;
  }}
  .content h2 {{
    font-size: 18px;
    color: #2c5f8a;
    border-bottom: 1px solid #e0e0e0;
    padding-bottom: 6px;
    margin: 28px 0 12px;
  }}
  .content h3 {{
    font-size: 15px;
    color: #444;
    margin: 18px 0 8px;
  }}

  /* ── Paragraphs & lists ───────────────────────────────────────── */
  .content p {{
    margin: 0 0 12px;
  }}
  .content ul,
  .content ol {{
    margin: 0 0 12px 24px;
  }}
  .content li {{
    margin-bottom: 4px;
  }}

  /* ── Tables ───────────────────────────────────────────────────── */
  .content table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    margin: 12px 0 20px;
  }}
  .content th {{
    background-color: #2c5f8a;
    color: #ffffff;
    padding: 9px 12px;
    text-align: left;
    font-weight: 600;
  }}
  .content td {{
    padding: 8px 12px;
    border-bottom: 1px solid #e8e8e8;
  }}
  .content tr:nth-child(even) td {{
    background-color: #f9f9f9;
  }}
  .content tr:last-child td {{
    border-bottom: none;
  }}

  /* ── Code ─────────────────────────────────────────────────────── */
  .content code {{
    background-color: #f4f4f4;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 13px;
    padding: 2px 5px;
    border-radius: 3px;
  }}
  .content pre {{
    background-color: #f4f4f4;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 13px;
    padding: 14px 16px;
    border-radius: 5px;
    overflow-x: auto;
    margin: 0 0 16px;
  }}
  .content pre code {{
    background: none;
    padding: 0;
  }}

  /* ── Blockquotes (executive-summary callout) ──────────────────── */
  .content blockquote {{
    border-left: 4px solid #2c5f8a;
    background-color: #eef5fb;
    margin: 16px 0;
    padding: 12px 16px;
    border-radius: 0 4px 4px 0;
    color: #2c3e50;
  }}
  .content blockquote p {{
    margin: 0;
  }}

  /* ── Bold emphasis ────────────────────────────────────────────── */
  .content strong {{
    color: #1a1a2e;
  }}

  /* ── Horizontal rule ──────────────────────────────────────────── */
  .content hr {{
    border: none;
    border-top: 1px solid #e0e0e0;
    margin: 24px 0;
  }}

  /* ── Footer ───────────────────────────────────────────────────── */
  .footer {{
    background-color: #f7f8fa;
    border-top: 1px solid #e0e0e0;
    padding: 14px 32px;
    text-align: center;
    font-size: 12px;
    color: #888;
  }}

  /* ── Responsive — mobile ──────────────────────────────────────── */
  @media (max-width: 480px) {{
    body {{ font-size: 14px; }}
    .wrapper {{ margin: 0; border-radius: 0; }}
    .header {{ padding: 20px 18px; }}
    .content {{ padding: 20px 18px; }}
    .footer {{ padding: 12px 18px; }}
    .content th,
    .content td {{ padding: 7px 8px; font-size: 13px; }}
  }}

  /* ── Dark mode ────────────────────────────────────────────────── */
  @media (prefers-color-scheme: dark) {{
    body {{ background-color: #111; color: #e0e0e0; }}
    .wrapper {{ background-color: #1e1e1e; box-shadow: 0 2px 8px rgba(0,0,0,.5); }}
    .content h2 {{ color: #6aaddc; border-bottom-color: #333; }}
    .content h3 {{ color: #bbb; }}
    .content h1 {{ color: #e0e0e0; }}
    .content strong {{ color: #e0e0e0; }}
    .content th {{ background-color: #1e4a72; }}
    .content td {{ border-bottom-color: #2a2a2a; }}
    .content tr:nth-child(even) td {{ background-color: #252525; }}
    .content code,
    .content pre {{ background-color: #2a2a2a; color: #e0e0e0; }}
    .content blockquote {{ background-color: #1a2d3e; border-left-color: #6aaddc; color: #d0e4f0; }}
    .content hr {{ border-top-color: #333; }}
    .footer {{ background-color: #161616; border-top-color: #2a2a2a; color: #666; }}
  }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Fitness Review</h1>
    <p>Your personalised AI-powered fitness summary</p>
  </div>
  <div class="content">
    {body_html}
  </div>
  <div class="footer">
    Generated by AIFitnessSummary &middot; {today_str}
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_email_client() -> "EmailClient | None":
    """Return an :class:`EmailClient` if all required env vars are set.

    Required environment variables:

    * ``EMAIL_SENDER`` — Gmail address used as the *From* address.
    * ``EMAIL_RECIPIENT`` — destination address.
    * ``GMAIL_APP_PASSWORD`` — 16-character Gmail app password.

    If any variable is missing, returns ``None`` so that callers can
    silently skip email delivery without crashing.
    """
    sender = os.environ.get("EMAIL_SENDER", "").strip()
    recipient = os.environ.get("EMAIL_RECIPIENT", "").strip()
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not sender or not recipient or not app_password:
        return None

    return EmailClient(sender=sender, recipient=recipient, app_password=app_password)
