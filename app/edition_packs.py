"""
Packs d'édition limitée du Pass Premium (branche pack-edition-pass, 20/11/2026) : la récompense « pack d'édition limitée » des niveaux 20
(2 cartes) et 30 (3 cartes) du Pass Premium devient un VRAI pack, rangé dans la réserve de l'onglet Packs et ouvert avec l'animation
habituelle (POST /pack/open {pack_type: "edition", edition_pack_id}). Avant, ses cartes allaient directement dans la collection, sans
ouverture : les joueurs croyaient ne rien avoir reçu.

- Contenu inchangé : `size` cartes de l'édition du thème du Pass (de préférence celles que le joueur n'a pas encore), pas de crédits.
- Sans édition pour le thème (ou sans aucune carte de cette édition) au moment de la récupération : repli inchangé, des packs rares
  (battlepass._edition_pack). Si l'édition n'a plus de carte au moment de l'ouverture : le pack est remplacé par un pack rare.
- Compte comme un pack ouvert (missions, succès, objectif du club), comme les packs joueur.
- /me renvoie `edition_packs` [{id, edition, size, season}]. Suppression d'un compte : ses packs non ouverts disparaissent.
"""
import random
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base
from .models import Card, OwnedCard, Tier, User, gen_id
from . import game_logic

RNG = random.Random()                                        # (remplaçable dans les tests)


class OwnedEditionPack(Base):
    """Un pack d'édition limitée gagné dans le Pass et pas encore ouvert."""
    __tablename__ = "edition_packs_owned"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False, index=True)
    edition = Column(String, nullable=False)                 # rareté de l'édition (halloween, noel, ed1…)
    size = Column(Integer, nullable=False, default=2)        # nombre de cartes
    season = Column(String, nullable=True)                   # Pass d'origine (AAAA-MM)
    level = Column(Integer, nullable=True)                   # niveau du Pass
    created_at = Column(DateTime, default=datetime.utcnow)


def _cards(db: Session, edition: str) -> list:
    try:
        return db.query(Card).filter(Card.tier == Tier(edition)).all()
    except ValueError:
        return []


def grant(db: Session, user: User, edition: str, size: int, season: str = None, level: int = None) -> OwnedEditionPack:
    """Range un pack d'édition dans la réserve du joueur (sans commit)."""
    row = OwnedEditionPack(user_id=user.id, edition=edition, size=int(size), season=season, level=level)
    db.add(row); db.flush()
    return row


def owned_out(db: Session, user_id: str) -> list:
    rows = db.query(OwnedEditionPack).filter_by(user_id=user_id).order_by(OwnedEditionPack.created_at).all()
    return [{"id": r.id, "edition": r.edition, "size": r.size, "season": r.season} for r in rows]


def open_for_user(db: Session, user: User, pack_id: Optional[str]) -> dict:
    """Ouvre un pack d'édition de la réserve : `size` cartes de l'édition, de préférence nouvelles pour le joueur, toutes différentes
    si possible. Même forme de résultat que game_logic.open_pack_for_user. Lève ValueError("no_pack_available") ou ("edition_empty")."""
    row = db.query(OwnedEditionPack).filter_by(id=pack_id or "", user_id=user.id).with_for_update().first()
    if row is None:
        raise ValueError("no_pack_available")
    cards = _cards(db, row.edition)
    db.delete(row)
    if not cards:                                            # l'édition n'a plus de carte : un pack rare à la place
        ps = user.pack_state; ps.rare_pack_tokens = (getattr(ps, "rare_pack_tokens", 0) or 0) + 1
        db.commit()
        raise ValueError("edition_empty")
    owned = {o.card_id for o in db.query(OwnedCard).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    fresh = [c for c in cards if c.id not in owned]; RNG.shuffle(fresh)
    rest = [c for c in cards if c.id in owned]; RNG.shuffle(rest)
    won = (fresh + rest)[:row.size]
    while len(won) < row.size:                               # (édition plus petite que le pack : on complète, doublons possibles)
        won.append(RNG.choice(cards))
    RNG.shuffle(won)
    new_flags = []
    for c in won:
        o = game_logic.get_or_create_owned(db, user, c)
        new_flags.append(o.quantity == 0)
        o.quantity += 1
    db.commit()
    return {"credits_won": 0, "cards_won": won, "new_flags": new_flags, "crafted": [], "source": "pass", "pack_type": "edition"}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(OwnedEditionPack).filter_by(user_id=user_id).delete()
