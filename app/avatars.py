"""
Photos de profil.

Le site réduit la photo choisie à 256 × 256 pixels (JPEG) AVANT de l'envoyer : le serveur n'accepte donc que de petites images JPEG
(150 Ko au plus). Elles sont gardées dans la base de données (le disque de Railway est effacé à chaque déploiement) et servies à
tout le monde à l'adresse /users/<pseudo>/avatar. Le joueur peut la changer ou la supprimer ; l'administrateur peut la retirer.
"""
import base64
import binascii
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, LargeBinary, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .common import require_admin
from .security import get_current_user

router = APIRouter()
MAX_BYTES = 150_000


class UserAvatar(Base):
    """La photo de profil d'un joueur (sans clé étrangère : on nettoie à la main à la suppression d'un compte)."""
    __tablename__ = "user_avatars"
    user_id = Column(String, primary_key=True)
    data = Column(LargeBinary, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AvatarUpload(BaseModel):
    image: str = Field(max_length=260_000)       # « data:image/jpeg;base64,… » ou le base64 seul


class RemoveAvatarRequest(BaseModel):
    pseudo: str


def stamps(db: Session) -> dict:
    """{joueur: version de sa photo} (un nombre qui change à chaque nouvelle photo : sert à rafraîchir le cache du navigateur)."""
    return {uid: int(t.timestamp()) for uid, t in db.query(UserAvatar.user_id, UserAvatar.updated_at).all() if t}


def user_stamp(db: Session, user_id: str):
    row = db.query(UserAvatar.updated_at).filter_by(user_id=user_id).first()
    return int(row[0].timestamp()) if row and row[0] else None


def _decode(image: str) -> bytes:
    raw = image.split(",", 1)[1] if image.startswith("data:") and "," in image else image
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Image illisible")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image trop lourde (%d Ko maximum)" % (MAX_BYTES // 1000))
    if not (data.startswith(b"\xff\xd8\xff") and data.rstrip(b"\x00").endswith(b"\xff\xd9")):
        raise HTTPException(status_code=400, detail="Image JPEG seulement")
    return data


@router.post("/me/avatar")
def set_avatar(payload: AvatarUpload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = _decode(payload.image)
    row = db.query(UserAvatar).filter_by(user_id=user.id).first()
    now = datetime.utcnow()
    if row is None:
        db.add(UserAvatar(user_id=user.id, data=data, updated_at=now))
    else:
        row.data, row.updated_at = data, now
    from . import profiles
    profiles.bump(db, user, "avatar_set")                    # compteur à vie (Premiers pas : il reste coché même si la photo est retirée ensuite)
    db.commit()
    return {"status": "ok", "avatar": user_stamp(db, user.id)}


@router.delete("/me/avatar")
def delete_avatar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(UserAvatar).filter_by(user_id=user.id).delete()
    db.commit()
    return {"status": "ok"}


@router.get("/users/{pseudo}/avatar")
def get_avatar(pseudo: str, request: Request, db: Session = Depends(get_db)):
    """La photo d'un joueur (publique, comme son profil). 404 s'il n'en a pas."""
    user = db.query(User).filter_by(pseudo=pseudo).first()
    row = db.query(UserAvatar).filter_by(user_id=user.id).first() if user else None
    if row is None:
        raise HTTPException(status_code=404, detail="Pas de photo")
    etag = 'W/"%d-%d"' % (int(row.updated_at.timestamp()), len(row.data))
    headers = {"ETag": etag, "Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=bytes(row.data), media_type="image/jpeg", headers=headers)


@router.post("/admin/remove-avatar", dependencies=[Depends(require_admin)])
def admin_remove_avatar(payload: RemoveAvatarRequest, db: Session = Depends(get_db)):
    """Retire la photo de profil d'un joueur (photo inappropriée)."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    n = db.query(UserAvatar).filter_by(user_id=user.id).delete()
    db.commit()
    if not n:
        raise HTTPException(status_code=404, detail="Ce joueur n'a pas de photo de profil")
    return {"status": "ok", "pseudo": user.pseudo}
