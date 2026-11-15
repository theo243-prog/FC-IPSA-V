"""
Cartes de la communauté (14/11/2026, fonction en essai « communaute », voir features.py) : les joueurs proposent des cartes, l'administration
les trie, et chaque jour un vote choisit celle qui sort.

- Proposer : un nom de carte (NAME_MAX caractères) et la description de l'image voulue (DESC_MAX), sans limite par jour. Un nom déjà pris
  (joueur ou carte, sans tenir compte des majuscules) ou déjà proposé et en attente est refusé.
- Trier (administration) : chaque proposition attend (« pending ») ; l'admin l'accepte (en corrigeant le nom s'il le veut) ou la refuse
  (avec une raison facultative). Seules les propositions acceptées entrent dans le vote. L'auteur reçoit une notification.
- Voter : chaque compte qui a accès donne UNE voix par jour à une proposition acceptée (pas la sienne), modifiable jusqu'à la clôture.
  Le vote du jour J se termine à CLOSE_HOUR (20 h, heure de Paris) ; une voix donnée après 20 h compte pour le lendemain. Les voix sont
  secrètes pendant le vote (seuls l'admin et le résultat les montrent).
- Résultat (tâche de fond `tick`, une fois par jour grâce à la table community_releases) : la proposition qui a le plus de voix sort, à
  égalité la plus ancienne. Sans aucune voix, rien ne sort (les propositions restent en stock). Les autres restent en lice.
- La carte : une fiche de poste réservé COMMUNAUTE (card_kind « communaute ») au nom de la proposition, `proposed_by` = pseudo de l'auteur
  (affiché en bas de la carte, à la place de la note, et sur la fiche), et UNE carte de rareté `communaute` (entre commune et rare, chance réglée carte par carte, voir
  game_logic.community_tier_weights). Carte de collection : elle ne joue pas, n'a ni note, ni niveau, ni secrète, ni Édition Noire.
  L'auteur la reçoit d'office. Pas d'image à la création : l'admin l'ajoute ensuite (« Photo d'un joueur ») d'après la description.
- Pendant l'essai : les routes refusent les comptes sans accès (403), les cartes ne sortent des packs que pour eux et ne comptent pas dans
  le % de collection. Rien n'est annoncé dans le chat. Vérifié par tests/test_communaute.py.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, Player, Tier, User
from .common import require_admin
from .security import get_current_user
from . import features, game_logic, push

router = APIRouter()
FEATURE = "communaute"
POSTE = "COMMUNAUTE"
CLOSE_HOUR = 20                  # fin du vote du jour, heure de Paris
NAME_MIN, NAME_MAX = 2, 60
DESC_MIN, DESC_MAX = 3, 300
HISTORY = 15                     # cartes déjà sorties montrées sur la page


class CommunityProposal(Base):
    """Une proposition de carte (sans clé étrangère vers l'utilisateur : nettoyée à la main à la suppression d'un compte)."""
    __tablename__ = "community_proposals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False)              # pseudo au moment de la proposition
    name = Column(String, nullable=False)
    image_desc = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending")      # pending, accepted, refused, released
    reason = Column(String, nullable=True)               # raison d'un refus (facultative)
    card_id = Column(String, nullable=True)              # carte créée (released)
    released_day = Column(String, nullable=True)         # AAAA-MM-JJ du vote gagné (vide : sortie par l'admin)
    votes = Column(Integer, nullable=True)               # voix obtenues le jour de sa sortie
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)


class CommunityVote(Base):
    """La voix d'un joueur pour le vote d'un jour (une par jour, modifiable)."""
    __tablename__ = "community_votes"
    __table_args__ = (UniqueConstraint("day", "user_id", name="uq_community_vote"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(String, nullable=False, index=True)     # AAAA-MM-JJ du jour du vote (il se termine ce jour-là à 20 h)
    user_id = Column(String, nullable=False, index=True)
    proposal_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CommunityRelease(Base):
    """Le résultat d'un jour : une ligne par jour (verrou : jamais deux sorties pour le même vote)."""
    __tablename__ = "community_releases"
    day = Column(String, primary_key=True)
    proposal_id = Column(Integer, nullable=True)         # vide : aucune voix ce jour-là
    votes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProposeRequest(BaseModel):
    name: str
    image_desc: str


class VoteRequest(BaseModel):
    proposal_id: int


class WithdrawRequest(BaseModel):
    proposal_id: int


class ReviewRequest(BaseModel):
    proposal_id: int
    decision: str                                        # accept / refuse
    name: Optional[str] = None                           # nom corrigé (accept)
    reason: Optional[str] = None                         # raison du refus


class ReleaseRequest(BaseModel):
    proposal_id: int


