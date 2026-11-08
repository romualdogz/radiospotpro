"""Konten von der Kommandozeile verwalten (z. B. auf dem Server per SSH).

    python -m studio.cli invite kollege@example.com --role pro
    python -m studio.cli create-user ron@onaircraft.net --role admin
    python -m studio.cli set-password ron@onaircraft.net
    python -m studio.cli list
"""
import argparse
import getpass
import sys

from .accounts import AccountError, create_invitation, create_user, normalize_email, set_password
from .config import settings
from .database import SessionLocal, init_db
from .models import ROLES, StudioUser


def _ask_password() -> str:
    pw = getpass.getpass("Passwort: ")
    if pw != getpass.getpass("Passwort wiederholen: "):
        raise AccountError("Die Passwörter stimmen nicht überein.")
    return pw


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m studio.cli", description="Radiospot-Studio: Konten verwalten")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("invite", "create-user"):
        s = sub.add_parser(name)
        s.add_argument("email")
        s.add_argument("--role", choices=list(ROLES), default="pro")
    sub.add_parser("set-password").add_argument("email")
    sub.add_parser("list")
    args = p.parse_args(argv)

    init_db()
    with SessionLocal() as db:
        try:
            if args.cmd == "invite":
                inv, token = create_invitation(db, None, args.email, args.role)
                base = settings.public_url or "http://127.0.0.1:8001"
                print(f"Einladung für {inv.email} ({ROLES[inv.role]}), gültig bis {inv.expires_at:%d.%m.%Y %H:%M} UTC:")
                print(f"{base}/invite/{token}")
            elif args.cmd == "create-user":
                user = create_user(db, args.email, _ask_password(), args.role)
                print(f"Konto {user.email} ({ROLES[user.role]}) angelegt.")
            elif args.cmd == "set-password":
                user = db.query(StudioUser).filter_by(email=normalize_email(args.email)).first()
                if user is None:
                    raise AccountError("Kein Konto mit dieser E-Mail-Adresse.")
                set_password(db, user, _ask_password())
                print("Passwort geändert, alle Sessions abgemeldet.")
            else:
                for u in db.query(StudioUser).order_by(StudioUser.email):
                    print(f"{u.email:40} {ROLES.get(u.role, u.role):15} {'aktiv' if u.active else 'gesperrt'}")
        except AccountError as e:
            print(f"Fehler: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
