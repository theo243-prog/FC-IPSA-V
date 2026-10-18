"""
Échange de cartes entre joueurs : une carte contre une carte, sans crédits.

Règle d'or : on ne peut échanger que des DOUBLONS (au moins 2 exemplaires), de chaque côté, pour que personne ne perde une carte de sa
collection. Une proposition reste ouverte 7 jours ; les cartes sont vérifiées à nouveau au moment où elle est acceptée.
Les trophées de saison ne s'échangent jamais.
"""
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, OwnedCard, Tier, User, gen_id
from .security import get_current_user
from . import game_logic, push

router = APIRouter()
MAX_OPEN, EXPIRES_DAYS = 5, 7


class CardSwap(Base):
    """Une proposition d'échange (sans clés étrangères : nettoyage à la main à la suppression d'un compte)."""
    __tablename__ = "card_swaps"
    id = Column(String, primary_key=True, default=gen_id)
    proposer_id = Column(String, nullable=False, index=True)
    target_id = Column(String, nullable=False, index=True)
    give_card_id = Column(String, nullable=False)      # la carte que le proposeur donne
    want_card_id = Column(String, nullable=False)      # la carte qu'il demande en retour
    status = Column(String, nullable=False, default="open")     # open / accepted / declined / cancelled / expired
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class SwapRequest(BaseModel):
    to: str
    give_card_id: str
    want_card_id: str


def _tradeable(card: Card) -> bool:
    return card.tier != Tier.saison and game_logic.card_kind(card.player) != "trophee"


def _qty(db: Session, user_id: str, card_id: str) -> int:
    o = db.query(OwnedCard).filter_by(user_id=user_id, card_id=card_id).first()
    return o.quantity if o else 0


def _cout(card: Card) -> dict:
    from .main import card_out
    c = card_out(card)
    return {"id": c["id"], "player_name": c["player_name"], "tier": c["tier"], "poste": c.get("poste"), "player_photo_url": c.get("player_photo_url"), "display_name": c.get("display_name") or c["player_name"]}


TIER_NAMES = {"commune": "Commune", "rare": "Rare", "epique": "Épique", "legendaire": "Légendaire", "secrete": "Secrète", "speciale": "Spéciale", "gold": "Gold", "halloween": "Halloween", "noel": "Noël"}


def _named(card: Card) -> str:
    return "%s (%s)" % (_cout(card)["display_name"], TIER_NAMES.get(card.tier.value, card.tier.value))


def _expire(db: Session) -> None:
    limit = datetime.utcnow() - timedelta(days=EXPIRES_DAYS)
    for s in db.query(CardSwap).filter(CardSwap.status == "open", CardSwap.created_at < limit).all():
        s.status, s.resolved_at = "expired", datetime.utcnow()
    db.commit()


