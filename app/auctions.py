"""
Enchères au marché.

Un joueur met une de ses cartes (rare ou mieux : pas les communes, pas les trophées) aux enchères : il choisit le PRIX DE DÉPART et la DURÉE (de 15 minutes à 24 heures).
- La carte est mise de côté tout de suite. Chaque enchère doit dépasser la précédente d'au moins 5 % (1 crédit minimum) ; le premier enchérisseur peut miser le prix de départ.
- Les crédits de l'enchérisseur sont mis de côté ; s'il est dépassé, il est remboursé tout de suite (et prévenu).
- Anti-« dernière seconde » : une enchère dans les 2 dernières minutes prolonge l'enchère de 2 minutes.
- À la fin : la carte va au meilleur enchérisseur, le vendeur reçoit les crédits. Sans aucune enchère, la carte revient au vendeur. Le vendeur peut annuler tant qu'il n'y a pas d'enchère.
"""
import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, Tier, User, gen_id
from .common import card_out, optional_user
from .security import get_current_user
from .prono import now_paris
from . import game_logic, missions, offers, push, chat

router = APIRouter()
MIN_MINUTES, MAX_MINUTES = 15, 1440
DURATIONS = [15, 30, 60, 180, 360, 720, 1440]          # les boutons proposés aux vendeurs
MAX_OPEN_PER_SELLER = 5
SNIPE_WINDOW = 120                                      # secondes
ANNOUNCE_TIERS = {"legendaire", "secrete"}              # les ventes de ces raretés sont annoncées dans le chat


def _now() -> datetime:
    return now_paris()


class Auction(Base):
    """Une enchère ouverte (sans clés étrangères : on nettoie à la main quand un compte ou une carte disparaît)."""
    __tablename__ = "auctions"
    id = Column(String, primary_key=True, default=gen_id)
    seller_id = Column(String, nullable=False, index=True)
    card_id = Column(String, nullable=False)
    start_price = Column(Integer, nullable=False)
    current_bid = Column(Integer, nullable=True)
    top_bidder_id = Column(String, nullable=True, index=True)
    bids = Column(Integer, nullable=False, default=0)
    ends_at = Column(DateTime, nullable=False, index=True)       # heure de Paris
    created_at = Column(DateTime, default=datetime.utcnow)


def min_next_bid(a: Auction) -> int:
    return a.start_price if a.current_bid is None else a.current_bid + max(1, math.ceil(a.current_bid * 0.05))


def escrow(db: Session) -> dict:
    """Crédits mis de côté dans les meilleures enchères, par joueur (comptés dans le total public du classement)."""
    out = {}
    for uid, bid in db.query(Auction.top_bidder_id, Auction.current_bid).filter(Auction.top_bidder_id.isnot(None)).all():
        out[uid] = out.get(uid, 0) + (bid or 0)
    return out


def _tell(db, user_id, title, body):
    try:
        push.enqueue(db, user_id, "market", title, body, url="/#marche", tag="auction")
    except Exception:
        pass


def _settle(db: Session, a: Auction) -> None:
    card = db.get(Card, a.card_id); seller = db.get(User, a.seller_id); winner = db.get(User, a.top_bidder_id) if a.top_bidder_id else None
    name = offers._name(card) if card else "une carte"
    if winner is not None and a.current_bid is not None and card is not None and seller is not None:
        seller.credits += a.current_bid
        game_logic.get_or_create_owned(db, winner, card).quantity += 1
        db.add(offers.Trade(kind="enchère", seller_id=seller.id, buyer_id=winner.id, seller_pseudo=seller.pseudo, buyer_pseudo=winner.pseudo, card_id=card.id, card_tier=card.tier.value, price=a.current_bid))
        _tell(db, winner.id, "Enchère remportée 🔨", "Tu remportes %s pour %d crédits." % (name, a.current_bid))
        _tell(db, seller.id, "Enchère terminée 💰", "%s remporte %s pour %d crédits." % (winner.pseudo, name, a.current_bid))
        if card.tier.value in ANNOUNCE_TIERS:
            chat.add_event(db, "🔨 %s remporte %s (%s) aux enchères pour %d crédits !" % (winner.pseudo, name, card.tier.value, a.current_bid), winner)
        won = winner.id
    else:
        if winner is not None and a.current_bid:
            winner.credits += a.current_bid                       # (le vendeur ou la carte a disparu : on rembourse)
        if seller is not None and card is not None:
            game_logic.get_or_create_owned(db, seller, card).quantity += 1
            _tell(db, seller.id, "Enchère terminée", "Personne n'a enchéri sur %s : la carte est revenue dans ta collection." % name)
        won = None
    seller_id = a.seller_id
    db.delete(a)
    return won, seller_id


def settle_due(db: Session) -> int:
    n = 0
    for a in db.query(Auction).filter(Auction.ends_at <= _now()).all():
        won, seller_id = _settle(db, a); db.commit(); n += 1
        if won:
            missions.safe_record(db, db.get(User, won), "market_buy")
    return n


def tick(db: Session) -> None:
    settle_due(db)


def cancel_for_cards(db: Session, card_ids: list) -> int:
    """Une carte disparaît du jeu : ses enchères sont annulées et le meilleur enchérisseur remboursé."""
    n = 0
    for a in db.query(Auction).filter(Auction.card_id.in_(card_ids)).all():
        if a.top_bidder_id:
            u = db.get(User, a.top_bidder_id)
            if u:
                u.credits += a.current_bid or 0
        db.delete(a); n += 1
    return n


