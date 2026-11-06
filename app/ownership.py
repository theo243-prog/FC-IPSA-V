"""
Part des joueurs qui possèdent chaque carte (ligne « 👥 Possédée par 37 % des joueurs (12 sur 32) » de la fiche d'une carte).

- Propriétaire : un compte qui a AU MOINS un exemplaire de la carte dans sa collection (les doublons ne comptent qu'une fois ; une copie
  en vente au marché ou aux enchères n'est plus dans la collection).
- Total : les comptes qui possèdent au moins une carte. Les pseudos de EXCLUDED_FROM_STATS ne comptent ni dans le total ni comme propriétaires.
- Une seule requête groupée pour toutes les cartes, gardée en cache CACHE_SECONDS secondes (pas de calcul à chaque clic).
- Confidentialité : jamais de nom de propriétaire. Une carte secrète, un trophée de saison ou une carte d'édition pas encore commencée
  que le joueur ne possède pas n'apparaît pas du tout dans la réponse.
"""
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from .models import Card, OwnedCard, Tier, User
from .security import get_current_user
from . import game_logic

router = APIRouter()
EXCLUDED_FROM_STATS: list = []            # pseudos exclus des statistiques (comptes de test…)
CACHE_SECONDS = 60
_cache = {"at": 0.0, "data": None}


def _compute(db: Session) -> dict:
    """{"total": comptes avec au moins une carte, "owners": {card_id: nombre de propriétaires}}, en deux requêtes groupées."""
    q = db.query(OwnedCard).filter(OwnedCard.quantity > 0)
    if EXCLUDED_FROM_STATS:
        q = q.join(User, User.id == OwnedCard.user_id).filter(User.pseudo.notin_(list(EXCLUDED_FROM_STATS)))
    total = q.with_entities(func.count(func.distinct(OwnedCard.user_id))).scalar() or 0
    owners = dict(q.with_entities(OwnedCard.card_id, func.count(func.distinct(OwnedCard.user_id))).group_by(OwnedCard.card_id).all())
    return {"total": int(total), "owners": {k: int(v) for k, v in owners.items()}}


def stats(db: Session) -> dict:
    now = time.monotonic()
    if _cache["data"] is None or now - _cache["at"] >= CACHE_SECONDS:
        _cache.update(at=now, data=_compute(db))
    return _cache["data"]


def clear_cache() -> None:
    _cache.update(at=0.0, data=None)


def _hidden_for(db: Session, user: User) -> set:
    """Les cartes dont ce joueur ne doit rien savoir : secrètes, trophées et éditions pas encore commencées qu'il ne possède pas."""
    tiers = [Tier.secrete, Tier.saison] + [Tier(k) for k in game_logic.EDITION_TIERS if game_logic.edition_status(db, k) == "upcoming"]
    mine = {cid for (cid,) in db.query(OwnedCard.card_id).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    return {cid for (cid,) in db.query(Card.id).filter(Card.tier.in_(tiers)).all()} - mine


@router.get("/cards/ownership")
def ownership(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Total des joueurs et nombre de propriétaires de chaque carte visible (0 compris). Jamais de nom."""
    s = stats(db)
    hidden = _hidden_for(db, user)
    cards = {cid: s["owners"].get(cid, 0) for (cid,) in db.query(Card.id).all() if cid not in hidden}
    return {"total_players": s["total"], "cards": cards, "cache_seconds": CACHE_SECONDS}
