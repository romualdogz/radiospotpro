"""JSON-API des Studios. Der ganze Router hängt an `api_user` – keine Route ist ohne Login erreichbar."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database import get_db
from .models import ROLES, StudioUser
from .security import api_admin, api_user

router = APIRouter(prefix="/api", dependencies=[Depends(api_user)], tags=["studio"])


def _me(u: StudioUser) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "role_label": ROLES.get(u.role, u.role),
            "quota_mb": u.quota_mb, "export_limit": u.export_limit, "libraries": u.libraries or []}


@router.get("/me")
def me(user: StudioUser = Depends(api_user)):
    return _me(user)


class MeUpdate(BaseModel):
    name: str = Field(max_length=120)


@router.patch("/me")
def update_me(data: MeUpdate, user: StudioUser = Depends(api_user), db: Session = Depends(get_db)):
    user.name = data.name.strip()
    db.commit()
    return _me(user)


@router.get("/admin/users")
def list_users(_: StudioUser = Depends(api_admin), db: Session = Depends(get_db)):
    return [_me(u) | {"active": u.active} for u in db.query(StudioUser).order_by(StudioUser.email)]
