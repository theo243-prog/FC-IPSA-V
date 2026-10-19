"""
Parrainage : chaque joueur a un code d'invitation. Un nouveau joueur le saisit à l'inscription (ou dans les 7 premiers jours de son compte) :
le parrain ET le filleul reçoivent chacun un pack ULTRA. Un parrain peut avoir au plus 3 filleuls récompensés.
"""
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .security import get_current_user
from . import chat, push

router = APIRouter()
REFERRAL_PACK = "ultra"              # le pack offert aux deux (ultra = champ ultra_pack_tokens)
MAX_REFERRALS = 3                    # filleuls récompensés par parrain
ELIGIBLE_DAYS = 7                    # on peut saisir un code pendant les 7 premiers jours du compte
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"       # sans O/0/I/1 pour éviter les confusions


class ReferralCode(Base):
    __tablename__ = "referral_codes"
    user_id = Column(String, primary_key=True)
    code = Column(String, nullable=False, unique=True, index=True)


class Referral(Base):
    __tablename__ = "referrals"
    referee_id = Column(String, primary_key=True)
    referrer_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def code_of(db: Session, user: User) -> str:
    row = db.get(ReferralCode, user.id)
    if row is None:
        while True:
            code = "".join(random.choice(ALPHABET) for _ in range(6))
            if not db.query(ReferralCode).filter_by(code=code).first():
                break
        row = ReferralCode(user_id=user.id, code=code); db.add(row); db.commit()
    return row.code


def _eligible(user: User) -> bool:
    return user.created_at is None or (datetime.utcnow() - user.created_at) <= timedelta(days=ELIGIBLE_DAYS)


def apply(db: Session, referee: User, code: str) -> dict:
    """Valide un code pour `referee`. Lève HTTPException si impossible."""
    code = (code or "").strip().upper()
    if db.get(Referral, referee.id):
        raise HTTPException(status_code=400, detail="Tu as déjà utilisé un code d'invitation")
    if not _eligible(referee):
        raise HTTPException(status_code=400, detail="Un code se saisit pendant les %d premiers jours du compte" % ELIGIBLE_DAYS)
    row = db.query(ReferralCode).filter_by(code=code).first()
    referrer = db.get(User, row.user_id) if row else None
    if referrer is None:
        raise HTTPException(status_code=404, detail="Code d'invitation inconnu")
    if referrer.id == referee.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas utiliser ton propre code")
    if db.query(Referral).filter_by(referrer_id=referrer.id).count() >= MAX_REFERRALS:
        raise HTTPException(status_code=400, detail="Ce code a atteint sa limite de %d parrainages" % MAX_REFERRALS)
    from . import game_logic
    field = game_logic.PACK_TYPES[REFERRAL_PACK]["token_field"]
    for u in (referrer, referee):
        setattr(u.pack_state, field, getattr(u.pack_state, field) + 1)
    db.add(Referral(referee_id=referee.id, referrer_id=referrer.id))
    chat.add_event(db, "🤝 %s a rejoint le club grâce à %s : un pack ultra chacun !" % (referee.pseudo, referrer.pseudo), referee)
    db.commit()
    try:
        push.enqueue(db, referrer.id, "social", "Parrainage 🤝", "%s a rejoint le club avec ton code : un pack ultra pour vous deux !" % referee.pseudo, url="/", tag="referral")
    except Exception:
        pass
    return {"ok": True, "referrer": referrer.pseudo}


def try_apply(db: Session, referee: User, code) -> dict:
    """À l'inscription : ne fait jamais échouer la création du compte."""
    if not code or not str(code).strip():
        return None
    try:
        return apply(db, referee, code)
    except HTTPException as e:
        db.rollback()
        return {"ok": False, "message": e.detail}
    except Exception:
        db.rollback()
        return {"ok": False, "message": "Code non pris en compte"}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(ReferralCode).filter_by(user_id=user_id).delete()
    db.query(Referral).filter((Referral.referee_id == user_id) | (Referral.referrer_id == user_id)).delete(synchronize_session=False)


class UseCode(BaseModel):
    code: str = Field(min_length=3, max_length=12)


@router.get("/referral")
def my_referral(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code = code_of(db, user); used = db.get(Referral, user.id)
    referees = [db.get(User, r.referee_id) for r in db.query(Referral).filter_by(referrer_id=user.id).order_by(Referral.created_at).all()]
    return {"code": code, "count": len(referees), "max": MAX_REFERRALS, "referees": [u.pseudo for u in referees if u], "eligible_days": ELIGIBLE_DAYS,
            "can_use": used is None and _eligible(user), "used_with": (db.get(User, used.referrer_id).pseudo if used and db.get(User, used.referrer_id) else None), "pack": REFERRAL_PACK}


@router.post("/referral/use")
def use_code(payload: UseCode, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return apply(db, user, payload.code)
