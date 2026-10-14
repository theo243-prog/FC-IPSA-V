"""
Offres d'achat au marché.

Un joueur peut proposer d'acheter une carte précise à un prix qu'il fixe. Ses crédits sont mis de côté tout de suite
(comme la mise d'un défi), si bien que le vendeur est sûr d'être payé. Un joueur qui POSSÈDE cette carte voit l'offre et peut
la prendre en direct : la carte passe à l'offreur, les crédits au vendeur, l'offre disparaît.

Pour garder la surprise des cartes pas encore débloquées, une offre n'est visible que de son auteur et des joueurs qui possèdent
la carte : on ne peut pas deviner le nom d'une carte en parcourant les offres.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, OwnedCard, User
from . import game_logic, missions, push
from .common import card_out, optional_user
from .security import get_current_user

router = APIRouter()
MAX_OPEN_OFFERS = 5          # offres ouvertes en même temps, par joueur
PRICE_MAX = 100000


class BuyOffer(Base):
    """Une offre d'achat ouverte (volontairement sans clés étrangères : on nettoie à la main quand un compte ou une carte disparaît)."""
    __tablename__ = "buy_offers"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    buyer_id = Column(String, nullable=False)
    card_id = Column(String, nullable=False)
    price = Column(Integer, nullable=False)           # crédits mis de côté
    created_at = Column(DateTime, default=datetime.utcnow)


class Trade(Base):
    """Un échange entre deux joueurs au marché (annonce achetée, ou offre d'achat acceptée). Les pseudos sont gardés tels quels :
    l'historique reste lisible même si un compte est supprimé ensuite (volontairement sans clés étrangères)."""
    __tablename__ = "trades"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kind = Column(String, nullable=False)              # "annonce" ou "offre"
    seller_id = Column(String, nullable=False)
    buyer_id = Column(String, nullable=False)
    seller_pseudo = Column(String, nullable=False)
    buyer_pseudo = Column(String, nullable=False)
    card_id = Column(String, nullable=False)
    card_tier = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def record_trade(db: Session, kind: str, seller: User, buyer: User, card: Card, price: int) -> None:
    """Note un échange dans l'historique du marché. Ne fait JAMAIS échouer la vente elle-même."""
    try:
        db.add(Trade(kind=kind, seller_id=seller.id, buyer_id=buyer.id, seller_pseudo=seller.pseudo, buyer_pseudo=buyer.pseudo,
                     card_id=card.id, card_tier=card.tier.value, price=price))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


class CreateOfferRequest(BaseModel):
    card_id: str
    price: int = Field(ge=1, le=PRICE_MAX)


def reserved_credits(db: Session) -> dict:
    """Crédits mis de côté dans les offres ouvertes, par joueur (comptés dans le total public du classement)."""
    out = {}
    for buyer_id, price in db.query(BuyOffer.buyer_id, BuyOffer.price).all():
        out[buyer_id] = out.get(buyer_id, 0) + price
    return out


def refund_for_cards(db: Session, card_ids: list) -> int:
    """Une carte disparaît du jeu : les offres qui la visaient sont annulées et remboursées."""
    n = 0
    for o in db.query(BuyOffer).filter(BuyOffer.card_id.in_(card_ids)).all():
        buyer = db.query(User).filter_by(id=o.buyer_id).first()
        if buyer:
            buyer.credits += o.price
        db.delete(o)
        n += 1
    return n


def _name(card: Card) -> str:
    p = card.player
    return p.surnom if (card.tier.value == "secrete" and p.surnom) else p.name


def notify_sold(db: Session, buyer_id: str, seller_pseudo: str, card: Card, price: int) -> None:
    push.enqueue(db, buyer_id, "market", "Offre acceptée 💰", "%s te vend %s pour %d crédit%s." % (seller_pseudo, _name(card), price, "s" if price > 1 else ""),
                 url="/#marche", tag="offer-accepted")


def _offer_out(o: BuyOffer, card: Card, **extra) -> dict:
    return {"id": o.id, "price": o.price, "created_at": o.created_at.isoformat(), "card": card_out(card), **extra}


