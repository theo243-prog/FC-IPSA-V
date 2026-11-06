"""
Notifications dans le site (encadré « 🔔 Notifications » en haut de la page) : tout ce qui concerne personnellement un joueur.

Chaque message envoyé à UN joueur par push.enqueue (défi relevé, défi privé reçu, carte vendue, enchère dépassée / gagnée / terminée,
offre d'achat acceptée, échange proposé ou accepté, pronostic réglé, tournoi, parrainage, podium de saison…) est aussi rangé ici,
même si le joueur n'a pas activé les notifications de son téléphone. Les rappels « pack gratuit prêt » et les annonces envoyées à
tout le monde (nouvelles cartes, messages de l'administration) n'y vont pas.
On garde au plus KEEP messages par joueur.
"""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .security import get_current_user

router = APIRouter()
KEEP = 60
SKIP_KINDS = {"packs"}                    # rappels de packs prêts : déjà visibles dans l'onglet Packs


class UserNotice(Base):
    __tablename__ = "user_notices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    url = Column(String, nullable=True)                   # ex. /#marche : l'onglet à ouvrir
    read = Column(Integer, nullable=False, default=0)


def add(db: Session, user_id: str, kind: str, title: str, body: str, url: str = None) -> None:
    """Range une notification pour un joueur (sans commit). Ne lève jamais d'exception."""
    if kind in SKIP_KINDS or not user_id:
        return
    try:
        db.add(UserNotice(user_id=user_id, title=(title or "")[:120], body=(body or "")[:300], url=url))
    except Exception:
        pass


def unread_count(db: Session, user_id: str) -> int:
    return db.query(UserNotice).filter_by(user_id=user_id, read=0).count()


def _prune(db: Session, user_id: str) -> None:
    old = db.query(UserNotice.id).filter_by(user_id=user_id).order_by(UserNotice.id.desc()).offset(KEEP).all()
    if old:
        db.query(UserNotice).filter(UserNotice.id.in_([i for (i,) in old])).delete(synchronize_session=False)


@router.get("/notifications")
def my_notices(limit: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    limit = max(1, min(int(limit), KEEP))
    rows = db.query(UserNotice).filter_by(user_id=user.id).order_by(UserNotice.id.desc()).limit(limit).all()
    return {"unread": unread_count(db, user.id),
            "items": [{"id": r.id, "title": r.title, "body": r.body, "url": r.url, "read": bool(r.read), "at": r.created_at.isoformat()} for r in rows]}


class ReadRequest(BaseModel):
    ids: list[int] = []                   # vide : toutes


@router.post("/notifications/read")
def mark_read(payload: ReadRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(UserNotice).filter_by(user_id=user.id, read=0)
    if payload.ids:
        q = q.filter(UserNotice.id.in_(payload.ids))
    q.update({"read": 1}, synchronize_session=False)
    _prune(db, user.id)
    db.commit()
    return {"status": "ok", "unread": unread_count(db, user.id)}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(UserNotice).filter_by(user_id=user_id).delete()
