"""
Premiers pas : 5 objectifs pour guider un nouveau joueur, et une récompense quand ils sont tous faits.

- OBJECTIFS (dans cet ordre), détectés automatiquement à partir d'indicateurs DURABLES (ils ne se décochent pas d'un jour à l'autre) :
  1. ouvrir un premier pack          : compteur à vie « open_packs » (missions.record) ;
  2. ajouter une photo de profil     : compteur à vie « avatar_set » (avatars.set_avatar), ou une photo déjà en place ;
  3. jouer un premier match 1v1      : une ligne dans la table des duels, comme créateur du défi ou comme joueur qui l'a joué
                                       (le défi du club et le tournoi n'y écrivent jamais) ;
  4. écrire un message dans le chat  : compteur à vie « chat_messages » (chat.send_chat), ou un message de joueur encore dans le salon
                                       (jamais une annonce automatique, même si elle porte le nom du joueur) ;
  5. récupérer une mission du jour   : compteur à vie « missions_claimed » (missions.claim, missions seulement : ni la série ni le bonus).
- RÉCOMPENSE : quand les 5 sont faits, le joueur appuie sur « Récupérer » : +20 crédits et 1 pack classique, une seule fois par compte.
- QUI LA VOIT : seulement les comptes créés depuis moins de 14 jours, tant que la récompense n'est pas récupérée.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, String, or_
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Duel, User
from .common import require_admin
from .security import get_current_user
from . import avatars, chat, missions, profiles

router = APIRouter()
ELIGIBLE_DAYS = 14
REWARD = {"credits": 20, "pack": "classique"}
STEPS = [
    ("pack", "Ouvrir ton premier pack"),
    ("photo", "Ajouter une photo de profil"),
    ("duel", "Jouer ton premier match 1v1"),
    ("chat", "Écrire un message dans le chat"),
    ("mission", "Récupérer une mission du jour"),
]


class FirstStepsClaim(Base):
    """La récompense des Premiers pas récupérée par un joueur (une seule fois par compte)."""
    __tablename__ = "first_steps_claims"
    user_id = Column(String, primary_key=True)
    claimed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ResetRequest(BaseModel):
    pseudo: str


def done_steps(db: Session, user: User) -> dict:
    """{objectif: fait ?} pour les 5 objectifs."""
    cnt = lambda k: profiles._counter(db, user.id, k)
    return {
        "pack": cnt("open_packs") > 0,
        "photo": cnt("avatar_set") > 0 or db.query(avatars.UserAvatar).filter_by(user_id=user.id).first() is not None,
        "duel": db.query(Duel).filter(or_(Duel.challenger_id == user.id, Duel.defender_id == user.id)).first() is not None,
        "chat": cnt("chat_messages") > 0 or db.query(chat.ChatMessage).filter_by(user_id=user.id, kind="user").first() is not None,
        "mission": cnt("missions_claimed") > 0,
    }


def eligible(user: User, now: datetime = None) -> bool:
    """Compte créé depuis moins de 14 jours (les comptes plus anciens ne voient jamais les Premiers pas)."""
    now = now or datetime.utcnow()
    return user.created_at is not None and now - user.created_at < timedelta(days=ELIGIBLE_DAYS)


def state(db: Session, user: User) -> dict:
    if not eligible(user) or db.get(FirstStepsClaim, user.id) is not None:
        return {"visible": False}
    done = done_steps(db, user)
    n = sum(1 for k, _ in STEPS if done[k])
    return {"visible": True, "steps": [{"id": k, "label": label, "done": done[k]} for k, label in STEPS], "done": n, "total": len(STEPS),
            "reward": dict(REWARD), "claimable": n == len(STEPS),
            "ends_at": (user.created_at + timedelta(days=ELIGIBLE_DAYS)).isoformat()}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(FirstStepsClaim).filter_by(user_id=user_id).delete()


@router.get("/first-steps")
def get_first_steps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Les 5 objectifs des Premiers pas et leur état, ou {"visible": false} si le compte n'y a pas (ou plus) droit."""
    return state(db, user)


@router.post("/first-steps/claim")
def claim(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """+20 crédits et 1 pack classique quand les 5 objectifs sont faits ; une seule fois par compte."""
    if db.get(FirstStepsClaim, user.id) is not None:
        raise HTTPException(status_code=400, detail="Tu as déjà récupéré la récompense des Premiers pas")
    if not eligible(user):
        raise HTTPException(status_code=400, detail="Les Premiers pas sont réservés aux comptes créés depuis moins de %d jours" % ELIGIBLE_DAYS)
    done = done_steps(db, user)
    left = [label for k, label in STEPS if not done[k]]
    if left:
        raise HTTPException(status_code=400, detail="Il te reste %d objectif%s : %s" % (len(left), "s" if len(left) > 1 else "", ", ".join(l.lower() for l in left)))
    missions._grant(user, REWARD)
    db.add(FirstStepsClaim(user_id=user.id, claimed_at=datetime.utcnow()))
    db.commit()
    return {"status": "ok", "credits_gained": REWARD["credits"], "pack": REWARD["pack"], "credits": user.credits}


@router.post("/admin/first-steps-reset", dependencies=[Depends(require_admin)])
def admin_reset(payload: ResetRequest, db: Session = Depends(get_db)):
    """Efface la récupération des Premiers pas d'un joueur (pour tester). Les objectifs restent faits ; un compte de plus de 14 jours reste invisible."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    n = db.query(FirstStepsClaim).filter_by(user_id=user.id).delete()
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "recuperation_effacee": bool(n), "compte_eligible": eligible(user)}
