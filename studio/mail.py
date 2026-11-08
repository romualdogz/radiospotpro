"""E-Mails des Studios (Einladung, Benachrichtigung an onaircraft) über den SMTP-Zugang aus der .env."""
from app import mailer

from .config import settings
from .models import ROLES


def enabled() -> bool:
    return mailer.is_configured()


def send_invitation(email: str, url: str, role: str, expires_at) -> None:
    body = (f"Hallo,\n\nSie wurden zum Radiospot-Studio von onaircraft eingeladen ({ROLES.get(role, role)}).\n\n"
            f"Hier richten Sie Ihr Konto ein und vergeben Ihr Passwort:\n{url}\n\n"
            f"Der Link ist einmal verwendbar und gültig bis {expires_at:%d.%m.%Y %H:%M} Uhr (UTC).\n\n"
            "Viele Grüße\nonaircraft")
    mailer.send(mailer.build_message([email], "Ihre Einladung zum Radiospot-Studio", body, []))


def notify_support(user_email: str, project: str, message: str, admin_url: str) -> bool:
    """Benachrichtigung an onaircraft; False, wenn keine Adresse oder kein SMTP eingerichtet ist."""
    if not (settings.support_email and enabled()):
        return False
    body = (f"{user_email} hat das Projekt „{project}“ an onaircraft geschickt.\n\n"
            f"Nachricht:\n{message or '(keine)'}\n\nIm Studio öffnen: {admin_url}\n")
    mailer.send(mailer.build_message([settings.support_email], f"Studio: Projekt „{project}“ von {user_email}", body, []))
    return True
