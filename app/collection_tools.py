"""
Outils de collection : « Vendre tous les doublons ».

Chaque doublon se revend à un prix FIXE selon sa rareté (commune 1, rare 3, …). Mais les doublons de communes (1 point) et de rares
(5 points) d'un joueur servent aussi à FUSIONNER sa carte secrète (100 points). Tant qu'il reste des secrètes à débloquer, la vente en
bloc propose donc de GARDER les doublons de communes et de rares des joueurs dont la secrète n'est pas encore à toi. Une fois toutes
les secrètes débloquées, il n'y a plus rien à garder : tout se vend d'un coup. On garde toujours 1 exemplaire de chaque carte.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .models import Card, OwnedCard, Tier, User
from . import game_logic, missions
from .security import get_current_user

router = APIRouter()


class SellAllRequest(BaseModel):
    keep_for_secrets: bool = True          # garder les doublons de communes et de rares utiles aux secrètes encore bloquées


def _plan(db: Session, user: User):
    """Les doublons vendables : [(carte possédée, exemplaires en trop, valeur d'un exemplaire, utile aux secrètes ?)] et le nombre de secrètes à débloquer."""
    secret_players = {c.player_id for c in db.query(Card).filter(Card.tier == Tier.secrete).all()}
    owned_secret = {o.card.player_id for o in db.query(OwnedCard).join(Card, Card.id == OwnedCard.card_id)
                    .filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0, Card.tier == Tier.secrete).all()}
    locked = secret_players - owned_secret
    rows = []
    for o in db.query(OwnedCard).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 1).all():
        tier = o.card.tier
        if tier == Tier.saison or game_logic.card_kind(o.card.player) == "trophee":      # un trophée ne se vend jamais
            continue
        useful = tier in (Tier.commune, Tier.rare) and o.card.player_id in locked
        rows.append((o, o.quantity - 1, game_logic.DUPLICATE_SELL_VALUE[tier.value], useful))
    return rows, len(locked)


def _totals(rows) -> dict:
    return {"copies": sum(r[1] for r in rows), "kinds": len(rows), "credits": sum(r[1] * r[2] for r in rows)}


@router.get("/collection/duplicates-summary")
def duplicates_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ce que rapporterait la vente en bloc, dans les deux variantes (avec ou sans les doublons utiles aux secrètes)."""
    rows, locked = _plan(db, user)
    kept = [r for r in rows if r[3]]
    return {"all": _totals(rows), "keep": _totals([r for r in rows if not r[3]]), "secrets_locked": locked,
            "kept_for_secrets": sum(r[1] for r in kept), "fusion_cost": game_logic.SECRET_FUSION_COST}


@router.post("/collection/sell-duplicates")
def sell_all_duplicates(payload: SellAllRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Vend tous les doublons d'un coup (en gardant, si demandé, ceux qui servent encore aux cartes secrètes). Définitif."""
    rows, _ = _plan(db, user)
    chosen = [r for r in rows if not (payload.keep_for_secrets and r[3])]
    if not chosen:
        raise HTTPException(status_code=400, detail="Aucun doublon à vendre")
    total = _totals(chosen)
    for owned, extra, value, useful in chosen:
        owned.quantity = 1
    user.credits += total["credits"]
    db.commit()
    missions.safe_record(db, user, "sell_dupes", total["copies"])
    return {"sold": total["copies"], "kinds": total["kinds"], "credits_gained": total["credits"], "credits_total": user.credits}
