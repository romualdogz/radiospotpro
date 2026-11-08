"""Zwei-Faktor-Anmeldung nach RFC 6238 (TOTP, 30 s, 6 Ziffern, SHA-1) – kompatibel mit
Google Authenticator, Microsoft Authenticator, 1Password, Bitwarden usw."""
import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote

STEP, DIGITS, WINDOW = 30, 6, 1  # ±1 Zeitfenster Toleranz für ungenaue Uhren


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def verify(secret: str, code: str, last_step: int | None = None, now: float | None = None) -> int | None:
    """Gültiger Code → verwendetes Zeitfenster (zum Speichern gegen Wiederverwendung), sonst None."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(secret: str, account: str, issuer: str = "Radiospot-Studio") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def qr_svg_data_uri(text: str) -> str:
    """QR-Code als SVG-Data-URI (erlaubt durch die CSP: img-src data:)."""
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathFillImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()
