"""Rabatt-Glücksrad im Konfigurator – einstellbar unter Admin → Preise → Glücksrad.

Der Server entscheidet, wo das Rad stehen bleibt (gewichteter Zufall), und gibt einen Gewinn als
signiertes Token aus. Der Konfigurator schickt das Token mit der Preisberechnung mit; ungültige,
abgelaufene oder manipulierte Tokens werden ignoriert. Gegen „so lange drehen, bis es passt“:
pro IP-Adresse gilt 24 Stunden lang dasselbe Ergebnis. Die IP-Adresse liegt dafür nur im
Arbeitsspeicher (nicht in der Datenbank, nicht im Log) und ist nach einem Neustart weg.
"""
import json
import secrets
import time
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import settings
from .models import Discount, DiscountKind, DiscountScope, Setting

DEFAULT_SEGMENTS = [  # Bezeichnung, Rabatt in %, Gewichtung (relative Häufigkeit)
    {"label": "3 %", "percent": 3, "weight": 30},
    {"label": "Leider nein", "percent": 0, "weight": 20},
    {"label": "5 %", "percent": 5, "weight": 25},
    {"label": "Nächstes Mal!", "percent": 0, "weight": 10},
    {"label": "7 %", "percent": 7, "weight": 10},
    {"label": "10 %", "percent": 10, "weight": 5},
]
# Anzeige: eingebettet im letzten Schritt oder als Pop-up beim Öffnen eines Schritts
MODES = {"inline": "Eingebettet im letzten Schritt („Anfrage“)", "popup": "Als Pop-up"}
STYLES = {"wheel": "Glücksrad (Drehrad mit Zeiger)", "radio": "Analog-Radio (Sendersuchknopf drehen)",
          "slot": "Spielautomat (Hebel ziehen, drei Walzen)"}
POPUP_STEPS = {"0": "beim Start (Schritt 1)", "3": "bei „Buchung“ (Schritt 4)", "4": "bei „Anfrage“ (Schritt 5)"}
DEFAULTS = {"wheel_enabled": "0", "wheel_stackable": "0", "wheel_valid_hours": "72",
            "wheel_mode": "inline", "wheel_popup_step": "4", "wheel_style": "wheel",
            "wheel_segments": json.dumps(DEFAULT_SEGMENTS, ensure_ascii=False)}
MAX_SEGMENTS, MIN_SEGMENTS, MAX_PERCENT = 12, 2, 50
REPEAT_WINDOW = 24 * 3600  # so lange bekommt dieselbe IP dasselbe Ergebnis

_signer = URLSafeTimedSerializer(settings.secret_key, salt="discount-wheel")
_rng = secrets.SystemRandom()
_recent: dict[str, tuple[float, dict]] = {}  # IP → (Zeitpunkt, Ergebnis) – nur im Arbeitsspeicher


@dataclass
class WheelConfig:
    enabled: bool
    stackable: bool
    valid_hours: int
    segments: list[dict]
    mode: str = "inline"
    popup_step: int = 4
    style: str = "wheel"

    @property
    def total_weight(self) -> int:
        return sum(s["weight"] for s in self.segments)

    def chance(self, segment: dict) -> float:
        return segment["weight"] / self.total_weight if self.total_weight else 0

    @property
    def average_percent(self) -> float:
        return sum(self.chance(s) * s["percent"] for s in self.segments)

    @property
    def win_chance(self) -> float:
        return sum(self.chance(s) for s in self.segments if s["percent"] > 0)


def get_config(db: Session) -> WheelConfig:
    stored = {s.key: s.value for s in db.query(Setting).filter(Setting.key.in_(list(DEFAULTS)))}
    v = {**DEFAULTS, **stored}
    try:
        segments = validate_segments(json.loads(v["wheel_segments"]))
    except (ValueError, TypeError):
        segments = DEFAULT_SEGMENTS
    try:
        hours = min(720, max(1, int(v["wheel_valid_hours"])))
    except ValueError:
        hours = 72
    return WheelConfig(enabled=v["wheel_enabled"] == "1", stackable=v["wheel_stackable"] == "1",
                       valid_hours=hours, segments=segments,
                       mode=v["wheel_mode"] if v["wheel_mode"] in MODES else "inline",
                       popup_step=int(v["wheel_popup_step"]) if v["wheel_popup_step"] in POPUP_STEPS else 4,
                       style=v["wheel_style"] if v["wheel_style"] in STYLES else "wheel")


