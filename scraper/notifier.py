"""
notifier.py
-----------
Sends email alerts when permit status or inspection results change.
Uses SMTP (works with Gmail App Passwords, Outlook, or any SMTP provider).
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from .accela_scraper import PermitRecord

logger = logging.getLogger(__name__)


def send_change_alert(changed_records: list[PermitRecord]):
    """Send an email summarizing all permit changes detected."""
    if not changed_records:
        return

    to_email = os.environ.get("NOTIFY_EMAIL", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")

    if not all([to_email, smtp_user, smtp_pass]):
        logger.warning("Email notification skipped — SMTP credentials not fully set.")
        return

    subject = f"🚨 Permit Update Alert — {len(changed_records)} change(s) detected"
    
    # Build HTML email body
    rows_html = ""
    for rec in changed_records:
        rows_html += f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd;font-weight:bold">{rec.permit_number}</td>
            <td style="padding:8px;border:1px solid #ddd">{rec.address}</td>
            <td style="padding:8px;border:1px solid #ddd">{rec.municipality}</td>
            <td style="padding:8px;border:1px solid #ddd;color:#d9534f;font-weight:bold">{rec.status}</td>
            <td style="padding:8px;border:1px solid #ddd">{rec.last_inspection}</td>
            <td style="padding:8px;border:1px solid #ddd">{rec.inspection_result}</td>
            <td style="padding:8px;border:1px solid #ddd">{rec.expiration_date}</td>
        </tr>"""

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333">
    <h2 style="color:#1a3a5c">🏗️ Permit Status Update</h2>
    <p>The following permits had changes since the last check:</p>
    
    <table style="border-collapse:collapse;width:100%;margin-top:16px">
        <thead>
            <tr style="background:#1a3a5c;color:white">
                <th style="padding:10px;text-align:left">Permit #</th>
                <th style="padding:10px;text-align:left">Address</th>
                <th style="padding:10px;text-align:left">Municipality</th>
                <th style="padding:10px;text-align:left">New Status</th>
                <th style="padding:10px;text-align:left">Last Inspection</th>
                <th style="padding:10px;text-align:left">Result</th>
                <th style="padding:10px;text-align:left">Expires</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>

    <p style="margin-top:24px;color:#666;font-size:13px">
        Checked: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}<br>
        <a href="https://docs.google.com/spreadsheets/d/{os.environ.get('GOOGLE_SHEET_ID','')}">
            View full tracker in Google Sheets →
        </a>
    </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        logger.info(f"Alert email sent to {to_email} for {len(changed_records)} change(s).")
    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
