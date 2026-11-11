"""
Packs joueur du shop (11/11/2026) : pour aider les joueurs à obtenir les cartes des joueurs qu'ils veulent faire évoluer.

- Chaque jour (jour de Paris, changé à minuit), le shop propose les MÊMES offres à tout le monde, tirées au hasard au premier accès
  et enregistrées (table player_pack_offers, une ligne par jour et par emplacement) :
  * RARE_OFFERS (4) packs « joueur rare » à RARE_PRICE (75) crédits : la carte RARE d'un vrai joueur est garantie (4 joueurs différents) ;
  * PREMIUM_OFFERS (1) pack « joueur premium » : une carte plus rare que rare d'un vrai joueur est garantie, au prix de sa rareté
    (PREMIUM_PRICES : édition limitée EN COURS 200, épique 300, spéciale 400 ; jamais de légendaire, de secrète, de trophée ni d'édition
    pas commencée ou terminée). On tire d'abord la catégorie (parmi celles qui ont des cartes), puis la carte. Les spéciales des postes de
    PREMIUM_EXCLUDED_SPECIAL_POSTES (le gardien) ne sont pas proposées, pour ne pas renforcer encore le seul gardien du club.
- Un pack = 3 cartes toutes différentes : la carte garantie + 2 cartes aux probabilités du pack classique (gold, édition, épique…
  possibles), et des crédits comme n'importe quel pack. Les promotions du shop (events.shop_price) s'appliquent.
- Achat sans limite. Le pack acheté va dans la réserve (table player_packs_owned) et s'ouvre dans l'onglet Packs (/pack/open avec
  pack_type « joueur » et player_pack_id), avec l'animation habituelle. Il compte comme un pack ouvert (missions, succès, objectif du club).
- Carte supprimée : les offres du jour sur cette carte disparaissent, les packs non ouverts sont remboursés (prix payé).
"""
import random
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, Tier, User, gen_id
from .security import get_current_user
from . import events, game_logic

RARE_OFFERS = 4
PREMIUM_OFFERS = 1
RARE_PRICE = 75
PREMIUM_PRICES = {"edition": 200, "epique": 300, "speciale": 400}
PREMIUM_EXCLUDED_SPECIAL_POSTES = {"GB"}       # pas de spéciale du gardien dans le pack premium (vider l'ensemble pour l'autoriser)
RNG = random.Random()                           # remplaçable dans les tests

router = APIRouter()


class PlayerPackOffer(Base):
    """Une offre du shop pour un jour : la carte garantie et son prix (les mêmes pour tout le monde ce jour-là)."""
    __tablename__ = "player_pack_offers"
    __table_args__ = (UniqueConstraint("day", "slot", name="uq_player_pack_offer"),)
    id = Column(String, primary_key=True, default=gen_id)
    day = Column(String, nullable=False, index=True)          # AAAA-MM-JJ (Paris)
    slot = Column(Integer, nullable=False)                    # 0..3 : rare, 4 : premium
    kind = Column(String, nullable=False)                     # « rare » ou « premium »
    card_id = Column(String, nullable=False)
    price = Column(Integer, nullable=False)                   # prix de base (avant une éventuelle promotion)
    created_at = Column(DateTime, default=datetime.utcnow)


class OwnedPlayerPack(Base):
    """Un pack joueur acheté et pas encore ouvert."""
    __tablename__ = "player_packs_owned"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False, index=True)
    card_id = Column(String, nullable=False)                  # la carte garantie
    kind = Column(String, nullable=False)
    price_paid = Column(Integer, nullable=False, default=0)
    bought_at = Column(DateTime, default=datetime.utcnow)


class BuyRequest(BaseModel):
    offer_id: str


def _real_player_cards(db: Session, tiers) -> list:
    return [c for c in db.query(Card).filter(Card.tier.in_([Tier(t) for t in tiers])).all() if game_logic.card_kind(c.player) == "joueur"]


def _premium_category(card: Card) -> Optional[str]:
    t = card.tier.value
    if t in game_logic.EDITION_TIERS:
        return "edition"
    return t if t in PREMIUM_PRICES else None


def _premium_candidates(db: Session) -> dict:
    """{catégorie: [cartes]} des cartes possibles pour le pack premium aujourd'hui."""
    active = [k for k in game_logic.EDITION_TIERS if game_logic.edition_status(db, k) == "active"]
    out = {"edition": _real_player_cards(db, active) if active else [],
           "epique": _real_player_cards(db, ["epique"]),
           "speciale": [c for c in _real_player_cards(db, ["speciale"]) if (c.player.poste or "").upper() not in PREMIUM_EXCLUDED_SPECIAL_POSTES]}
    return {k: v for k, v in out.items() if v}


def _draw_offers(db: Session) -> list:
    """Les offres d'un nouveau jour : [(emplacement, type, carte, prix)]."""
    rares = _real_player_cards(db, ["rare"])
    RNG.shuffle(rares)
    seen, picks = set(), []
    for c in rares:                                           # 4 joueurs différents
        if c.player_id not in seen:
            seen.add(c.player_id); picks.append(c)
        if len(picks) >= RARE_OFFERS:
            break
    out = [(i, "rare", c, RARE_PRICE) for i, c in enumerate(picks)]
    cands = _premium_candidates(db)
    for j in range(PREMIUM_OFFERS):
        if not cands:
            break
        cat = RNG.choice(sorted(cands))
        card = RNG.choice(cands[cat])
        out.append((RARE_OFFERS + j, "premium", card, PREMIUM_PRICES[cat]))
    return out


