"""Zugriff auf die im Admin pflegbaren globalen Einstellungen."""
from sqlalchemy.orm import Session

from .models import Setting

DEFAULTS: dict[str, str] = {
    "company_info": "onaircraft sound so(u)lutions · Wien",  # Fußzeile im PDF
    "watermark_text": "Hörprobe von onaircraft",  # wird in jede Kunden-Hörprobe gesprochen
    "watermark_interval_s": "7",                   # Abstand der Wasserzeichen in Sekunden
    "master_lufs": "-8",          # Ziel-Lautheit des fertigen Spots (LUFS, integriert)
    "master_ceiling_dbtp": "-1",  # True-Peak-Grenze (dBTP)
    "min_order_cent": "0",   # Mindestbestellwert (netto)
    "studio_price_cent": "34900",  # Studiospot mit echtem Sprecher (netto)
    "ad_tax_rate_bp": "500",  # 5 % Werbeabgabe auf die Sendezeit (0 = keine)
    "ad_tax_in_vat_base": "1",  # Werbeabgabe unterliegt der Umsatzsteuer
    "currency": "EUR",
    "individual_booking": "1",  # „Individuell“ (Buchung nach Sekunden) im Konfigurator anbieten
}


def get_settings(db: Session) -> dict:
    stored = {s.key: s.value for s in db.query(Setting).all()}
    merged = {**DEFAULTS, **stored}
    return {
        "company_info": merged["company_info"],
        "watermark_text": merged["watermark_text"],
        "watermark_interval_s": int(merged["watermark_interval_s"]),
        "master_lufs": float(merged["master_lufs"]),
        "master_ceiling_dbtp": float(merged["master_ceiling_dbtp"]),
        "min_order_cent": int(merged["min_order_cent"]),
        "studio_price_cent": int(merged["studio_price_cent"]),
        "ad_tax_rate_bp": int(merged["ad_tax_rate_bp"]),
        "ad_tax_in_vat_base": merged["ad_tax_in_vat_base"] in ("1", "True", "true"),
        "currency": merged["currency"],
        "individual_booking": merged["individual_booking"] in ("1", "True", "true"),
    }


def save_settings(db: Session, values: dict) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        if isinstance(value, bool):
            value = int(value)
        db.merge(Setting(key=key, value=str(value)))
    db.commit()
