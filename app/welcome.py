"""
Accueil des nouveaux comptes.

- PACK ULTRA OFFERT : les N prochaines créations de compte reçoivent un pack ultra tout de suite (N = 30 au départ). Le nombre
  de packs restants est gardé en base ; tu peux le remettre à 30 (ou autre) depuis la page d'administration pour une nouvelle série.
- POP-UP DE BIENVENUE : seul un compte créé APRÈS cette mise à jour le reçoit (les comptes existants n'ont rien à voir), une seule
  fois : le site dit « c'est vu » au serveur quand le joueur ferme la fenêtre.
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import AppSetting, User
from .common import require_admin
from .profiles import UserCounter
from .security import get_current_user

router = APIRouter()
DEFAULT_GIFTS = int(os.getenv("WELCOME_ULTRA_GIFTS", "30"))      # nombre de packs ultra offerts au départ (30 ; ne sert qu'avant le premier réglage dans l'administration)
KEY_REMAINING = "welcome_ultra_remaining"


class SetWelcomeGiftRequest(BaseModel):
    remaining: int = Field(ge=0, le=1000)          # combien de prochains comptes recevront un pack ultra


def _flag(db: Session, user_id: str, key: str) -> int:
    row = db.query(UserCounter).filter_by(user_id=user_id, key=key).first()
    return int(row.value) if row else 0


def _set_flag(db: Session, user_id: str, key: str, value: int) -> None:
    row = db.query(UserCounter).filter_by(user_id=user_id, key=key).first()
    if row is None:
        db.add(UserCounter(user_id=user_id, key=key, value=value))
    else:
        row.value = value


def remaining(db: Session) -> int:
    row = db.get(AppSetting, KEY_REMAINING)
    return int(row.value) if row is not None else DEFAULT_GIFTS


def take_gift(db: Session) -> bool:
    """Un nouveau compte arrive : vrai s'il reste un pack ultra à offrir (et en retire un). Verrouille la ligne pour que deux
    inscriptions simultanées ne prennent pas le dernier pack toutes les deux."""
    row = db.query(AppSetting).filter_by(key=KEY_REMAINING).with_for_update().first()
    if row is None:
        try:
            with db.begin_nested():
                db.add(AppSetting(key=KEY_REMAINING, value=str(DEFAULT_GIFTS)))
        except IntegrityError:
            pass
        row = db.query(AppSetting).filter_by(key=KEY_REMAINING).with_for_update().first()
    left = int(row.value)
    if left <= 0:
        return False
    row.value = str(left - 1)
    return True


def mark_new_account(db: Session, user: User, gift: bool) -> None:
    """Le compte vient d'être créé : il verra le pop-up de bienvenue (avec ou sans le cadeau)."""
    _set_flag(db, user.id, "welcome_pending", 1)
    _set_flag(db, user.id, "welcome_gift", 1 if gift else 0)


def status(db: Session, user: User):
    """Ce que /me annonce au site : rien (compte déjà accueilli ou ancien), ou le pop-up à montrer."""
    if _flag(db, user.id, "welcome_pending") != 1:
        return None
    return {"gift_ultra": _flag(db, user.id, "welcome_gift") == 1}


@router.post("/welcome/seen")
def welcome_seen(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Le joueur a fermé le pop-up de bienvenue : il ne reviendra plus."""
    _set_flag(db, user.id, "welcome_pending", 0)
    db.commit()
    return {"status": "ok"}


@router.get("/admin/welcome-gift", dependencies=[Depends(require_admin)])
def admin_welcome_gift(db: Session = Depends(get_db)):
    """Packs ultra de bienvenue : combien de prochains comptes en recevront, et combien de comptes en ont déjà reçu un."""
    given = db.query(func.count()).select_from(UserCounter).filter(UserCounter.key == "welcome_gift", UserCounter.value == 1).scalar()
    return {"remaining": remaining(db), "already_given": int(given or 0)}


@router.post("/admin/welcome-gift", dependencies=[Depends(require_admin)])
def admin_set_welcome_gift(payload: SetWelcomeGiftRequest, db: Session = Depends(get_db)):
    """Règle le nombre de PROCHAINS comptes qui recevront un pack ultra de bienvenue (ex. 30 pour une nouvelle série, 0 pour arrêter)."""
    row = db.get(AppSetting, KEY_REMAINING)
    if row is None:
        db.add(AppSetting(key=KEY_REMAINING, value=str(payload.remaining)))
    else:
        row.value = str(payload.remaining)
    db.commit()
    return {"status": "ok", "remaining": payload.remaining}
