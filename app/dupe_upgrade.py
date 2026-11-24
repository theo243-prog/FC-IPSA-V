"""
Doublons de communes → la rare de la même personne (branche `doublons-vers-rare`, 17/11/2026).

Depuis la fiche d'une carte COMMUNE de sa collection, un joueur échange DUPES_FOR_RARE (5) doublons de cette carte contre un exemplaire
de la carte RARE de la même personne (joueur, fan, Loup, équipement… tant que cette rare existe dans le jeu). Les doublons sont
CONSOMMÉS ; on garde toujours au moins un exemplaire de la commune, donc sa copie évoluée et son niveau restent. La rare reçue arrive
au niveau 0 (s'il en avait déjà une, la quantité augmente, son niveau ne change pas). Pas de limite par jour, pas de crédits à payer.
Plusieurs échanges d'un coup (24/11/2026) : `count` rares pour count × 5 doublons (20 doublons → 4 rares), `max` = doublons // 5.
"""
from typing import Optional

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import Card, OwnedCard, Tier, User
from . import game_logic
from .security import get_current_user

router = APIRouter()

DUPES_FOR_RARE = 5         # doublons de la commune consommés pour 1 exemplaire de la rare


def _rare_of(db: Session, card: Card):
    return db.query(Card).filter_by(player_id=card.player_id, tier=Tier.rare).first()


def info(db: Session, user: User, card: Card) -> dict:
    """Ce que la fiche affiche : doublons, carte rare visée, et la raison si c'est impossible."""
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card.id).first()
    dupes = max(0, (owned.quantity if owned else 0) - 1)
    out = {"card_id": card.id, "needed": DUPES_FOR_RARE, "dupes": dupes, "max": dupes // DUPES_FOR_RARE, "eligible": False, "can": False,
           "reason": None, "rare_card_id": None, "rare_owned": 0}
    if card.tier != Tier.commune:
        out["reason"] = "Seules les cartes communes s'échangent contre la rare"; return out
    if not owned or owned.quantity < 1:
        out["reason"] = "Cette carte n'est pas dans ta collection"; return out
    rare = _rare_of(db, card)
    if rare is None:
        out["reason"] = "Cette personne n'a pas de carte rare"; return out
    ro = db.query(OwnedCard).filter_by(user_id=user.id, card_id=rare.id).first()
    out.update(eligible=True, rare_card_id=rare.id, rare_owned=ro.quantity if ro else 0)
    if dupes < DUPES_FOR_RARE:
        out["reason"] = "Il te faut %d doublons de cette carte (tu en as %d)" % (DUPES_FOR_RARE, dupes); return out
    out["can"] = True
    return out


@router.get("/cards/{card_id}/upgrade-rare")
def upgrade_rare_info(card_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Cette carte n'existe pas")
    return info(db, user, card)


class UpgradeIn(BaseModel):
    count: Optional[int] = 1          # nombre de rares voulues (count × 5 doublons)


@router.post("/cards/{card_id}/upgrade-rare")
def upgrade_rare(card_id: str, data: Optional[UpgradeIn] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Échange count × 5 doublons d'une commune contre count exemplaires de la rare de la même personne (définitif)."""
    count = (data.count if data and data.count is not None else 1)
    if count < 1:
        raise HTTPException(status_code=400, detail="Choisis au moins 1 carte rare")
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Cette carte n'existe pas")
    db.query(User).filter_by(id=user.id).with_for_update().first()        # (deux clics en même temps : un seul passe)
    i = info(db, user, card)
    if not i["can"]:
        raise HTTPException(status_code=400, detail=i["reason"] or "Échange impossible")
    if count > i["max"]:
        raise HTTPException(status_code=400, detail="Il te faut %d doublons pour %d rares (tu en as %d)" % (count * DUPES_FOR_RARE, count, i["dupes"]))
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card.id).first()
    owned.quantity -= DUPES_FOR_RARE * count                                   # il reste toujours au moins 1 exemplaire (et sa copie évoluée)
    rare = db.get(Card, i["rare_card_id"])
    ro = game_logic.get_or_create_owned(db, user, rare)
    ro.quantity += count
    db.commit()
    return {"status": "ok", "dupes_used": DUPES_FOR_RARE * count, "count": count, "rare_card_id": rare.id, "player_name": rare.player.name,
            "rare_quantity": ro.quantity, "info": info(db, user, card)}
