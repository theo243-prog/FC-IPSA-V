"""
Gel de fatigue au shop (branche gel-fatigue, 19/11/2026) : un achat donne MATCHES (5) matchs 1v1 sans fatigue. Pendant ces matchs, les cartes
alignées ne perdent pas de forme (fatigue.record_match n'est pas appelé pour ce joueur) ; la forme déjà perdue reste perdue (le gel ne soigne
pas) et continue de remonter de 1 % par heure. Un match consomme un match de gel, que le joueur ait créé le défi ou qu'il le relève.

- Prix : BASE_PRICE (50) crédits, puis le prix DOUBLE à chaque achat du jour (50, 100, 200, 400…), sans limite d'achat ; il repart à 50 à
  minuit (heure de Paris), compteur du jour « fatigue_gels » de missions.daily_count. Prix fixe : les promotions du shop ne s'appliquent pas.
- Les matchs de gel s'additionnent (deux achats = 10 matchs) et ne se perdent pas à minuit : compteur à vie « fatigue_gel_left » (user_counters).
- 1v1 seulement : le tournoi, le défi du club et le draft ne fatiguent pas.
- Dépense volontaire (jamais de taxe) : les crédits sont détruits.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import credit_log
from .database import get_db
from .models import User
from .security import get_current_user
from . import missions
from .profiles import UserCounter

router = APIRouter()
MATCHES = 5                    # matchs 1v1 sans fatigue par achat
BASE_PRICE = 50                # prix du premier gel du jour ; il double à chaque achat du jour
LEFT_KEY = "fatigue_gel_left"  # matchs de gel restants (user_counters, ne se perdent pas)
DAILY_KEY = "fatigue_gels"     # gels achetés aujourd'hui (missions.daily_count, remis à zéro à minuit, heure de Paris)


def left(db: Session, user_id: str) -> int:
    row = db.query(UserCounter).filter_by(user_id=user_id, key=LEFT_KEY).first()
    return max(0, int(row.value)) if row else 0


def next_price(db: Session, user: User) -> int:
    return BASE_PRICE * 2 ** int(missions.daily_count(db, user, DAILY_KEY) or 0)


def state(db: Session, user: User) -> dict:
    return {"left": left(db, user.id), "price": next_price(db, user), "matches": MATCHES, "base_price": BASE_PRICE,
            "bought_today": int(missions.daily_count(db, user, DAILY_KEY) or 0)}


def use(db: Session, user_id: str) -> bool:
    """Un match 1v1 va être joué : s'il reste du gel, il en consomme un match et renvoie True (pas de fatigue pour ce joueur). Sans commit."""
    row = db.query(UserCounter).filter_by(user_id=user_id, key=LEFT_KEY).with_for_update().first()
    if row is None or row.value <= 0:
        return False
    row.value -= 1
    return True


@router.get("/shop/fatigue-gel")
def get_fatigue_gel(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = state(db, user)
    db.commit()                                            # (daily_count peut créer la ligne du jour)
    return out


@router.post("/shop/fatigue-gel/buy")
def buy_fatigue_gel(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.refresh(user, with_for_update=True)                 # deux achats en même temps : un seul passe à la fois
    price = next_price(db, user)
    if user.credits < price:
        raise HTTPException(status_code=400, detail="Pas assez de crédits : le gel coûte %d crédits" % price)
    credit_log.add(user, -price, "Gel de fatigue")                                  # crédits détruits (dépense volontaire)
    missions.daily_add(db, user, DAILY_KEY)
    row = db.query(UserCounter).filter_by(user_id=user.id, key=LEFT_KEY).first()
    if row is None:
        db.add(UserCounter(user_id=user.id, key=LEFT_KEY, value=MATCHES))
    else:
        row.value = max(0, row.value) + MATCHES
    db.commit()
    return {"status": "ok", "paid": price, "credits_total": user.credits, **state(db, user)}
