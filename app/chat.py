"""
Chat général + fil d'activité du club.

Les joueurs écrivent dans un salon commun ; le serveur y ajoute lui-même des annonces (« X a ouvert une légendaire », « Y a gagné la
saison »…). Le site relit le salon toutes les quelques secondes quand l'onglet est ouvert. Garde-fous : 300 caractères au plus, une
cadence limitée (1 message / 1,5 s et 15 / minute), et l'administrateur peut supprimer un message ou rendre un joueur muet.
"""
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .common import require_admin
from .security import get_current_user
from . import avatars, cosmetics

router = APIRouter()
MAX_LEN, KEEP = 300, 1500


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, default=datetime.utcnow, index=True)
    user_id = Column(String, nullable=True, index=True)       # None : annonce du club
    pseudo = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="user")     # "user" ou "event"
    text = Column(Text, nullable=False)


class ChatMute(Base):
    __tablename__ = "chat_mutes"
    user_id = Column(String, primary_key=True)
    until = Column(DateTime, nullable=False)


class SendRequest(BaseModel):
    text: str = Field(max_length=2000)


class AdminChatDelete(BaseModel):
    id: int


class AdminChatMute(BaseModel):
    pseudo: str
    hours: int = Field(ge=1, le=720)


class AdminChatUnmute(BaseModel):
    pseudo: str


def add_event(db: Session, text: str, user: User = None) -> None:
    """Ajoute une annonce SANS valider la transaction (elle partira avec le commit de l'appelant)."""
    try:
        db.add(ChatMessage(user_id=user.id if user else None, pseudo=user.pseudo if user else "FC IPSA V", kind="event", text=text[:MAX_LEN]))
    except Exception:
        pass


def post_event(db: Session, text: str, user: User = None) -> None:
    """Ajoute une annonce et la valide tout de suite. Ne lève jamais d'exception."""
    try:
        add_event(db, text, user); db.commit()
    except Exception:
        db.rollback()


def last_id(db: Session) -> int:
    return int(db.query(func.coalesce(func.max(ChatMessage.id), 0)).scalar() or 0)


def _out(m: ChatMessage, viewer_id: str, av: dict, cos: dict, pdisp: dict = None) -> dict:
    title, frame = cos.get(m.user_id, (None, None)) if m.user_id else (None, None)
    pd = (pdisp or {}).get(m.user_id, {}) if m.user_id else {}
    return {"id": m.id, "at": m.at.isoformat(), "kind": m.kind, "text": m.text, "pseudo": m.pseudo, "user": bool(m.user_id), "mine": bool(m.user_id) and m.user_id == viewer_id,
            "avatar": av.get(m.user_id) if m.user_id else None, "frame": frame, "title": title, "badge": pd.get("badge"), "name_color": pd.get("name_color")}


@router.get("/chat")
def read_chat(after_id: int = 0, limit: int = 60, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Les derniers messages (ou ceux arrivés après `after_id`), du plus ancien au plus récent."""
    limit = max(1, min(int(limit), 200))
    if after_id > 0:
        rows = db.query(ChatMessage).filter(ChatMessage.id > after_id).order_by(ChatMessage.id.asc()).limit(limit).all()
    else:
        rows = list(reversed(db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit).all()))
    from . import battlepass
    av, cos, pdisp = avatars.stamps(db), cosmetics.display_map(db), battlepass.display_map(db)
    mute = db.query(ChatMute).filter_by(user_id=user.id).first()
    muted_until = mute.until.isoformat() if mute and mute.until > datetime.utcnow() else None
    return {"messages": [_out(m, user.id, av, cos, pdisp) for m in rows], "last_id": last_id(db), "muted_until": muted_until}


@router.post("/chat")
def send_chat(payload: SendRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    text = re.sub(r"\s+", " ", payload.text).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message vide")
    if len(text) > MAX_LEN:
        raise HTTPException(status_code=400, detail="Message trop long (%d caractères au plus)" % MAX_LEN)
    now = datetime.utcnow()
    mute = db.query(ChatMute).filter_by(user_id=user.id).first()
    if mute and mute.until > now:
        raise HTTPException(status_code=403, detail="Tu ne peux pas écrire dans le chat pour le moment")
    last = db.query(func.max(ChatMessage.at)).filter(ChatMessage.user_id == user.id, ChatMessage.kind == "user").scalar()
    if last and now - last < timedelta(milliseconds=1500):
        raise HTTPException(status_code=429, detail="Doucement : un message toutes les secondes ou deux")
    recent = db.query(func.count()).select_from(ChatMessage).filter(ChatMessage.user_id == user.id, ChatMessage.kind == "user", ChatMessage.at > now - timedelta(minutes=1)).scalar()
    if recent >= 15:
        raise HTTPException(status_code=429, detail="Trop de messages d'un coup, attends un peu")
    m = ChatMessage(user_id=user.id, pseudo=user.pseudo, kind="user", text=text); db.add(m); db.commit()
    if m.id % 100 == 0:
        db.query(ChatMessage).filter(ChatMessage.id < m.id - KEEP).delete(synchronize_session=False); db.commit()
    from . import battlepass
    return _out(m, user.id, avatars.stamps(db), cosmetics.display_map(db), battlepass.display_map(db))


@router.delete("/chat/{message_id}")
def delete_own_message(message_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(ChatMessage).filter_by(id=message_id, user_id=user.id, kind="user").first()
    if m is None:
        raise HTTPException(status_code=404, detail="Message introuvable (tu ne peux supprimer que les tiens)")
    db.delete(m); db.commit()
    return {"status": "ok"}


@router.post("/admin/chat-delete", dependencies=[Depends(require_admin)])
def admin_chat_delete(payload: AdminChatDelete, db: Session = Depends(get_db)):
    m = db.query(ChatMessage).filter_by(id=payload.id).first()
    if m is None:
        raise HTTPException(status_code=404, detail="Message introuvable")
    label = "%s : %s" % (m.pseudo, m.text[:60])
    db.delete(m); db.commit()
    return {"status": "ok", "deleted": label}


@router.post("/admin/chat-mute", dependencies=[Depends(require_admin)])
def admin_chat_mute(payload: AdminChatMute, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    until = datetime.utcnow() + timedelta(hours=payload.hours)
    row = db.query(ChatMute).filter_by(user_id=user.id).first()
    if row is None:
        db.add(ChatMute(user_id=user.id, until=until))
    else:
        row.until = until
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "muted_until": until.isoformat()}


@router.post("/admin/chat-unmute", dependencies=[Depends(require_admin)])
def admin_chat_unmute(payload: AdminChatUnmute, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    db.query(ChatMute).filter_by(user_id=user.id).delete(); db.commit()
    return {"status": "ok", "pseudo": user.pseudo}
