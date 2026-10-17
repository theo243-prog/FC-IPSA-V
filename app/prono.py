"""
Pronostics sur les vrais matchs du club.

Avant un match réel (ceux de l'onglet Actualité), chaque joueur peut miser des crédits sur le score. Les mises forment une CAGNOTTE ;
quand l'administrateur enregistre le résultat, elle est partagée entre les bons pronostics :
  - SCORE EXACT : 70 % de la cagnotte, partagée entre les scores exacts au prorata des mises ;
  - BON RÉSULTAT (victoire / nul / défaite) sans le bon score : les 30 % restants, partagés de la même façon ;
  - s'il n'y a aucun score exact, les bons résultats se partagent toute la cagnotte, et inversement ;
  - si personne n'a trouvé le résultat, tout le monde est remboursé.
L'administrateur peut ajouter un BONUS du club à la cagnotte. Les pronostics ferment au coup d'envoi (à midi si l'heure n'est pas indiquée).
Un match supprimé sans résultat rembourse tout le monde.
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, func
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import AppSetting, UpcomingMatch, User, gen_id
from .common import require_admin
from .security import get_current_user
from . import profiles, push

router = APIRouter()
MAX_STAKE, MAX_SCORE, EXACT_SHARE = 50, 30, 0.7


class PronoBet(Base):
    """Un pronostic. Gardé après le match (avec le nom du match) pour l'historique ; sans clés étrangères."""
    __tablename__ = "prono_bets"
    id = Column(String, primary_key=True, default=gen_id)
    upcoming_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    score_us = Column(Integer, nullable=False)
    score_them = Column(Integer, nullable=False)
    stake = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="open")      # open / won / lost / refunded
    payout = Column(Integer, nullable=False, default=0)
    exact = Column(Integer, nullable=False, default=0)
    match_label = Column(String, nullable=False)
    match_date = Column(String, nullable=False)
    result = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BetRequest(BaseModel):
    upcoming_id: str
    score_us: int = Field(ge=0, le=MAX_SCORE)
    score_them: int = Field(ge=0, le=MAX_SCORE)
    stake: int = Field(ge=1, le=MAX_STAKE)


class BonusRequest(BaseModel):
    upcoming_id: str
    bonus: int = Field(ge=0, le=5000)


def now_paris() -> datetime:
    fake = os.getenv("FC_FAKE_NOW")                     # (tests seulement : fige l'horloge, ex. 2026-11-08T13:00:00 ; jamais défini en production)
    if fake:
        return datetime.fromisoformat(fake)
    return datetime.now(ZoneInfo("Europe/Paris")).replace(tzinfo=None)


def closes_at(m: UpcomingMatch) -> datetime:
    """Coup d'envoi ; sans heure indiquée, les pronostics ferment à midi le jour du match."""
    return m.date if (m.date.hour or m.date.minute) else m.date.replace(hour=12)


def _label(m: UpcomingMatch) -> str:
    return "FC IPSA V — " + m.opponent


def _bonus(db: Session, upcoming_id: str) -> int:
    row = db.get(AppSetting, "prono_bonus:" + upcoming_id)
    return int(row.value) if row is not None else 0


def _outcome(a: int, b: int) -> int:
    return (a > b) - (a < b)


def _pool_info(db: Session, upcoming_id: str) -> dict:
    bets = db.query(PronoBet).filter_by(upcoming_id=upcoming_id, status="open").all()
    bonus = _bonus(db, upcoming_id)
    return {"bets": len(bets), "pool": sum(b.stake for b in bets) + bonus, "bonus": bonus}


def _bet_out(b: PronoBet) -> dict:
    return {"upcoming_id": b.upcoming_id, "score_us": b.score_us, "score_them": b.score_them, "stake": b.stake, "status": b.status, "payout": b.payout,
            "exact": bool(b.exact), "match": b.match_label, "date": b.match_date, "result": b.result}


