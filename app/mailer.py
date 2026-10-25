"""E-Mail-Versand (SMTP) – z. B. PDF und Audiodateien einer Anfrage an Studio oder Kunden.

Zugangsdaten kommen aus der .env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
SMTP_SECURITY = starttls | ssl | none). Ohne SMTP_HOST ist der Versand deaktiviert.
"""
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
import os
import re
import smtplib
import socket
import ssl

from sqlalchemy.orm import Session

from .models import Setting

# Gesamtgröße der Anhänge (vor der Kodierung). Viele Mailserver erlauben 25 MB pro Mail,
# durch die Kodierung werden Anhänge rund ein Drittel größer.
MAX_ATTACHMENT_MB = float(os.getenv("MAIL_MAX_MB", "18"))
EMAIL_RE = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}")


class MailError(Exception):
    """Verständliche Fehlermeldung für den Admin."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    sender_name: str
    security: str


def config() -> SmtpConfig:
    security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    default_port = {"ssl": 465, "none": 25}.get(security, 587)
    user = os.getenv("SMTP_USER", "").strip()
    return SmtpConfig(
        host=os.getenv("SMTP_HOST", "").strip(),
        port=int(os.getenv("SMTP_PORT", "").strip() or default_port),
        user=user,
        password=os.getenv("SMTP_PASSWORD", ""),
        sender=os.getenv("SMTP_FROM", "").strip() or user,
        sender_name=os.getenv("SMTP_FROM_NAME", "onaircraft").strip(),
        security=security,
    )


def is_configured() -> bool:
    c = config()
    return bool(c.host and c.sender)


def default_recipient(db: Session) -> str:
    row = db.get(Setting, "mail_default_to")
    return row.value if row else ""


def save_default_recipient(db: Session, address: str) -> None:
    address = address.strip()
    if address and not EMAIL_RE.fullmatch(address):
        raise ValueError("Standard-Empfänger: bitte eine gültige E-Mail-Adresse angeben")
    db.merge(Setting(key="mail_default_to", value=address))
    db.commit()


def parse_recipients(raw: str) -> list[str]:
    """Eine oder mehrere Adressen, getrennt durch Komma, Strichpunkt oder Leerzeichen."""
    parts = [p for p in re.split(r"[\s,;]+", raw.strip()) if p]
    if not parts:
        raise MailError("Bitte eine Empfänger-Adresse angeben.")
    bad = [p for p in parts if not EMAIL_RE.fullmatch(p)]
    if bad:
        raise MailError(f"Ungültige E-Mail-Adresse: {', '.join(bad)}")
    if len(parts) > 10:
        raise MailError("Höchstens 10 Empfänger auf einmal.")
    return parts


def build_message(to: list[str], subject: str, body: str,
                  attachments: list[tuple[str, bytes, str]]) -> EmailMessage:
    c = config()
    total = sum(len(data) for _, data, _ in attachments)
    if total > MAX_ATTACHMENT_MB * 1024 * 1024:
        raise MailError(f"Die Anhänge sind zusammen {total / 1024 / 1024:.1f} MB groß – erlaubt sind "
                        f"{MAX_ATTACHMENT_MB:g} MB. Bitte weniger Dateien auswählen.")
    msg = EmailMessage()
    msg["From"] = formataddr((c.sender_name, c.sender))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=c.sender.split("@")[-1] or None)
    msg.set_content(body)
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


def send(msg: EmailMessage) -> None:
    """Blockierend – aus async-Code über einen Thread aufrufen."""
    c = config()
    if not (c.host and c.sender):
        raise MailError("E-Mail-Versand ist nicht eingerichtet (SMTP_HOST und SMTP_FROM in der .env).")
    context = ssl.create_default_context()
    try:
        if c.security == "ssl":
            server = smtplib.SMTP_SSL(c.host, c.port, timeout=60, context=context)
        else:
            server = smtplib.SMTP(c.host, c.port, timeout=60)
        with server:
            if c.security == "starttls":
                server.starttls(context=context)
            if c.user:
                server.login(c.user, c.password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailError("Anmeldung am Mailserver fehlgeschlagen – SMTP_USER/SMTP_PASSWORD prüfen "
                        "(bei Gmail ein App-Passwort verwenden).") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise MailError(f"Der Mailserver hat die Empfänger abgelehnt: {', '.join(e.recipients)}") from e
    except smtplib.SMTPSenderRefused as e:
        raise MailError(f"Der Mailserver hat den Absender {c.sender} abgelehnt – SMTP_FROM prüfen "
                        "(muss meist zum Konto passen).") from e
    except smtplib.SMTPDataError as e:
        detail = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        raise MailError(f"Der Mailserver hat die Nachricht abgelehnt (evtl. zu groß): {detail[:200]}") from e
    except (socket.timeout, TimeoutError) as e:
        raise MailError(f"Zeitüberschreitung bei der Verbindung zu {c.host}:{c.port}.") from e
    except ssl.SSLError as e:
        raise MailError("Verschlüsselung fehlgeschlagen – SMTP_SECURITY/SMTP_PORT prüfen "
                        "(587 = starttls, 465 = ssl).") from e
    except (OSError, smtplib.SMTPException) as e:
        raise MailError(f"Mailserver {c.host}:{c.port} nicht erreichbar: {e}") from e