# ------------------------------------------------------------------ temps
def now_paris() -> datetime:
    from .prono import now_paris as _now                 # (FC_FAKE_NOW dans les tests)
    return _now()


def vote_day(now: datetime = None) -> str:
    """Le jour du vote en cours : aujourd'hui avant 20 h, demain après."""
    now = now or now_paris()
    d = now.date() + (timedelta(days=1) if now.hour >= CLOSE_HOUR else timedelta(0))
    return d.isoformat()


def closes_at(day: str) -> str:
    return "%sT%02d:00:00" % (day, CLOSE_HOUR)


# ------------------------------------------------------------------ outils
def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _taken_names(db: Session, skip_id: int = None) -> set:
    names = {n.casefold() for (n,) in db.query(Player.name).all()}
    for p in db.query(CommunityProposal).filter(CommunityProposal.status.in_(["pending", "accepted"])).all():
        if p.id != skip_id:
            names.add(p.name.casefold())
    return names


def _check_name(db: Session, name: str, skip_id: int = None) -> str:
    name = _clean(name)
    if len(name) < NAME_MIN or len(name) > NAME_MAX:
        raise HTTPException(status_code=400, detail="Le nom de la carte doit faire de %d à %d caractères" % (NAME_MIN, NAME_MAX))
    if name.casefold() in _taken_names(db, skip_id):
        raise HTTPException(status_code=400, detail="« %s » existe déjà (carte ou proposition) : choisis un autre nom" % name)
    return name


def _proposal_out(p: CommunityProposal, mine: bool = False) -> dict:
    out = {"id": p.id, "name": p.name, "author": p.author, "image_desc": p.image_desc, "status": p.status,
           "created_at": p.created_at.isoformat() if p.created_at else None}
    if mine:
        out["reason"] = p.reason
    if p.status == "released":
        out.update(card_id=p.card_id, released_day=p.released_day, votes=p.votes)
    return out


def _require(db: Session, user: User) -> None:
    features.require(db, user, FEATURE, "Les cartes de la communauté ne sont pas encore ouvertes")


def tally(db: Session, day: str) -> dict:
    """{proposition: voix} du vote d'un jour, propositions encore acceptées seulement."""
    ok = {p.id for p in db.query(CommunityProposal.id).filter_by(status="accepted").all()}
    rows = db.query(CommunityVote.proposal_id, func.count(CommunityVote.id)).filter_by(day=day).group_by(CommunityVote.proposal_id).all()
    return {pid: n for pid, n in rows if pid in ok}


# ------------------------------------------------------------------ sortie d'une carte
def release(db: Session, proposal: CommunityProposal, day: str = None, votes: int = None) -> Card:
    """Crée la carte d'une proposition acceptée et la donne à son auteur (sans commit). Le nom est revérifié : refus s'il est pris."""
    if proposal.status != "accepted":
        raise HTTPException(status_code=400, detail="Seule une proposition acceptée peut sortir")
    if proposal.name.casefold() in {n.casefold() for (n,) in db.query(Player.name).all()}:
        raise HTTPException(status_code=400, detail="« %s » existe déjà comme carte : corrige le nom de la proposition" % proposal.name)
    player = Player(name=proposal.name, poste=POSTE, photo_url=None, proposed_by=proposal.author, unique_card=True)
    db.add(player)
    db.flush()
    card = Card(player_id=player.id, tier=Tier.communaute, vitesse=0, tir=0)
    db.add(card)
    db.flush()
    proposal.status, proposal.card_id, proposal.released_day, proposal.votes = "released", card.id, day, votes
    proposal.released_at = datetime.utcnow()
    author = db.get(User, proposal.user_id)
    if author is not None:
        owned = game_logic.get_or_create_owned(db, author, card)
        owned.quantity += 1
        push.safe(db, push.enqueue, author.id, "communaute", "Ta carte est sortie ! 💡",
                  "« %s » est maintenant une carte de la communauté : elle est dans ta collection." % proposal.name, url="/#collection")
    return card


def close_day(db: Session, day: str) -> Optional[CommunityRelease]:
    """Clôt le vote d'un jour (une seule fois) : la proposition qui a le plus de voix sort, à égalité la plus ancienne."""
    if db.get(CommunityRelease, day) is not None:
        return None
    row = CommunityRelease(day=day, proposal_id=None, votes=0)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:                               # un autre processus vient de le faire
        db.rollback()
        return None
    counts = tally(db, day)
    taken = {n.casefold() for (n,) in db.query(Player.name).all()}
    for pid, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        p = db.get(CommunityProposal, pid)
        if p is None or p.name.casefold() in taken:      # nom pris entre-temps : la suivante
            continue
        release(db, p, day, n)
        row.proposal_id, row.votes = p.id, n
        break
    db.commit()
    return row