@router.get("/prono")
def list_prono(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Les matchs à venir avec leur cagnotte, mon pronostic et si les pronostics sont encore ouverts."""
    now = now_paris(); out = []
    for m in db.query(UpcomingMatch).order_by(UpcomingMatch.date.asc()).all():
        mine = db.query(PronoBet).filter_by(upcoming_id=m.id, user_id=user.id, status="open").first()
        out.append({"id": m.id, "date": m.date.date().isoformat(), "time": m.date.strftime("%H:%M") if (m.date.hour or m.date.minute) else None, "opponent": m.opponent,
                    "open": now < closes_at(m), "closes_at": closes_at(m).isoformat(), **_pool_info(db, m.id), "mine": _bet_out(mine) if mine else None})
    return {"matches": out, "max_stake": MAX_STAKE}


@router.post("/prono")
def place_bet(payload: BetRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(UpcomingMatch, payload.upcoming_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Match introuvable")
    if now_paris() >= closes_at(m):
        raise HTTPException(status_code=400, detail="Les pronostics de ce match sont fermés")
    old = db.query(PronoBet).filter_by(upcoming_id=m.id, user_id=user.id, status="open").first()
    refund = old.stake if old else 0
    if user.credits + refund < payload.stake:
        raise HTTPException(status_code=400, detail="Pas assez de crédits pour miser %d" % payload.stake)
    user.credits += refund - payload.stake
    if old is None:
        db.add(PronoBet(upcoming_id=m.id, user_id=user.id, score_us=payload.score_us, score_them=payload.score_them, stake=payload.stake, match_label=_label(m), match_date=m.date.date().isoformat()))
    else:
        old.score_us, old.score_them, old.stake = payload.score_us, payload.score_them, payload.stake
    db.commit()
    return {"status": "ok", "credits_total": user.credits, **_pool_info(db, m.id)}


@router.delete("/prono/{upcoming_id}")
def cancel_bet(upcoming_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(UpcomingMatch, upcoming_id)
    bet = db.query(PronoBet).filter_by(upcoming_id=upcoming_id, user_id=user.id, status="open").first()
    if bet is None:
        raise HTTPException(status_code=404, detail="Tu n'as pas de pronostic sur ce match")
    if m is not None and now_paris() >= closes_at(m):
        raise HTTPException(status_code=400, detail="Les pronostics de ce match sont fermés : la mise reste engagée")
    user.credits += bet.stake
    db.delete(bet); db.commit()
    return {"status": "ok", "credits_total": user.credits}


@router.get("/prono/mine")
def my_bets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(PronoBet).filter_by(user_id=user.id).order_by(PronoBet.created_at.desc()).limit(30).all()
    return [_bet_out(b) for b in rows]


@router.get("/prono/ranking")
def prono_ranking(db: Session = Depends(get_db)):
    """Les meilleurs pronostiqueurs : gain net (gains moins mises) sur les pronostics réglés."""
    users = {u.id: u for u in db.query(User).filter(User.is_test == False).all()}       # noqa: E712
    agg = {}
    for b in db.query(PronoBet).filter(PronoBet.status.in_(("won", "lost"))).all():
        if b.user_id not in users:
            continue
        a = agg.setdefault(b.user_id, {"net": 0, "exact": 0, "bets": 0}); a["net"] += b.payout - b.stake; a["exact"] += b.exact; a["bets"] += 1
    rows = sorted(agg.items(), key=lambda kv: (-kv[1]["net"], -kv[1]["exact"], users[kv[0]].pseudo))[:10]
    return [{"pseudo": users[uid].pseudo, **a} for uid, a in rows]


def settle(db: Session, upcoming_id: str, score_us: int, score_them: int):
    """Règle les pronostics d'un match dont le résultat est connu. Ne valide PAS la transaction (l'appelant le fait). Renvoie les annonces à faire."""
    bets = db.query(PronoBet).filter_by(upcoming_id=upcoming_id, status="open").all()
    if not bets:
        return []
    pool = sum(b.stake for b in bets) + _bonus(db, upcoming_id)
    res = _outcome(score_us, score_them); result = "%d-%d" % (score_us, score_them)
    exact = [b for b in bets if b.score_us == score_us and b.score_them == score_them]
    good = [b for b in bets if b not in exact and _outcome(b.score_us, b.score_them) == res]
    shares = []
    if exact and good:
        e = int(pool * EXACT_SHARE); shares = [(exact, e), (good, pool - e)]
    elif exact:
        shares = [(exact, pool)]
    elif good:
        shares = [(good, pool)]
    users = {u.id: u for u in db.query(User).filter(User.id.in_({b.user_id for b in bets})).all()}
    events = []
    if not shares:                                           # personne n'a trouvé le résultat : tout le monde est remboursé
        for b in bets:
            if b.user_id in users: users[b.user_id].credits += b.stake
            b.status, b.payout, b.result = "refunded", b.stake, result
        return []
    paid = set()
    for group, share in shares:
        total = sum(b.stake for b in group); amounts = [share * b.stake // total for b in group]
        amounts[max(range(len(group)), key=lambda i: (group[i].stake, -i))] += share - sum(amounts)     # le reste va à la plus grosse mise
        for b, amount in zip(group, amounts):
            if b.user_id in users: users[b.user_id].credits += amount
            b.status, b.payout, b.result = "won", amount, result; b.exact = 1 if group is exact else 0; paid.add(b.id)
    for b in bets:
        if b.id not in paid:
            b.status, b.payout, b.result = "lost", 0, result
    for b in bets:
        u = users.get(b.user_id)
        if u is None: continue
        profiles.bump(db, u, "prono_placed")
        if b.exact: profiles.bump(db, u, "prono_exact")
        push.safe(db, lambda d, u=u, b=b: push.enqueue(d, u.id, "cards", "Pronostic %s 🎯" % ("gagné" if b.status == "won" else "perdu"), "%s : %s. %s" % (b.match_label, result, ("+%d crédits" % b.payout) if b.status == "won" else "Ce sera pour la prochaine !"), url="/#actualite", tag="prono"))
    from . import chat
    for b in exact:
        if b.user_id in users:
            chat.add_event(db, "🎯 %s a trouvé le score exact de %s (%s) : +%d crédits !" % (users[b.user_id].pseudo, b.match_label, result, b.payout), users[b.user_id])
    return events


def refund_match(db: Session, upcoming_id: str) -> int:
    """Le match est supprimé sans résultat : tous les pronostics ouverts sont remboursés. Ne valide pas la transaction."""
    n = 0
    for b in db.query(PronoBet).filter_by(upcoming_id=upcoming_id, status="open").all():
        u = db.get(User, b.user_id)
        if u is not None: u.credits += b.stake
        b.status, b.payout = "refunded", b.stake; n += 1
    return n


@router.post("/admin/prono-bonus", dependencies=[Depends(require_admin)])
def admin_prono_bonus(payload: BonusRequest, db: Session = Depends(get_db)):
    """Ajoute un BONUS du club à la cagnotte d'un match (des crédits offerts, partagés avec les mises)."""
    m = db.get(UpcomingMatch, payload.upcoming_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Match à venir introuvable")
    key = "prono_bonus:" + m.id; row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=str(payload.bonus)))
    else:
        row.value = str(payload.bonus)
    db.commit()
    return {"status": "ok", "match": _label(m), "bonus": payload.bonus}
