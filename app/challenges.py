"""
Défi adressé à un joueur précis (et revanche en un clic).

Un défi « privé » est un défi normal (mise, équipe, enveloppe…) avec, en plus, le joueur à qui il s'adresse :
  - il n'apparaît dans la liste que pour son créateur et pour le joueur défié (les autres ne le voient pas) ;
  - seul le joueur défié peut le jouer ;
  - le joueur défié reçoit une notification ;
  - le créateur peut l'annuler quand il veut (sa mise lui est rendue, comme pour tout défi).
La « revanche » du site n'est qu'un défi privé adressé à son dernier adversaire, avec la même mise.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import MatchProposal, User
from . import duel_engine, push, schemas
from .common import optional_user, require_admin
from .security import get_current_user

router = APIRouter()


class DirectChallenge(Base):
    """Un défi réservé : l'identifiant du défi et celui du joueur défié (volontairement sans clés étrangères)."""
    __tablename__ = "direct_challenges"
    proposal_id = Column(String, primary_key=True)
    target_id = Column(String, nullable=False)


class TargetedCreateRequest(schemas.CreateProposalRequest):
    target: Optional[str] = None       # pseudo du joueur défié ; absent = défi public


class AdminCancelProposalRequest(BaseModel):
    proposal_id: str


def resolve_target(db: Session, user: User, pseudo: Optional[str]):
    """Le joueur défié, ou None pour un défi public. Lève une erreur claire si le pseudo ne convient pas."""
    pseudo = (pseudo or "").strip()
    if not pseudo:
        return None
    target = db.query(User).filter_by(pseudo=pseudo).first()
    if target is None:
        raise HTTPException(status_code=400, detail="Ce joueur n'existe pas : vérifie son pseudo")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas te défier toi-même")
    return target


def attach(db: Session, proposal, target: User) -> None:
    db.add(DirectChallenge(proposal_id=proposal.id, target_id=target.id))
    db.commit()


def notify(db: Session, creator: User, target: User, stake: int) -> None:
    push.enqueue(db, target.id, "duels", "%s te défie ! ⚔️" % creator.pseudo,
                 "Mise de %d crédit%s. Relève le défi dans l'onglet Matchs 1v1." % (stake, "s" if stake > 1 else ""), url="/#duels", tag="duel-direct")


def filter_proposals(db: Session, rows: list, viewer) -> list:
    """La liste des défis telle que la voit `viewer` : les défis privés ne sont visibles que de leur créateur et du joueur défié."""
    targets = {d.proposal_id: d.target_id for d in db.query(DirectChallenge).all()}
    if not targets:
        return rows
    alive = {r["id"] for r in rows}
    for pid in [p for p in targets if p not in alive]:           # ménage : défis déjà joués ou annulés
        db.query(DirectChallenge).filter_by(proposal_id=pid).delete()
    db.commit()
    names = {u.id: u.pseudo for u in db.query(User).filter(User.id.in_(set(targets.values()))).all()}
    out = []
    for r in rows:
        tid = targets.get(r["id"])
        if tid is None:
            out.append(r)
            continue
        mine = viewer is not None and (viewer.pseudo == r["creator"] or viewer.id == tid)
        if mine:
            out.append({**r, "target": names.get(tid), "target_is_me": viewer.id == tid})
    return out


def check_no_trophy(db: Session, slots) -> None:
    """Un trophée de saison n'est qu'un souvenir : il ne peut jouer aucun match."""
    from .models import Card, Tier
    ids = [s.card_id for s in slots if getattr(s, "card_id", None)]
    if ids and db.query(Card).filter(Card.id.in_(ids), Card.tier == Tier.saison).first() is not None:
        raise HTTPException(status_code=400, detail="Un trophée de saison ne peut pas jouer de match : c'est un souvenir")


def check_can_play(db: Session, user: User, proposal_id: str) -> None:
    """Refuse de jouer un défi réservé à quelqu'un d'autre."""
    d = db.query(DirectChallenge).filter_by(proposal_id=proposal_id).first()
    if d is not None and d.target_id != user.id:
        target = db.query(User).filter_by(id=d.target_id).first()
        raise HTTPException(status_code=403, detail="Ce défi est réservé à %s" % (target.pseudo if target else "un autre joueur"))


@router.get("/duel/opponents")
def opponents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Les joueurs que je peux défier en particulier (pas moi, pas les comptes de test)."""
    rows = db.query(User).filter(User.id != user.id, User.is_test == False).order_by(User.pseudo).all()      # noqa: E712
    return [{"pseudo": u.pseudo, "elo": u.elo} for u in rows]


@router.get("/admin/proposals", dependencies=[Depends(require_admin)])
def admin_list_proposals(db: Session = Depends(get_db)):
    """Tous les défis ouverts (y compris les défis privés), avec les crédits qu'ils bloquent."""
    targets = {d.proposal_id: d.target_id for d in db.query(DirectChallenge).all()}
    names = {u.id: u.pseudo for u in db.query(User).all()}
    return [{"id": p.id, "creator": p.creator.pseudo, "stake": p.stake, "referee_bid": p.referee_bid or 0, "target": names.get(targets.get(p.id)),
             "created_at": p.created_at.isoformat()} for p in db.query(MatchProposal).order_by(MatchProposal.created_at.desc()).all()]


@router.post("/admin/cancel-proposal", dependencies=[Depends(require_admin)])
def admin_cancel_proposal(payload: AdminCancelProposalRequest, db: Session = Depends(get_db)):
    """Annule un défi ouvert et rend à son créateur sa mise et son enveloppe."""
    p = db.query(MatchProposal).filter_by(id=payload.proposal_id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Défi introuvable")
    who, refund = p.creator.pseudo, p.stake + (p.referee_bid or 0)
    duel_engine.cancel_proposal(db, p)
    db.query(DirectChallenge).filter_by(proposal_id=payload.proposal_id).delete()
    db.commit()
    return {"status": "ok", "creator": who, "refunded": refund}