def tick(db: Session) -> None:
    """Tâche de fond : clôt les votes terminés (celui d'hier soir, et ceux d'avant qui auraient des voix sans résultat)."""
    current = vote_day()
    last_closed = (datetime.fromisoformat(current) - timedelta(days=1)).date().isoformat()
    days = {d for (d,) in db.query(CommunityVote.day).filter(CommunityVote.day < current).distinct().all()} | {last_closed}
    done = {d for (d,) in db.query(CommunityRelease.day).filter(CommunityRelease.day.in_(list(days))).all()}
    for d in sorted(days - done):
        close_day(db, d)


# ------------------------------------------------------------------ routes des joueurs
@router.get("/communaute")
def page(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require(db, user)
    day = vote_day()
    mine_vote = db.query(CommunityVote).filter_by(day=day, user_id=user.id).first()
    candidates = db.query(CommunityProposal).filter_by(status="accepted").order_by(CommunityProposal.id).all()
    mine = db.query(CommunityProposal).filter_by(user_id=user.id).order_by(CommunityProposal.id.desc()).all()
    released = db.query(CommunityProposal).filter_by(status="released").order_by(CommunityProposal.released_at.desc(), CommunityProposal.id.desc()).limit(HISTORY).all()
    last = db.query(CommunityRelease).filter(CommunityRelease.day < day).order_by(CommunityRelease.day.desc()).first()
    last_out = None
    if last is not None:
        p = db.get(CommunityProposal, last.proposal_id) if last.proposal_id else None
        last_out = {"day": last.day, "name": p.name if p else None, "author": p.author if p else None, "votes": last.votes}
    return {
        "vote_day": day, "closes_at": closes_at(day), "close_hour": CLOSE_HOUR,
        "voters": db.query(CommunityVote).filter_by(day=day).count(),        # nombre de votants (les voix restent secrètes)
        "my_vote": mine_vote.proposal_id if mine_vote else None,
        "candidates": [{**_proposal_out(p), "mine": p.user_id == user.id} for p in candidates],
        "mine": [_proposal_out(p, mine=True) for p in mine],
        "released": [_proposal_out(p) for p in released],
        "last_result": last_out,
        "limits": {"name_max": NAME_MAX, "desc_max": DESC_MAX},
    }


@router.post("/communaute/propose")
def propose(payload: ProposeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require(db, user)
    name = _check_name(db, payload.name)
    desc = (payload.image_desc or "").strip()
    if len(desc) < DESC_MIN or len(desc) > DESC_MAX:
        raise HTTPException(status_code=400, detail="Décris l'image voulue en %d à %d caractères" % (DESC_MIN, DESC_MAX))
    p = CommunityProposal(user_id=user.id, author=user.pseudo, name=name, image_desc=desc, status="pending")
    db.add(p)
    db.commit()
    return {"status": "ok", "proposal": _proposal_out(p, mine=True)}


@router.post("/communaute/withdraw")
def withdraw(payload: WithdrawRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Retire une de ses propositions pas encore sortie (en attente ou acceptée) ; les voix du jour pour elle sont perdues."""
    _require(db, user)
    p = db.get(CommunityProposal, payload.proposal_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    if p.status not in ("pending", "accepted"):
        raise HTTPException(status_code=400, detail="Cette proposition ne peut plus être retirée")
    db.query(CommunityVote).filter_by(proposal_id=p.id).delete()
    db.delete(p)
    db.commit()
    return {"status": "ok"}


@router.post("/communaute/vote")
def vote(payload: VoteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require(db, user)
    p = db.get(CommunityProposal, payload.proposal_id)
    if p is None or p.status != "accepted":
        raise HTTPException(status_code=404, detail="Cette proposition n'est pas dans le vote")
    if p.user_id == user.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas voter pour ta propre proposition")
    day = vote_day()
    row = db.query(CommunityVote).filter_by(day=day, user_id=user.id).first()
    if row is None:
        db.add(CommunityVote(day=day, user_id=user.id, proposal_id=p.id))
    else:
        row.proposal_id, row.created_at = p.id, datetime.utcnow()
    try:
        db.commit()
    except IntegrityError:                               # deux clics en même temps
        db.rollback()
        db.query(CommunityVote).filter_by(day=day, user_id=user.id).update({"proposal_id": p.id})
        db.commit()
    return {"status": "ok", "vote_day": day, "proposal_id": p.id}


# ------------------------------------------------------------------ administration
@router.get("/admin/communaute", dependencies=[Depends(require_admin)])
def admin_page(db: Session = Depends(get_db)):
    day = vote_day()
    counts = tally(db, day)
    rows = db.query(CommunityProposal).order_by(CommunityProposal.id).all()
    no_photo = {p.id for p in db.query(Player).filter(Player.poste == POSTE).all() if not p.photo_url}
    card_player = {c.id: c.player_id for c in db.query(Card).filter_by(tier=Tier.communaute).all()}
    return {
        "vote_day": day, "closes_at": closes_at(day),
        "pending": [_proposal_out(p, mine=True) for p in rows if p.status == "pending"],
        "accepted": sorted(({**_proposal_out(p), "votes_today": counts.get(p.id, 0)} for p in rows if p.status == "accepted"),
                           key=lambda r: (-r["votes_today"], r["id"])),
        "released": [{**_proposal_out(p), "needs_image": card_player.get(p.card_id) in no_photo} for p in reversed(rows) if p.status == "released"],
        "refused": [_proposal_out(p, mine=True) for p in reversed(rows) if p.status == "refused"][:50],
        "access": features.get(db, FEATURE),
    }


@router.post("/admin/communaute-review", dependencies=[Depends(require_admin)])
def admin_review(payload: ReviewRequest, db: Session = Depends(get_db)):
    """Accepte (nom corrigé possible) ou refuse une proposition en attente. On peut aussi refuser ou renommer une proposition acceptée."""
    p = db.get(CommunityProposal, payload.proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    if p.status not in ("pending", "accepted"):
        raise HTTPException(status_code=400, detail="Cette proposition est déjà %s" % {"refused": "refusée", "released": "sortie"}.get(p.status, p.status))
    decision = (payload.decision or "").strip().lower()
    if decision in ("accept", "accepter"):
        if payload.name and _clean(payload.name) != p.name:
            p.name = _check_name(db, payload.name, skip_id=p.id)
        elif p.name.casefold() in {n.casefold() for (n,) in db.query(Player.name).all()}:
            raise HTTPException(status_code=400, detail="« %s » existe déjà comme carte : donne un autre nom" % p.name)
        was = p.status
        p.status, p.reason, p.reviewed_at = "accepted", None, datetime.utcnow()
        if was == "pending":
            push.safe(db, push.enqueue, p.user_id, "communaute", "Proposition acceptée 💡",
                      "« %s » entre dans le vote de la carte de la communauté." % p.name, url="/#communaute")
    elif decision in ("refuse", "refuser"):
        p.status, p.reason, p.reviewed_at = "refused", (payload.reason or "").strip()[:200] or None, datetime.utcnow()
        db.query(CommunityVote).filter_by(proposal_id=p.id).delete()
        push.safe(db, push.enqueue, p.user_id, "communaute", "Proposition refusée",
                  "« %s » n'a pas été retenue%s." % (p.name, (" : " + p.reason) if p.reason else ""), url="/#communaute")
    else:
        raise HTTPException(status_code=400, detail="decision doit être accept ou refuse")
    db.commit()
    return {"status": "ok", "proposal": _proposal_out(p, mine=True)}


@router.post("/admin/communaute-release", dependencies=[Depends(require_admin)])
def admin_release(payload: ReleaseRequest, db: Session = Depends(get_db)):
    """Sort tout de suite une proposition acceptée, sans attendre le vote (en plus de la carte du jour)."""
    p = db.get(CommunityProposal, payload.proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    card = release(db, p)
    db.query(CommunityVote).filter_by(proposal_id=p.id).delete()
    db.commit()
    return {"status": "ok", "card_id": card.id, "name": p.name, "author": p.author}


def on_cards_deleted(db: Session, card_ids: list) -> None:
    """Carte communauté supprimée (ex. carte de test) : sa proposition disparaît aussi (historique « sorties », nom libéré)."""
    ids = [p.id for p in db.query(CommunityProposal).filter(CommunityProposal.card_id.in_(card_ids)).all()]
    if ids:
        db.query(CommunityVote).filter(CommunityVote.proposal_id.in_(ids)).delete(synchronize_session=False)
        db.query(CommunityProposal).filter(CommunityProposal.id.in_(ids)).delete(synchronize_session=False)


def on_user_deleted(db: Session, user_id: str) -> None:
    """Ses voix et ses propositions pas encore sorties ; les cartes sorties restent (avec son pseudo comme auteur)."""
    db.query(CommunityVote).filter_by(user_id=user_id).delete()
    ids = [p.id for p in db.query(CommunityProposal).filter(CommunityProposal.user_id == user_id, CommunityProposal.status != "released").all()]
    if ids:
        db.query(CommunityVote).filter(CommunityVote.proposal_id.in_(ids)).delete(synchronize_session=False)
        db.query(CommunityProposal).filter(CommunityProposal.id.in_(ids)).delete(synchronize_session=False)
