"""Konten von der Kommandozeile verwalten (z. B. auf dem Server per SSH).

    python -m studio.cli invite kollege@example.com --role pro
    python -m studio.cli create-user ron@onaircraft.net --role admin
    python -m studio.cli set-password ron@onaircraft.net
    python -m studio.cli list
    python -m studio.cli import-library ~/SFX/Tueren --library "onaircraft SFX" --category sfx --tags "tür"
"""
import argparse
import getpass
import shutil
import sys
from pathlib import Path

from .accounts import AccountError, create_invitation, create_user, normalize_email, set_password
from .config import settings
from .database import SessionLocal, init_db
from . import storage
from .models import LIBRARY_CATEGORIES, ROLES, Library, StudioUser


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
    imp = sub.add_parser("import-library", help="Ordner mit Audiodateien in eine Bibliothek übernehmen")
    imp.add_argument("folder")
    imp.add_argument("--library", required=True, help="Name der Sammlung (wird angelegt, falls neu)")
    imp.add_argument("--category", choices=list(LIBRARY_CATEGORIES), default="sfx")
    imp.add_argument("--tags", default="")
    imp.add_argument("--license", default="", help="Lizenzhinweis für neue Sammlung bzw. die Dateien")
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
            elif args.cmd == "import-library":
                return _import(db, args)
            else:
                for u in db.query(StudioUser).order_by(StudioUser.email):
                    print(f"{u.email:40} {ROLES.get(u.role, u.role):15} {'aktiv' if u.active else 'gesperrt'}")
        except AccountError as e:
            print(f"Fehler: {e}", file=sys.stderr)
            return 1
    return 0


def _import(db, args) -> int:
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        raise AccountError(f"Ordner nicht gefunden: {folder}")
    lib = db.query(Library).filter_by(name=args.library).first()
    if lib is None:
        lib = Library(name=args.library, license_note=args.license)
        db.add(lib)
        db.commit()
        print(f"Sammlung „{lib.name}“ angelegt (für alle Konten sichtbar).")
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in storage.EXTENSIONS and p.is_file())
    ok = 0
    for path in files:
        tmp = storage.library_dir() / ("import-" + path.name + ".part")
        shutil.copyfile(path, tmp)
        try:
            storage.add_library_item(db, lib.id, path.name, tmp, args.category, args.tags,
                                     args.license if args.license != lib.license_note else "")
            ok += 1
            print(f"  ✓ {path.name}")
        except storage.StorageError as e:
            print(f"  ✗ {path.name}: {e}", file=sys.stderr)
    print(f"{ok} von {len(files)} Dateien übernommen.")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
