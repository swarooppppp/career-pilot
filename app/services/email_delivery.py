"""Send generated resumes through an SMTP server."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def send_resume_email(pdf_path: Path) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    recipient = os.getenv("RESUME_RECIPIENT")
    if not all((host, username, password, recipient)):
        return False

    message = EmailMessage()
    message["Subject"] = f"Tailored resume - {pdf_path.stem}"
    message["From"] = username
    message["To"] = recipient
    message.set_content("Your tailored resume is attached.")
    message.add_attachment(
        pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name
    )

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)
    return True