def on_user_deleted(db: Session, user_id: str) -> None:
    for a in db.query(Auction).filter(Auction.seller_id == user_id).all():       # ses enchères : annulées, le meilleur enchérisseur remboursé
        if a.top_bidder_id:
            u = db.get(User, a.top_bidder_id)
            if u:
                u.credits += a.current_bid or 0
        db.delete(a)
    for a in db.query(Auction).filter(Auction.top_bidder_id == user_id).all():   # ses enchères en tête : l'enchère repart sans mise
        a.top_bidder_id, a.current_bid, a.bids = None, None, 0


def _out(a: Auction, card: Card, seller: User, bidder, now: datetime, viewer=None) -> dict:
    return {"id": a.id, "card": card_out(card), "seller_pseudo": seller.pseudo if seller else "?", "start_price": a.start_price, "current_bid": a.current_bid, "bids": a.bids,
            "top_bidder": bidder.pseudo if bidder else None, "min_next_bid": min_next_bid(a), "seconds_left": max(0, int((a.ends_at - now).total_seconds())),
            "mine": bool(viewer and a.seller_id == viewer.id), "i_am_top": bool(viewer and a.top_bidder_id == viewer.id)}


@router.get("/auctions")
def list_auctions(viewer=Depends(optional_user), db: Session = Depends(get_db)):
    settle_due(db); now = _now(); out = []
    for a in db.query(Auction).order_by(Auction.ends_at).all():
        card = db.get(Card, a.card_id)
        if card is None:
            continue
        out.append(_out(a, card, db.get(User, a.seller_id), db.get(User, a.top_bidder_id) if a.top_bidder_id else None, now, viewer))
    return {"durations": DURATIONS, "min_minutes": MIN_MINUTES, "max_minutes": MAX_MINUTES, "auctions": out}


class CreateAuction(BaseModel):
    card_id: str
    start_price: int = Field(ge=1, le=offers.PRICE_MAX)
    minutes: int = Field(ge=MIN_MINUTES, le=MAX_MINUTES)


class BidRequest(BaseModel):
    amount: int = Field(ge=1, le=offers.PRICE_MAX * 10)


@router.post("/auctions")
def create_auction(payload: CreateAuction, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .models import OwnedCard
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=payload.card_id).first()
    if not owned or owned.quantity < 1:
        raise HTTPException(status_code=400, detail="Tu ne possèdes pas cette carte")
    if owned.card.tier in (Tier.commune, Tier.saison):
        raise HTTPException(status_code=400, detail="Les enchères sont réservées aux cartes rares ou mieux (ni communes, ni trophées)")
    if db.query(Auction).filter_by(seller_id=user.id).count() >= MAX_OPEN_PER_SELLER:
        raise HTTPException(status_code=400, detail="Tu as déjà %d enchères ouvertes : attends qu'une se termine" % MAX_OPEN_PER_SELLER)
    owned.quantity -= 1                                           # la carte est mise de côté tant que l'enchère est ouverte
    a = Auction(seller_id=user.id, card_id=payload.card_id, start_price=payload.start_price, ends_at=_now() + timedelta(minutes=payload.minutes))
    db.add(a); db.commit()
    missions.safe_record(db, user, "market_list")
    return {"id": a.id, "seconds_left": payload.minutes * 60}


@router.post("/auctions/{auction_id}/bid")
def bid(auction_id: str, payload: BidRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settle_due(db); a = db.get(Auction, auction_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Cette enchère est terminée ou n'existe plus")
    if a.seller_id == user.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas enchérir sur ta propre carte")
    need = min_next_bid(a)
    if payload.amount < need:
        raise HTTPException(status_code=400, detail="Ton enchère doit être d'au moins %d crédits" % need)
    extra = payload.amount - (a.current_bid or 0) if a.top_bidder_id == user.id else payload.amount
    if user.credits < extra:
        raise HTTPException(status_code=400, detail="Pas assez de crédits (il t'en faut %d)" % extra)
    card = db.get(Card, a.card_id)
    if a.top_bidder_id and a.top_bidder_id != user.id:            # le précédent meilleur enchérisseur est remboursé tout de suite
        prev = db.get(User, a.top_bidder_id)
        if prev:
            prev.credits += a.current_bid or 0
            _tell(db, prev.id, "Tu as été dépassé 🔨", "%s a enchéri %d crédits sur %s. Ton argent t'a été rendu." % (user.pseudo, payload.amount, offers._name(card)))
    user.credits -= extra
    a.current_bid, a.top_bidder_id, a.bids = payload.amount, user.id, (a.bids or 0) + 1
    if (a.ends_at - _now()).total_seconds() < SNIPE_WINDOW:
        a.ends_at = _now() + timedelta(seconds=SNIPE_WINDOW)      # prolongation anti-« dernière seconde »
    db.commit()
    return {"status": "ok", "credits": user.credits, "current_bid": a.current_bid, "min_next_bid": min_next_bid(a), "seconds_left": max(0, int((a.ends_at - _now()).total_seconds()))}


@router.delete("/auctions/{auction_id}")
def cancel(auction_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settle_due(db); a = db.get(Auction, auction_id)
    if a is None or a.seller_id != user.id:
        raise HTTPException(status_code=404, detail="Enchère introuvable")
    if a.bids:
        raise HTTPException(status_code=400, detail="Il y a déjà une enchère : tu ne peux plus annuler")
    game_logic.get_or_create_owned(db, user, db.get(Card, a.card_id)).quantity += 1
    db.delete(a); db.commit()
    return {"status": "ok"}
