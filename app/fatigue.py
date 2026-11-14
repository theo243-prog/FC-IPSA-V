"""
Forme des cartes en 1v1. Depuis le 14/11/2026 (branche fatigue-recuperation) : chaque carte utilisée dans un match 1v1 (les 5 joueurs, le Fan,
le Loup et l'équipement) coûte FORM_LOSS_PER_MATCH (0,5 %, avant 1 %) de forme à sa PERSONNE, et la forme REMONTE EN CONTINU de
RECOVERY_PER_HOUR (1 % par heure), au lieu de revenir à 100 % à minuit. La forme multiplie la note d'un joueur (note + niveau, puis forme,
puis malus hors poste et capitaine) et le bonus d'un Fan (le Loup et l'équipement n'ont plus de bonus de puissance).
L'ÉQUIPEMENT réduit la perte de forme de toutes les cartes du match (game_logic.equipment_fatigue_reduction : -5 % à -25 %, plus ses niveaux).
But : faire tourner les cartes pendant une session (le gardien compris), sans punir ceux qui reviennent jouer plus tard.

- « Dette de fatigue » par joueur du site et PAR PERSONNE (table person_fatigue, en centièmes de % : 50 = 0,5 %) : toutes les versions d'une
  même personne (commune, rare, édition, spéciale…) partagent la même forme. Deux joueurs du site différents ont chacun la leur.
- À la lecture, la dette baisse de RECOVERY_PER_HOUR par heure écoulée depuis le dernier match (jamais sous 0) ; un match l'augmente
  ensuite de la perte de chaque carte alignée de cette personne. La forme = 100 % - dette, jamais sous MIN_FORM (50 %).
- Seul le 1v1 compte et fatigue : le tournoi et le défi du club jouent toujours à 100 % (et ne fatiguent pas).
- Les deux équipes d'un défi se fatiguent : celle du créateur et celle du challenger, au moment où le match est joué.
- L'ancienne table card_fatigue (perte du jour, remise à zéro à minuit) n'est plus utilisée : au passage au nouveau système, tout le monde
  repart à 100 %.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from .database import Base
from .models import Card
from . import game_logic

FORM_LOSS_PER_MATCH = 0.005      # 0,5 % de forme en moins par match 1v1 joué (avant le 14/11/2026 : 1 %)
RECOVERY_PER_HOUR = 0.01         # la forme remonte de 1 % par heure, en continu (avant : retour à 100 % à minuit)
MIN_FORM = 0.50                  # plancher : une carte n'est jamais sous 50 % de forme
_now = datetime.utcnow           # (remplaçable dans les tests)


class CardFatigue(Base):
    """ANCIEN système (jusqu'au 13/11/2026) : perte de forme du jour par carte, remise à zéro à minuit. Gardée en base, plus lue."""
    __tablename__ = "card_fatigue"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_card_fatigue"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    card_id = Column(String, nullable=False, index=True)
    day = Column(String, nullable=False)
    matches = Column(Integer, nullable=False, default=0)
    loss = Column(Integer, nullable=True)


class PersonFatigue(Base):
    """Dette de fatigue d'une personne (vrai joueur, fan, Loup, équipement) pour un joueur du site, au moment `updated_at` (UTC)."""
    __tablename__ = "person_fatigue"
    __table_args__ = (UniqueConstraint("user_id", "player_id", name="uq_person_fatigue"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    player_id = Column(String, nullable=False, index=True)
    debt = Column(Integer, nullable=False, default=0)      # en centièmes de % (50 = 0,5 %)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def loss_per_match(reduction: float = 0.0) -> int:
    """Perte de forme d'un match en centièmes de % : 50 (0,5 %) sans équipement, moins la réduction de l'équipement (jamais négative)."""
    return int(round(FORM_LOSS_PER_MATCH * 10000 * (1 - max(0.0, min(1.0, reduction)))))


def form_from_loss(loss: int) -> float:
    return max(MIN_FORM, 1.0 - max(0, loss) / 10000)


def form_from_matches(matches: int) -> float:
    return form_from_loss(int(round(max(0, matches) * FORM_LOSS_PER_MATCH * 10000)))


def debt_now(row: PersonFatigue, now: datetime = None) -> float:
    """La dette de fatigue à l'instant `now`, après la récupération de 1 % par heure depuis le dernier match (en centièmes de %)."""
    hours = max(0.0, ((now or _now()) - row.updated_at).total_seconds() / 3600)
    return max(0.0, row.debt - RECOVERY_PER_HOUR * 10000 * hours)


def _debts(db: Session, user_id: str, now=None) -> dict:
    return {r.player_id: d for r in db.query(PersonFatigue).filter_by(user_id=user_id).all() for d in [debt_now(r, now)] if d > 0}


def forms_for(db: Session, user_id: str, now=None) -> dict:
    """{carte: forme entre 0,5 et 1} des cartes d'un joueur dont la PERSONNE est encore fatiguée (les autres sont à 100 %)."""
    debts = _debts(db, user_id, now)
    if not debts:
        return {}
    return {cid: form_from_loss(debts[pid]) for cid, pid in db.query(Card.id, Card.player_id).filter(Card.player_id.in_(list(debts))).all()}


def recovery_for(db: Session, user_id: str, now=None) -> dict:
    """{carte: minutes avant de retrouver 100 %} pour les cartes encore fatiguées d'un joueur."""
    debts = _debts(db, user_id, now)
    if not debts:
        return {}
    per_min = RECOVERY_PER_HOUR * 10000 / 60
    return {cid: int(-(-debts[pid] // per_min)) for cid, pid in db.query(Card.id, Card.player_id).filter(Card.player_id.in_(list(debts))).all()}


def record_match(db: Session, user_id: str, card_ids, reduction: float = 0.0, now=None) -> None:
    """Un match 1v1 vient d'être joué avec ces cartes : chaque carte coûte 0,5 % de forme à sa personne (moins la réduction de l'équipement),
    après la récupération écoulée depuis le dernier match. Sans commit."""
    now = now or _now()
    step = loss_per_match(reduction)
    person = dict(db.query(Card.id, Card.player_id).filter(Card.id.in_(list(set(card_ids)))).all()) if card_ids else {}
    added = {}
    for cid in set(card_ids):
        pid = person.get(cid)
        if pid is not None:
            added[pid] = added.get(pid, 0) + step
    for pid, extra in added.items():
        row = db.query(PersonFatigue).filter_by(user_id=user_id, player_id=pid).first()
        if row is None:
            db.add(PersonFatigue(user_id=user_id, player_id=pid, debt=extra, updated_at=now))
            continue
        row.debt = int(round(debt_now(row, now))) + extra
        row.updated_at = now


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(CardFatigue).filter_by(user_id=user_id).delete()
    db.query(PersonFatigue).filter_by(user_id=user_id).delete()


def on_cards_deleted(db: Session, card_ids) -> None:
    if card_ids:
        db.query(CardFatigue).filter(CardFatigue.card_id.in_(list(card_ids))).delete(synchronize_session=False)
