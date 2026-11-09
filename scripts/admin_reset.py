"""Admin-Zugang im Terminal zurücksetzen – für Konfigurator und Studio.

Hilft, wenn das Admin-Passwort vergessen ist, das Konto gesperrt oder abgelaufen ist oder das Handy für die
Zwei-Faktor-Anmeldung fehlt. Fehlt das Konto, wird es angelegt.

    python scripts/admin_reset.py                       # fragt alles ab
    python scripts/admin_reset.py --studio --user ron@onaircraft.net
    python scripts/admin_reset.py --konfigurator --user admin --generate
    python scripts/admin_reset.py --list                # vorhandene Admins anzeigen

Am Mac: Doppelklick auf admin-zuruecksetzen.command.
Läuft der Server, muss er nicht neu gestartet werden – nur eine Sperre nach zu vielen Fehlversuchen
(15 Minuten) hebt erst ein Neustart auf.
"""
import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)  # relative Datenbankpfade (sqlite:///./…) wie beim Server auflösen
sys.path.insert(0, str(ROOT))

MIN_PASSWORD = 10


class ResetError(Exception):
    pass


# --------------------------------------------------------------------------- Konfigurator

def configurator_admins() -> list[str]:
    from app.database import SessionLocal, upgrade_schema
    from app.models import AdminUser
    upgrade_schema()
    with SessionLocal() as db:
        return [u.username for u in db.query(AdminUser).filter_by(role="admin").order_by(AdminUser.id)]


def reset_configurator(username: str, password: str) -> str:
    from app.database import SessionLocal, upgrade_schema
    from app.models import AdminUser
    from app.security import hash_password
    upgrade_schema()
    with SessionLocal() as db:
        user = db.query(AdminUser).filter_by(username=username).first()
        created = user is None
        if created:
            user = AdminUser(username=username, password_hash="")
            db.add(user)
        user.password_hash = hash_password(password)
        user.role = "admin"
        db.commit()
    return "angelegt" if created else "zurückgesetzt"


# --------------------------------------------------------------------------- Studio

def studio_admins() -> list[str]:
    from studio.database import SessionLocal, init_db
    from studio.models import StudioUser
    init_db()
    with SessionLocal() as db:
        return [u.email for u in db.query(StudioUser).filter_by(role="admin").order_by(StudioUser.id)]


def reset_studio(email: str, password: str) -> str:
    from studio.accounts import AccountError, normalize_email
    from studio.database import SessionLocal, init_db
    from studio.models import StudioUser
    from studio.security import hash_password, password_problem
    try:
        email = normalize_email(email)
    except AccountError as e:
        raise ResetError(str(e)) from e
    if problem := password_problem(password, email):
        raise ResetError(problem)
    init_db()
    with SessionLocal() as db:
        user = db.query(StudioUser).filter_by(email=email).first()
        created = user is None
        if created:
            user = StudioUser(email=email, password_hash="", role="admin")
            db.add(user)
        user.password_hash = hash_password(password)
        user.role, user.active, user.valid_until = "admin", True, None
        user.totp_secret, user.totp_enabled, user.totp_last_step = None, False, None
        user.session_epoch = (user.session_epoch or 0) + 1  # alle bisherigen Anmeldungen beenden
        db.commit()
    return "angelegt" if created else "zurückgesetzt"


# --------------------------------------------------------------------------- Ablauf

def ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def ask_password() -> str | None:
    """Neues Passwort abfragen; leer = zufälliges erzeugen (None)."""
    while True:
        pw = getpass.getpass(f"Neues Passwort (mind. {MIN_PASSWORD} Zeichen, leer = zufällig erzeugen): ")
        if not pw:
            return None
        if len(pw) < MIN_PASSWORD:
            print(f"  Zu kurz – bitte mindestens {MIN_PASSWORD} Zeichen.")
            continue
        if pw != getpass.getpass("Passwort wiederholen: "):
            print("  Die Passwörter stimmen nicht überein.")
            continue
        return pw


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="admin_reset", description="Admin-Zugang zurücksetzen (Konfigurator oder Studio)")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--studio", action="store_true", help="Admin des Radiospot-Studios")
    which.add_argument("--konfigurator", action="store_true", help="Admin des Konfigurators (/admin)")
    p.add_argument("--user", help="E-Mail (Studio) bzw. Benutzername (Konfigurator)")
    p.add_argument("--password", help="neues Passwort (sonst wird gefragt)")
    p.add_argument("--generate", action="store_true", help="zufälliges Passwort erzeugen und anzeigen")
    p.add_argument("--list", action="store_true", help="vorhandene Admins anzeigen")
    args = p.parse_args(argv)

    if args.list:
        print("Konfigurator:", ", ".join(configurator_admins()) or "–")
        print("Studio:      ", ", ".join(studio_admins()) or "–")
        return 0

    interactive = sys.stdin.isatty()
    try:
        if args.studio or args.konfigurator:
            target = "studio" if args.studio else "konfigurator"
        elif interactive:
            print("Welchen Admin zurücksetzen?\n  1) Radiospot-Studio\n  2) Konfigurator (/admin)")
            target = {"1": "studio", "2": "konfigurator"}.get(ask("Auswahl", "1"))
            if target is None:
                raise ResetError("Bitte 1 oder 2 wählen.")
        else:
            raise ResetError("Bitte --studio oder --konfigurator angeben.")

        existing = studio_admins() if target == "studio" else configurator_admins()
        user = args.user
        if not user:
            if not interactive:
                raise ResetError("Bitte --user angeben.")
            if existing:
                print("Vorhandene Admins: " + ", ".join(existing))
            default = existing[0] if existing else ("admin@localhost" if target == "studio" else "admin")
            user = ask("E-Mail" if target == "studio" else "Benutzername", default)
        if not user.strip():
            raise ResetError("Kein Konto angegeben.")
        user = user.strip()

        if args.password:
            password, shown = args.password, False
        elif args.generate or not interactive:
            password, shown = None, True
        else:
            password = ask_password()
            shown = password is None
        if password is None:
            password = secrets.token_urlsafe(12)
        if len(password) < MIN_PASSWORD:
            raise ResetError(f"Das Passwort muss mindestens {MIN_PASSWORD} Zeichen haben.")

        if target == "studio":
            result = reset_studio(user, password)
            extras = "Rolle Administrator, aktiv, ohne Ablaufdatum, Zwei-Faktor aus, alle Geräte abgemeldet."
        else:
            result = reset_configurator(user, password)
            extras = "Rolle Administrator."
    except ResetError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1

    name = "Studio" if target == "studio" else "Konfigurator"
    print(f"\n✔ {name}-Admin „{user}“ {result}. {extras}")
    if shown:
        print(f"  Neues Passwort: {password}")
        print("  Bitte gleich nach der Anmeldung unter „Mein Konto“ ändern.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
