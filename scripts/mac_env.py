"""Hilfsprogramm für install-mac.command: .env anlegen bzw. ergänzen, Werte lesen und setzen.

  python scripts/mac_env.py ensure          .env aus .env.example anlegen oder fehlende Einträge ergänzen
  python scripts/mac_env.py get KEY         Wert ausgeben (leer, wenn nicht gesetzt)
  python scripts/mac_env.py set KEY=WERT …  Werte setzen (Kommentare und Reihenfolge bleiben erhalten)

Bestehende Werte werden nie überschrieben – außer dem unsicheren Platzhalter-SECRET_KEY.
"""
from datetime import date
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parent.parent
ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"
_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_WEAK_SECRETS = {"", "change-me", "dev-secret-change-me"}


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _values(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines:
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _write(lines: list[str]) -> None:
    ENV.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    ENV.chmod(0o600)  # enthält Passwörter und API-Keys


def set_values(pairs: dict[str, str]) -> None:
    lines = _read(ENV)
    pending = dict(pairs)
    for i, line in enumerate(lines):
        m = _LINE.match(line)
        if m and m.group(1) in pending:
            lines[i] = f"{m.group(1)}={pending.pop(m.group(1))}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    _write(lines)


def ensure() -> str:
    """Gibt "created" oder "updated:<n>" zurück (n = ergänzte Einträge)."""
    example = _read(EXAMPLE)
    if not ENV.exists():
        lines = []
        for line in example:
            m = _LINE.match(line)
            if m and m.group(1) == "SECRET_KEY":
                line = f"SECRET_KEY={secrets.token_urlsafe(48)}"
            elif m and m.group(1) == "ADMIN_PASSWORD":
                line = f"ADMIN_PASSWORD={secrets.token_urlsafe(12)}"
            elif m and m.group(1) == "CORS_ORIGINS":
                line = "CORS_ORIGINS="
            lines.append(line)
        _write(lines)
        return "created"

    lines = _read(ENV)
    current = _values(lines)
    missing, block, comments = [], [], []
    for line in example:  # fehlende Einträge samt der Kommentare darüber übernehmen
        m = _LINE.match(line)
        if not m:
            comments.append(line)
            continue
        if m.group(1) not in current:
            block += comments + [line]
            missing.append(m.group(1))
        comments = []
    if block:
        lines += ["", f"# --- ergänzt vom Installer am {date.today():%d.%m.%Y} ---", *block]
        _write(lines)
    if current.get("SECRET_KEY", "") in _WEAK_SECRETS:
        set_values({"SECRET_KEY": secrets.token_urlsafe(48)})
    else:
        ENV.chmod(0o600)
    return f"updated:{len(missing)}"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "ensure":
        print(ensure())
    elif cmd == "get" and len(args) == 1:
        print(_values(_read(ENV)).get(args[0], ""))
    elif cmd == "set" and args:
        set_values(dict(a.split("=", 1) for a in args))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
