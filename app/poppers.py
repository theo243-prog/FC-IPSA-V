"""
Poppers au shop (branche poppers, 27/11/2026, demandé par Théo) : un objet qui remet UNE personne (joueur, fan, Loup, équipement) à 100 % de
forme en 1v1, d'un coup (sa dette de fatigue, fatigue.PersonFatigue, est effacée). Comme la forme est partagée par toutes les versions d'une
même personne, toutes ses cartes repassent à 100 %.

- Prix fixe PRICE = 250 crédits (sans promotion), au plus UN achat par jour (heure de Paris, compteur du jour « poppers » de
  missions.daily_count). Les crédits sont détruits (dépense volontaire, jamais de taxe).
- L'objet acheté va dans la réserve du joueur (compteur à vie « poppers_left » de user_counters) : on l'utilise quand on veut, il ne se perd
  pas à minuit ; plusieurs peuvent s'accumuler (un par jour).
- Utilisation : POST /shop/poppers/use {card_id} sur une carte de SA collection dont la personne n'est pas à 100 % (sinon refus, l'objet
  est gardé). Pas de limite d'utilisation par jour.
- 1v1 seulement : le tournoi, le défi du club et le draft jouent toujours à 100 %.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import credit_log, fatigue, missions
from .database import get_db
from .models import User, Card, OwnedCard
from .profiles import UserCounter
from .security import get_current_user

router = APIRouter()
PRICE = 250                  # crédits, prix fixe
DAILY_MAX = 1                # achats au plus par jour (heure de Paris)
LEFT_KEY = "poppers_left"    # poppers en réserve (user_counters, ne se perdent pas)
DAILY_KEY = "poppers"        # poppers achetés aujourd'hui (missions.daily_count)


class UseRequest(BaseModel):
    card_id: str


def left(db: Session, user_id: str) -> int:
    row = db.query(UserCounter).filter_by(user_id=user_id, key=LEFT_KEY).first()
    return max(0, int(row.value)) if row else 0


def state(db: Session, user: User) -> dict:
    bought = int(missions.daily_count(db, user, DAILY_KEY) or 0)
    return {"left": left(db, user.id), "price": PRICE, "daily_max": DAILY_MAX, "bought_today": bought, "can_buy": bought < DAILY_MAX}


@router.get("/shop/poppers")
def get_poppers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = state(db, user)
    db.commit()                                            # (daily_count peut créer la ligne du jour)
    return out


@router.post("/shop/poppers/buy")
def buy_poppers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.refresh(user, with_for_update=True)                 # deux achats en même temps : un seul passe
    if int(missions.daily_count(db, user, DAILY_KEY) or 0) >= DAILY_MAX:
        raise HTTPException(status_code=400, detail="Tu as déjà acheté ton poppers aujourd'hui : reviens demain")
    if user.credits < PRICE:
        raise HTTPException(status_code=400, detail="Pas assez de crédits : le poppers coûte %d crédits" % PRICE)
    credit_log.add(user, -PRICE, "Poppers")                # crédits détruits (dépense volontaire)
    missions.daily_add(db, user, DAILY_KEY)
    row = db.query(UserCounter).filter_by(user_id=user.id, key=LEFT_KEY).first()
    if row is None:
        db.add(UserCounter(user_id=user.id, key=LEFT_KEY, value=1))
    else:
        row.value = max(0, row.value) + 1
    db.commit()
    return {"status": "ok", "paid": PRICE, "credits_total": user.credits, **state(db, user)}


@router.post("/shop/poppers/use")
def use_poppers(payload: UseRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=payload.card_id).first()
    card = db.get(Card, payload.card_id)
    if card is None or owned is None or owned.quantity < 1:
        raise HTTPException(status_code=404, detail="Cette carte n'est pas dans ta collection")
    row = db.query(UserCounter).filter_by(user_id=user.id, key=LEFT_KEY).with_for_update().first()
    if row is None or row.value <= 0:
        raise HTTPException(status_code=400, detail="Tu n'as pas de poppers : achète-le au shop")
    tired = db.query(fatigue.PersonFatigue).filter_by(user_id=user.id, player_id=card.player_id).first()
    if tired is None or fatigue.debt_now(tired) <= 0:
        raise HTTPException(status_code=400, detail="%s est déjà à 100 %% de forme : garde ton poppers" % card.player.name)
    db.delete(tired)                                       # dette effacée : toutes ses cartes repassent à 100 %
    row.value -= 1
    db.commit()
    return {"status": "ok", "player_name": card.player.name, "form": 100, **state(db, user)}