def _row(db: Session, s: CardSwap, names: dict) -> dict:
    give, want = db.get(Card, s.give_card_id), db.get(Card, s.want_card_id)
    return {"id": s.id, "from": names.get(s.proposer_id, "?"), "to": names.get(s.target_id, "?"), "give": _cout(give) if give else None, "want": _cout(want) if want else None,
            "status": s.status, "created_at": s.created_at.isoformat(), "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None}


@router.get("/swaps/doubles/{pseudo}")
def player_doubles(pseudo: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Les doublons d'un joueur : ce qu'on peut lui demander en échange."""
    target = db.query(User).filter_by(pseudo=pseudo).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    rows = db.query(OwnedCard).filter(OwnedCard.user_id == target.id, OwnedCard.quantity >= 2).all()
    return [{**_cout(o.card), "quantity": o.quantity} for o in rows if _tradeable(o.card)]


@router.get("/swaps")
def my_swaps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Mes propositions reçues et envoyées, plus les derniers échanges réalisés au club."""
    _expire(db)
    names = {u.id: u.pseudo for u in db.query(User).all()}
    incoming = db.query(CardSwap).filter_by(target_id=user.id, status="open").order_by(CardSwap.created_at.desc()).all()
    outgoing = db.query(CardSwap).filter_by(proposer_id=user.id, status="open").order_by(CardSwap.created_at.desc()).all()
    recent = db.query(CardSwap).filter_by(status="accepted").order_by(CardSwap.resolved_at.desc()).limit(10).all()
    return {"incoming": [_row(db, s, names) for s in incoming], "outgoing": [_row(db, s, names) for s in outgoing], "recent": [_row(db, s, names) for s in recent]}


@router.post("/swaps")
def propose_swap(payload: SwapRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _expire(db)
    target = db.query(User).filter_by(pseudo=payload.to).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas échanger avec toi-même")
    give, want = db.get(Card, payload.give_card_id), db.get(Card, payload.want_card_id)
    if give is None or want is None:
        raise HTTPException(status_code=404, detail="Carte introuvable")
    if not (_tradeable(give) and _tradeable(want)):
        raise HTTPException(status_code=400, detail="Les trophées de saison ne s'échangent pas")
    if give.id == want.id:
        raise HTTPException(status_code=400, detail="Propose deux cartes différentes")
    if _qty(db, user.id, give.id) < 2:
        raise HTTPException(status_code=400, detail="Tu ne peux donner qu'un doublon (il t'en faut au moins 2 exemplaires)")
    if _qty(db, target.id, want.id) < 2:
        raise HTTPException(status_code=400, detail="%s n'a pas cette carte en double : choisis parmi ses doublons" % target.pseudo)
    if db.query(CardSwap).filter_by(proposer_id=user.id, status="open").count() >= MAX_OPEN:
        raise HTTPException(status_code=400, detail="Tu as déjà %d propositions ouvertes : annule-en une d'abord" % MAX_OPEN)
    if db.query(CardSwap).filter_by(proposer_id=user.id, target_id=target.id, give_card_id=give.id, want_card_id=want.id, status="open").first():
        raise HTTPException(status_code=400, detail="Cette proposition existe déjà")
    s = CardSwap(proposer_id=user.id, target_id=target.id, give_card_id=give.id, want_card_id=want.id); db.add(s); db.commit()
    push.safe(db, lambda d: push.enqueue(d, target.id, "market", "%s te propose un échange 🔁" % user.pseudo, "Il te donne une carte contre une de tes cartes. Réponds dans l'onglet Marché.", url="/#marche", tag="swap"))
    return {"status": "ok", "id": s.id}


def _mine_open(db: Session, swap_id: str, user_id: str, role: str) -> CardSwap:
    s = db.get(CardSwap, swap_id)
    if s is None or getattr(s, role) != user_id:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    if s.status != "open":
        raise HTTPException(status_code=400, detail="Cette proposition n'est plus ouverte")
    return s


@router.post("/swaps/{swap_id}/accept")
def accept_swap(swap_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _expire(db)
    s = _mine_open(db, swap_id, user.id, "target_id")
    proposer = db.get(User, s.proposer_id)
    give, want = db.get(Card, s.give_card_id), db.get(Card, s.want_card_id)
    if proposer is None or give is None or want is None:
        s.status, s.resolved_at = "cancelled", datetime.utcnow(); db.commit()
        raise HTTPException(status_code=400, detail="Cet échange n'est plus possible")
    if _qty(db, proposer.id, give.id) < 2:
        raise HTTPException(status_code=400, detail="%s n'a plus cette carte en double : l'échange n'est plus possible" % proposer.pseudo)
    if _qty(db, user.id, want.id) < 2:
        raise HTTPException(status_code=400, detail="Tu n'as plus cette carte en double : l'échange n'est plus possible")
    game_logic.get_or_create_owned(db, proposer, give).quantity -= 1
    game_logic.get_or_create_owned(db, user, want).quantity -= 1
    game_logic.get_or_create_owned(db, proposer, want).quantity += 1
    game_logic.get_or_create_owned(db, user, give).quantity += 1
    s.status, s.resolved_at = "accepted", datetime.utcnow()
    from . import battlepass, chat
    battlepass.add_points(db, proposer, "swap", 15, battlepass.DAILY_CAPS["swap"]); battlepass.add_points(db, user, "swap", 15, battlepass.DAILY_CAPS["swap"])      # Pass de saison
    chat.add_event(db, "🔁 %s et %s ont échangé des cartes : %s contre %s" % (proposer.pseudo, user.pseudo, _named(give), _named(want)))
    db.commit()
    push.safe(db, lambda d: push.enqueue(d, proposer.id, "market", "Échange accepté 🔁", "%s a accepté ton échange." % user.pseudo, url="/#marche", tag="swap"))
    return {"status": "ok", "gave": _cout(want), "got": _cout(give)}


@router.post("/swaps/{swap_id}/decline")
def decline_swap(swap_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _mine_open(db, swap_id, user.id, "target_id")
    s.status, s.resolved_at = "declined", datetime.utcnow(); db.commit()
    return {"status": "ok"}


@router.delete("/swaps/{swap_id}")
def cancel_swap(swap_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _mine_open(db, swap_id, user.id, "proposer_id")
    s.status, s.resolved_at = "cancelled", datetime.utcnow(); db.commit()
    return {"status": "ok"}