def todays_offers(db: Session) -> list:
    """Les offres du jour (créées au premier accès, puis les mêmes toute la journée pour tout le monde)."""
    day = game_logic.today_paris().isoformat()
    rows = db.query(PlayerPackOffer).filter_by(day=day).order_by(PlayerPackOffer.slot).all()
    if rows:
        return rows
    try:
        for slot, kind, card, price in _draw_offers(db):
            db.add(PlayerPackOffer(day=day, slot=slot, kind=kind, card_id=card.id, price=price))
        db.commit()
    except IntegrityError:                                    # deux premiers accès en même temps : on garde celui qui a gagné
        db.rollback()
    return db.query(PlayerPackOffer).filter_by(day=day).order_by(PlayerPackOffer.slot).all()


def _card_info(card: Card) -> dict:
    return {"card_id": card.id, "player_name": card.player.name, "poste": card.player.poste, "tier": card.tier.value}


def owned_out(db: Session, user_id: str) -> list:
    rows = db.query(OwnedPlayerPack).filter_by(user_id=user_id).order_by(OwnedPlayerPack.bought_at).all()
    out = []
    for r in rows:
        card = db.get(Card, r.card_id)
        if card is not None:
            out.append({"id": r.id, "kind": r.kind, **_card_info(card)})
    return out


def state_out(db: Session, user: User) -> dict:
    offers = []
    for o in todays_offers(db):
        card = db.get(Card, o.card_id)
        if card is None:
            continue
        price = events.shop_price(db, o.price)
        offers.append({"id": o.id, "kind": o.kind, "base_price": o.price, "price": price,
                       "discount": round(100 * (o.price - price) / o.price) if price < o.price else 0, **_card_info(card)})
    return {"day": game_logic.today_paris().isoformat(), "offers": offers, "owned": owned_out(db, user.id), "credits": user.credits,
            "prices": {"rare": RARE_PRICE, **PREMIUM_PRICES}}


def buy(db: Session, user: User, offer_id: str) -> OwnedPlayerPack:
    day = game_logic.today_paris().isoformat()
    offer = db.query(PlayerPackOffer).filter_by(id=offer_id).first()
    if offer is None or offer.day != day:
        raise ValueError("Cette offre n'est plus disponible : les packs joueur changent chaque jour à minuit")
    if db.get(Card, offer.card_id) is None:
        raise ValueError("Cette offre n'est plus disponible")
    db.query(User).filter_by(id=user.id).with_for_update().first()        # (deux clics en même temps : un seul passe)
    db.refresh(user)
    price = events.shop_price(db, offer.price)
    if user.credits < price:
        raise ValueError("Pas assez de crédits (il en faut %d)" % price)
    user.credits -= price
    row = OwnedPlayerPack(user_id=user.id, card_id=offer.card_id, kind=offer.kind, price_paid=price)
    db.add(row)
    db.commit()
    return row


def open_for_user(db: Session, user: User, pack_id: Optional[str]) -> dict:
    """Ouvre un pack joueur de la réserve : la carte garantie + 2 cartes aux probabilités classiques, toutes différentes, et des crédits.
    Même forme de résultat que game_logic.open_pack_for_user. Lève ValueError("no_pack_available")."""
    row = db.query(OwnedPlayerPack).filter_by(id=pack_id or "", user_id=user.id).with_for_update().first()
    card = db.get(Card, row.card_id) if row is not None else None
    if card is None:
        raise ValueError("no_pack_available")
    db.delete(row)
    credits_won = int(game_logic._roll_weighted(game_logic.CREDIT_WEIGHTS))
    user.credits += credits_won
    counts = game_logic.tier_card_counts(db)
    weights = game_logic.classic_tier_weights(counts, game_logic.weights_with_editions(db, game_logic.TIER_WEIGHTS, "classique", counts))
    cards, taken = [card], {card.id}
    for _ in range(2):
        c = game_logic._draw_distinct_card(db, game_logic._roll_weighted(weights), weights, taken)
        taken.add(c.id); cards.append(c)
    RNG.shuffle(cards)                                        # la place de la carte garantie ne dit rien
    new_flags = []
    for c in cards:
        owned = game_logic.get_or_create_owned(db, user, c)
        new_flags.append(owned.quantity == 0)
        owned.quantity += 1
    db.commit()
    return {"credits_won": credits_won, "cards_won": cards, "new_flags": new_flags, "crafted": [], "source": "shop", "pack_type": "joueur"}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(OwnedPlayerPack).filter_by(user_id=user_id).delete()


def on_cards_deleted(db: Session, card_ids) -> None:
    """Carte supprimée : ses offres disparaissent et ses packs pas encore ouverts sont remboursés. Sans commit."""
    ids = list(card_ids or [])
    if not ids:
        return
    db.query(PlayerPackOffer).filter(PlayerPackOffer.card_id.in_(ids)).delete(synchronize_session=False)
    for r in db.query(OwnedPlayerPack).filter(OwnedPlayerPack.card_id.in_(ids)).all():
        u = db.get(User, r.user_id)
        if u is not None:
            u.credits += r.price_paid or 0
        db.delete(r)


@router.get("/shop/player-packs")
def get_player_packs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Les packs joueur du jour (les mêmes pour tout le monde) et mes packs joueur pas encore ouverts."""
    return state_out(db, user)


@router.post("/shop/player-packs/buy")
def buy_player_pack(payload: BuyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Achète un pack joueur du jour (sans limite) : il va dans la réserve et s'ouvre dans l'onglet Packs."""
    try:
        row = buy(db, user, payload.offer_id)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "pack_id": row.id, "credits_total": user.credits, **state_out(db, user)}
