"""JSON-API des Studios. Der ganze Router hängt an `api_user` – keine Route ist ohne Login erreichbar.
Alle Daten werden nach Besitzer gefiltert: fremde Projekte, Dateien und Exporte sind „nicht gefunden“."""
import re
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from . import ai, storage
from .config import settings
from .database import get_db
from .models import ROLES, TRACKS, Asset, Export, Project, StudioUser, StudioVoice, now
from .projects import ProjectData, check_assets, empty_project
from .security import api_admin, api_user

router = APIRouter(prefix="/api", dependencies=[Depends(api_user)], tags=["studio"])
_PRIVATE_CACHE = {"Cache-Control": "private, max-age=3600"}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _owned(db: Session, model, obj_id: int, user: StudioUser):
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(404, "Nicht gefunden")
    return obj


def _validation_message(e: ValidationError) -> str:
    err = e.errors()[0]
    where = ".".join(str(p) for p in err.get("loc", ()))
    return f"Ungültiges Projekt ({where}): {err.get('msg', '')}".replace("Value error, ", "")


# --------------------------------------------------------------------------- Konto

def _me(db: Session, u: StudioUser) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "role_label": ROLES.get(u.role, u.role),
            "quota_mb": u.quota_mb, "used_bytes": storage.used_bytes(db, u.id), "export_limit": u.export_limit,
            "exports_used": db.query(Export).filter_by(user_id=u.id).count(), "libraries": u.libraries or [],
            "limits": {"max_upload_mb": settings.max_upload_mb, "max_length_s": settings.max_length_s},
            "tracks": TRACKS}


