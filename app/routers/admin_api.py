"""JSON-Admin-API (CRUD) – geschützt per Admin-Session oder HTTP Basic Auth.

Beträge in Cent, Prozentwerte/Faktoren in Basispunkten (10000 = 100 % bzw. Faktor 1,0).
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import Base, get_db
from ..models import (
    AddOn, Country, CoverageArea, Discount, Package, LanguageStyle, MusicStyle, Occasion, QuoteRequest, SpotLength, Station, TimeSlot, Tonality,
    Voice,
)
from ..schemas import (
    AddOnIn, AddOnOut, CountryIn, CountryOut, DiscountIn, DiscountOut, LanguageStyleIn, LanguageStyleOut, MusicStyleIn, MusicStyleOut,
    CoverageAreaIn, CoverageAreaOut, NamedIn, NamedOut, PackageIn, PackageOut, QuoteRequestOut, TonalityIn, TonalityOut, VoiceIn, VoiceOut, QuoteRequestStatusIn, SettingsIn,
    SpotLengthIn, SpotLengthOut, StationIn, StationOut, TimeSlotIn, TimeSlotOut,
)
from ..security import require_admin_api
from ..settings_store import get_settings, save_settings

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin_api)])


def _crud(path: str, model: type[Base], schema_in: type[BaseModel], schema_out: type[BaseModel], name: str):
    """Registriert Standard-CRUD-Endpunkte für ein Produktmodell."""

    def get_or_404(db: Session, item_id: int):
        obj = db.get(model, item_id)
        if obj is None:
            raise HTTPException(404, f"{name} nicht gefunden")
        return obj

    @router.get(f"/{path}", response_model=list[schema_out], summary=f"{name}: Liste")
    def list_items(db: Session = Depends(get_db)):
        return db.query(model).order_by(model.sort_order, model.id).all()

    @router.post(f"/{path}", response_model=schema_out, status_code=201, summary=f"{name}: anlegen")
    def create_item(data: schema_in, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = model(**data.model_dump())
        db.add(obj)
        db.commit()
        return obj

    @router.get(f"/{path}/{{item_id}}", response_model=schema_out, summary=f"{name}: lesen")
    def get_item(item_id: int, db: Session = Depends(get_db)):
        return get_or_404(db, item_id)

    @router.put(f"/{path}/{{item_id}}", response_model=schema_out, summary=f"{name}: ändern")
    def update_item(item_id: int, data: schema_in, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = get_or_404(db, item_id)
        for key, value in data.model_dump().items():
            setattr(obj, key, value)
        db.commit()
        return obj

    @router.delete(f"/{path}/{{item_id}}", status_code=204, summary=f"{name}: löschen")
    def delete_item(item_id: int, db: Session = Depends(get_db)):
        db.delete(get_or_404(db, item_id))
        db.commit()
        return Response(status_code=204)


_crud("occasions", Occasion, NamedIn, NamedOut, "Anlass")
_crud("tonalities", Tonality, TonalityIn, TonalityOut, "Tonalität")
_crud("language-styles", LanguageStyle, LanguageStyleIn, LanguageStyleOut, "Sprachstil")
_crud("voices", Voice, VoiceIn, VoiceOut, "Stimme")
_crud("music-styles", MusicStyle, MusicStyleIn, MusicStyleOut, "Musikrichtung")
_crud("stations", Station, StationIn, StationOut, "Sender")
_crud("time-slots", TimeSlot, TimeSlotIn, TimeSlotOut, "Zeitschiene")
_crud("spot-lengths", SpotLength, SpotLengthIn, SpotLengthOut, "Spotlänge")
_crud("addons", AddOn, AddOnIn, AddOnOut, "Zusatzleistung")
_crud("discounts", Discount, DiscountIn, DiscountOut, "Rabatt")
_crud("packages", Package, PackageIn, PackageOut, "Komplettpaket")
_crud("coverage-areas", CoverageArea, CoverageAreaIn, CoverageAreaOut, "Sendegebiet")
_crud("countries", Country, CountryIn, CountryOut, "Land")


@router.get("/settings", response_model=SettingsIn, summary="Globale Einstellungen lesen")
def read_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@router.put("/settings", response_model=SettingsIn, summary="Globale Einstellungen ändern")
def update_settings(data: SettingsIn, db: Session = Depends(get_db)):
    save_settings(db, data.model_dump())
    return get_settings(db)


@router.get("/quote-requests", response_model=list[QuoteRequestOut], summary="Angebotsanfragen")
def list_quote_requests(db: Session = Depends(get_db)):
    return db.query(QuoteRequest).order_by(QuoteRequest.created_at.desc()).all()


@router.patch("/quote-requests/{req_id}", response_model=QuoteRequestOut, summary="Anfragestatus ändern")
def update_quote_request(req_id: int, data: QuoteRequestStatusIn, db: Session = Depends(get_db)):
    req = db.get(QuoteRequest, req_id)
    if req is None:
        raise HTTPException(404, "Anfrage nicht gefunden")
    req.status = data.status
    db.commit()
    return req