def validate_segments(rows: list) -> list[dict]:
    """Prüft die Felder des Rads; wirft ValueError mit verständlicher Meldung."""
    out = []
    for row in rows:
        label = " ".join(str(row.get("label", "")).split())[:20]
        if not label:
            continue
        try:
            percent = int(str(row.get("percent", 0)).replace(",", ".").split(".")[0] or 0)
            weight = int(str(row.get("weight", 0)).replace(",", ".").split(".")[0] or 0)
        except ValueError as e:
            raise ValueError(f"„{label}“: Rabatt und Gewichtung bitte als ganze Zahlen angeben") from e
        if not 0 <= percent <= MAX_PERCENT:
            raise ValueError(f"„{label}“: Rabatt zwischen 0 und {MAX_PERCENT} %")
        if not 0 <= weight <= 1000:
            raise ValueError(f"„{label}“: Gewichtung zwischen 0 und 1000")
        out.append({"label": label, "percent": percent, "weight": weight})
    if not MIN_SEGMENTS <= len(out) <= MAX_SEGMENTS:
        raise ValueError(f"Das Rad braucht {MIN_SEGMENTS} bis {MAX_SEGMENTS} Felder")
    if not sum(s["weight"] for s in out):
        raise ValueError("Mindestens ein Feld braucht eine Gewichtung über 0")
    return out


def save_config(db: Session, enabled: bool, stackable: bool, valid_hours: int, segments: list,
                mode: str = "inline", popup_step: str = "4", style: str = "wheel") -> None:
    clean = validate_segments(segments)
    values = {"wheel_enabled": "1" if enabled else "0", "wheel_stackable": "1" if stackable else "0",
              "wheel_mode": mode if mode in MODES else "inline",
              "wheel_popup_step": popup_step if popup_step in POPUP_STEPS else "4",
              "wheel_style": style if style in STYLES else "wheel",
              "wheel_valid_hours": str(min(720, max(1, valid_hours))),
              "wheel_segments": json.dumps(clean, ensure_ascii=False)}
    for key, value in values.items():
        db.merge(Setting(key=key, value=value))
    db.commit()


def spin(db: Session, client_id: str) -> dict:
    """Dreht das Rad (oder liefert das Ergebnis der letzten 24 h für diese IP)."""
    cfg = get_config(db)
    if not cfg.enabled:
        raise ValueError("Das Glücksrad ist derzeit nicht aktiv.")
    now = time.time()
    for ip, (ts, _) in list(_recent.items()):  # Alte Einträge vergessen
        if now - ts > REPEAT_WINDOW:
            del _recent[ip]
    if client_id in _recent:
        previous = _recent[client_id][1]
        if previous["index"] < len(cfg.segments) and cfg.segments[previous["index"]]["label"] == previous["label"]:
            return {**previous, "repeat": True}
    pick = _rng.uniform(0, cfg.total_weight)
    index = 0
    for index, seg in enumerate(cfg.segments):
        pick -= seg["weight"]
        if pick < 0 and seg["weight"] > 0:
            break
    seg = cfg.segments[index]
    result = {"index": index, "label": seg["label"], "percent": seg["percent"],
              "token": _signer.dumps({"p": seg["percent"], "n": secrets.token_hex(4)}) if seg["percent"] else None,
              "valid_hours": cfg.valid_hours, "repeat": False}
    _recent[client_id] = (now, result)
    return result


def discount_from_token(db: Session, token: str | None) -> Discount | None:
    """Gültiges Token → Rabatt (nicht gespeichert) für die Preisberechnung, sonst None."""
    if not token:
        return None
    cfg = get_config(db)
    if not cfg.enabled:
        return None
    try:
        data = _signer.loads(token, max_age=cfg.valid_hours * 3600)
        percent = int(data["p"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
    if not 0 < percent <= min(MAX_PERCENT, max(s["percent"] for s in cfg.segments)):
        return None
    return Discount(name=f"Glücksrad-Rabatt {percent} %", description="Gewonnen am Glücksrad",
                    kind=DiscountKind.percent, value=percent * 100, applies_to=DiscountScope.total,
                    min_spots=0, min_amount_cent=0, promo_code=None, station_id=None,
                    valid_from=None, valid_until=None, stackable=cfg.stackable, active=True, sort_order=-1)


def reset_memory() -> None:  # für Tests
    _recent.clear()