@router.get("/me")
def me(user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    return _me(db, user)


class MeUpdate(BaseModel):
    name: str = Field(max_length=120)


@router.patch("/me")
def update_me(data: MeUpdate, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    user.name = data.name.strip()
    db.commit()
    return _me(db, user)


@router.get("/admin/users")
def list_users(_: StudioUser = Depends(api_admin), db: Session = Depends(get_db)):
    return [{"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
             "quota_mb": u.quota_mb, "export_limit": u.export_limit}
            for u in db.query(StudioUser).order_by(StudioUser.email)]


# --------------------------------------------------------------------------- Dateien

def _asset(a: Asset) -> dict:
    return {"id": a.id, "name": a.name, "duration": a.duration_s, "size_bytes": a.size_bytes,
            "media_type": a.media_type, "origin": a.origin, "created_at": _iso(a.created_at)}


@router.get("/assets")
def list_assets(user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    return [_asset(a) for a in db.query(Asset).filter_by(user_id=user.id).order_by(Asset.created_at.desc())]


@router.post("/assets", status_code=201)
async def upload_asset(request: Request, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    """Upload als Rohdaten (Body = Datei, Name im Header X-Filename). Wird gestreamt auf die Platte
    geschrieben und bricht beim Größenlimit ab; Prüfen und Dekodieren laufen außerhalb der Event-Loop."""
    filename = unquote(request.headers.get("X-Filename", ""))
    limit = settings.max_upload_mb * 1024 * 1024
    too_big = HTTPException(413, f"Die Datei ist größer als {settings.max_upload_mb} MB.")
    try:
        storage.check_upload_name(filename)
        storage.check_quota(db, user, 0)
    except storage.StorageError as e:
        raise HTTPException(e.status, str(e)) from e
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_big
    tmp, size = storage.temp_upload_path(user.id), 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise too_big
                f.write(chunk)
        asset = await run_in_threadpool(storage.save_upload, db, user, filename, tmp)
    except storage.StorageError as e:
        raise HTTPException(e.status, str(e)) from e
    finally:
        tmp.unlink(missing_ok=True)
    return _asset(asset)


@router.get("/assets/{asset_id}/audio")
def asset_audio(asset_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    a = _owned(db, Asset, asset_id, user)
    return FileResponse(storage.asset_path(a), media_type=a.media_type, headers=_PRIVATE_CACHE)


@router.get("/assets/{asset_id}/peaks")
def asset_peaks(asset_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    a = _owned(db, Asset, asset_id, user)
    return FileResponse(storage.peaks_path(a), media_type="application/json", headers=_PRIVATE_CACHE)


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    a = _owned(db, Asset, asset_id, user)
    used_in = [p.name for p in db.query(Project).filter_by(user_id=user.id)
               if any(c.get("asset_id") == a.id for c in (p.data or {}).get("clips", []))]
    if used_in:
        raise HTTPException(409, "Die Datei wird noch verwendet in: " + ", ".join(used_in))
    storage.delete_asset(db, a)


# --------------------------------------------------------------------------- Projekte

class ProjectCreate(BaseModel):
    name: str = Field("Neues Projekt", min_length=1, max_length=120)
    length: float = Field(30, ge=1)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    data: dict


def _project(p: Project, full: bool = True) -> dict:
    d = {"id": p.id, "name": p.name, "length": (p.data or {}).get("length", 30), "updated_at": _iso(p.updated_at)}
    if full:
        d["data"] = p.data
    return d


@router.get("/projects")
def list_projects(user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    return [_project(p, False) for p in db.query(Project).filter_by(user_id=user.id).order_by(Project.updated_at.desc())]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    try:
        data = empty_project(body.length)
    except ValidationError as e:
        raise HTTPException(422, _validation_message(e)) from e
    p = Project(user_id=user.id, name=body.name.strip(), data=data)
    db.add(p)
    db.commit()
    return _project(p)


@router.get("/projects/{project_id}")
def get_project(project_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    return _project(_owned(db, Project, project_id, user))


@router.put("/projects/{project_id}")
def save_project(project_id: int, body: ProjectUpdate, user: StudioUser = Depends(api_user),
                 db: Session = Depends(get_db)):
    p = _owned(db, Project, project_id, user)
    try:
        data = ProjectData.model_validate(body.data)
        check_assets(db, user.id, data)
    except ValidationError as e:
        raise HTTPException(422, _validation_message(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    p.name, p.data, p.updated_at = body.name.strip(), data.model_dump(), now()
    db.commit()
    return _project(p, False)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, Project, project_id, user))
    db.commit()


# --------------------------------------------------------------------------- Exporte

class ExportRequest(BaseModel):
    loudness: float | None = Field(None, ge=-30, le=-6)  # None = Pegel lassen, nur Spitzen begrenzen


def _export(e: Export) -> dict:
    return {"id": e.id, "project_id": e.project_id, "name": e.name, "status": e.status, "error": e.error,
            "loudness": e.loudness, "measured_lufs": e.measured_lufs, "measured_peak": e.measured_peak,
            "size_bytes": e.size_bytes, "created_at": _iso(e.created_at), "finished_at": _iso(e.finished_at)}


@router.post("/projects/{project_id}/exports", status_code=202)
def start_export(project_id: int, body: ExportRequest, user: StudioUser = Depends(api_user),
                 db: Session = Depends(get_db)):
    p = _owned(db, Project, project_id, user)
    data = ProjectData.model_validate(p.data)
    if not data.clips:
        raise HTTPException(400, "Das Projekt ist leer – zuerst Dateien auf die Spuren ziehen.")
    if user.export_limit is not None and db.query(Export).filter_by(user_id=user.id).count() >= user.export_limit:
        raise HTTPException(403, f"Export-Kontingent ausgeschöpft ({user.export_limit}). Bitte onaircraft kontaktieren.")
    pending = db.query(Export).filter(Export.user_id == user.id, Export.status.in_(("queued", "running"))).count()
    if pending >= settings.max_queued_per_user:
        raise HTTPException(429, "Es laufen bereits Exporte – bitte warten, bis sie fertig sind.")
    try:
        storage.check_quota(db, user, int(data.length * 48_000 * 2 * 3))  # Größe der WAV-Datei
    except storage.StorageError as e:
        raise HTTPException(e.status, str(e)) from e
    try:
        check_assets(db, user.id, data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    job = Export(user_id=user.id, project_id=p.id, name=p.name, snapshot=data.model_dump(), loudness=body.loudness)
    db.add(job)
    db.commit()
    return _export(job)


@router.get("/projects/{project_id}/exports")
def project_exports(project_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    _owned(db, Project, project_id, user)
    q = db.query(Export).filter_by(user_id=user.id, project_id=project_id).order_by(Export.id.desc()).limit(20)
    return [_export(e) for e in q]


@router.get("/exports/{export_id}")
def get_export(export_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    return _export(_owned(db, Export, export_id, user))


@router.get("/exports/{export_id}/download")
def download_export(export_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    e = _owned(db, Export, export_id, user)
    if e.status != "done":
        raise HTTPException(409, "Der Export ist nicht verfügbar.")
    safe = re.sub(r"[^\w\- ]+", "", e.name).strip().replace(" ", "_") or "spot"
    return FileResponse(storage.export_path(e), media_type="audio/wav",
                        filename=f"{safe}_{e.created_at:%Y%m%d-%H%M}.wav")


@router.delete("/exports/{export_id}", status_code=204)
def delete_export(export_id: int, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    e = _owned(db, Export, export_id, user)
    if e.status in ("queued", "running"):
        raise HTTPException(409, "Der Export läuft noch.")
    storage.delete_export_file(e)
    e.status, e.size_bytes = "expired", 0  # Eintrag bleibt für die Exportzählung
    db.commit()


# --------------------------------------------------------------------------- KI: Text & Stimme

@router.get("/ai")
def ai_status(user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    voices = db.query(StudioVoice).filter_by(active=True).order_by(StudioVoice.sort, StudioVoice.name)
    return {"text_enabled": ai.text_enabled(), "voice_enabled": ai.voice_enabled(),
            "tags_supported": ai.tags_supported(), "max_chars": ai.MAX_CHARS, "tonalities": ai.TONALITIES,
            "voices": [{"id": v.id, "name": v.name, "description": v.description} for v in voices],
            "usage": ai.usage(db, user.id),
            "limits": {"scripts": user.scripts_month, "voice_chars": user.tts_chars_month}}


class ScriptRequest(BaseModel):
    occasion: str = Field(min_length=1, max_length=200)
    seconds: int = Field(30, ge=5, le=120)
    tonality: str = Field("freundlich", max_length=40)
    firma: str = Field("", max_length=200)
    botschaft: str = Field(min_length=1, max_length=1500)
    cta: str = Field("", max_length=300)
    audio_tags: bool = True


@router.post("/ai/script")
async def ai_script(body: ScriptRequest, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    try:
        found = await ai.scripts(db, user, **body.model_dump())
    except ai.AiError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"scripts": found, "usage": ai.usage(db, user.id)}


class VoiceRequest(BaseModel):
    voice_id: int
    text: str = Field(min_length=1, max_length=5000)


@router.post("/ai/voice", status_code=201)
async def ai_voice(body: VoiceRequest, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    """Text einsprechen lassen → neue Datei in der Dateiliste (wie ein Upload, zählt zum Speicher)."""
    voice = db.get(StudioVoice, body.voice_id)
    if voice is None or not voice.active:
        raise HTTPException(404, "Diese Stimme ist nicht verfügbar.")
    try:
        storage.check_quota(db, user, 0)
        mp3 = await ai.speak(db, user, voice, body.text)
        tmp = storage.temp_upload_path(user.id)
        tmp.write_bytes(mp3)
        asset = await run_in_threadpool(storage.save_upload, db, user, ai.asset_name(voice, body.text), tmp, "ai")
    except ai.AiError as e:
        raise HTTPException(e.status, str(e)) from e
    except storage.StorageError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"asset": _asset(asset), "usage": ai.usage(db, user.id)}