@router.post("/market/offers")
def create_offer(payload: CreateOfferRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.query(Card).filter_by(id=payload.card_id).first()
    if card is None:
        raise HTTPException(status_code=404, detail="Cette carte n'existe pas")
    if card.tier.value == "saison":
        raise HTTPException(status_code=400, detail="Un trophée de saison ne s'achète pas : seul son gagnant l'a")
    if db.query(BuyOffer).filter_by(buyer_id=user.id).count() >= MAX_OPEN_OFFERS:
        raise HTTPException(status_code=400, detail="Tu as déjà %d offres d'achat ouvertes : annule-en une avant d'en faire une autre" % MAX_OPEN_OFFERS)
    if db.query(BuyOffer).filter_by(buyer_id=user.id, card_id=card.id).first():
        raise HTTPException(status_code=400, detail="Tu as déjà une offre pour cette carte : annule-la d'abord pour changer le prix")
    if user.credits < payload.price:
        raise HTTPException(status_code=400, detail="Pas assez de crédits pour cette offre")
    user.credits -= payload.price            # mis de côté : rendu si tu annules, versé au vendeur si une offre est prise
    offer = BuyOffer(buyer_id=user.id, card_id=card.id, price=payload.price)
    db.add(offer)
    db.commit()
    return {"id": offer.id, "credits": user.credits}


@router.get("/market/offers/mine")
def my_offers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(BuyOffer).filter_by(buyer_id=user.id).order_by(BuyOffer.created_at.desc()).all()
    cards = {c.id: c for c in db.query(Card).filter(Card.id.in_([o.card_id for o in rows])).all()} if rows else {}
    return [_offer_out(o, cards[o.card_id]) for o in rows if o.card_id in cards]


@router.delete("/market/offers/{offer_id}")
def cancel_offer(offer_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = db.query(BuyOffer).filter_by(id=offer_id, buyer_id=user.id).first()
    if o is None:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    user.credits += o.price
    db.delete(o)
    db.commit()
    return {"status": "ok", "credits": user.credits}


@router.get("/market/offers/for-me")
def offers_for_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Les offres d'achat visant une carte que je possède (les offres sur d'autres cartes ne me sont jamais montrées)."""
    owned = {o.card_id: o.quantity for o in db.query(OwnedCard).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    if not owned:
        return []
    rows = db.query(BuyOffer).filter(BuyOffer.card_id.in_(list(owned)), BuyOffer.buyer_id != user.id).order_by(BuyOffer.price.desc()).all()
    cards = {c.id: c for c in db.query(Card).filter(Card.id.in_([o.card_id for o in rows])).all()} if rows else {}
    buyers = {u.id: u.pseudo for u in db.query(User).filter(User.id.in_([o.buyer_id for o in rows])).all()} if rows else {}
    return [_offer_out(o, cards[o.card_id], buyer=buyers.get(o.buyer_id, "?"), quantity=owned[o.card_id]) for o in rows if o.card_id in cards]


@router.post("/market/offers/{offer_id}/accept")
def accept_offer(offer_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Je vends une de mes cartes, tout de suite, à celui qui m'en propose ce prix."""
    o = db.query(BuyOffer).filter_by(id=offer_id).first()
    if o is None:
        raise HTTPException(status_code=404, detail="Cette offre n'existe plus")
    if o.buyer_id == user.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas accepter ta propre offre")
    mine = db.query(OwnedCard).filter_by(user_id=user.id, card_id=o.card_id).first()
    if mine is None or mine.quantity < 1:
        raise HTTPException(status_code=400, detail="Tu ne possèdes pas cette carte")
    buyer = db.query(User).filter_by(id=o.buyer_id).first()
    card = db.query(Card).filter_by(id=o.card_id).first()
    if buyer is None or card is None:                                     # l'offreur ou la carte a disparu : on nettoie
        if buyer:
            buyer.credits += o.price
        db.delete(o)
        db.commit()
        raise HTTPException(status_code=404, detail="Cette offre n'existe plus")
    price = o.price
    mine.quantity -= 1
    game_logic.get_or_create_owned(db, buyer, card).quantity += 1
    user.credits += price                    # les crédits de l'offreur étaient déjà mis de côté
    db.delete(o)
    db.commit()
    record_trade(db, "offre", user, buyer, card, price)
    push.safe(db, notify_sold, buyer.id, user.pseudo, card, price)
    missions.safe_record(db, buyer, "market_buy")
    missions.safe_record(db, user, "market_list")
    return {"status": "ok", "credits_gained": price, "credits": user.credits, "buyer": buyer.pseudo}


@router.get("/market/history")
def market_history(limit: int = 100, viewer=Depends(optional_user), db: Session = Depends(get_db)):
    """Les derniers échanges entre joueurs (du plus récent au plus ancien). Une carte vendue par ANNONCE était déjà visible de tous au
    marché : elle s'affiche en entier. Une carte échangée par OFFRE D'ACHAT ne l'était pas : son nom n'est montré qu'à ceux qui
    sont dans l'échange ou qui possèdent cette carte (les autres voient seulement sa rareté), pour garder la surprise des cartes à découvrir."""
    limit = max(1, min(int(limit), 200))
    rows = db.query(Trade).order_by(Trade.created_at.desc()).limit(limit).all()
    cards = {c.id: c for c in db.query(Card).filter(Card.id.in_({t.card_id for t in rows})).all()} if rows else {}
    mine = {o.card_id for o in db.query(OwnedCard).filter(OwnedCard.user_id == viewer.id, OwnedCard.quantity > 0).all()} if viewer is not None else set()
    out = []
    for t in rows:
        card = cards.get(t.card_id)
        involved = viewer is not None and viewer.id in (t.seller_id, t.buyer_id)
        shown = card is not None and (t.kind == "annonce" or involved or t.card_id in mine)
        out.append({"id": t.id, "kind": t.kind, "created_at": t.created_at.isoformat(), "seller": t.seller_pseudo, "buyer": t.buyer_pseudo, "price": t.price,
                    "card": card_out(card) if shown else {"masked": True, "tier": t.card_tier, "deleted": card is None}})
    return out
