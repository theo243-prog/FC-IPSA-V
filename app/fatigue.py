"""
Forme des cartes en 1v1 : chaque carte utilisée dans un match 1v1 (les 5 joueurs, le Fan, le Loup et l'équipement) perd
FORM_LOSS_PER_MATCH (1 %) de forme ; elle repart à 100 % chaque jour à minuit (heure de Paris). La forme multiplie la note d'un joueur
(note + niveau, puis forme, puis malus hors poste et capitaine) et le bonus d'un Fan (le Loup et l'équipement n'ont plus de bonus de puissance).
L'ÉQUIPEMENT réduit la perte de forme de toutes les cartes du match (game_logic.EQUIPMENT_FATIGUE_REDUCTION : -15 % à -60 %, 60 % au plus).
La perte est comptée en centièmes de point de forme (colonne « loss » : 100 = 1 %) pour rester exacte avec l'équipement.
But : faire tourner les cartes utilisées, y compris le gardien et les bonus.

- Compté par joueur du site et par carte (deux joueurs différents ont chacun leur forme pour la même carte).
- Seul le 1v1 compte et fatigue : le tournoi et le défi du club jouent toujours à 100 % (et ne fatiguent pas).
- Les deux équipes d'un défi se fatiguent : celle du créateur et celle du challenger, au moment où le match est joué.
- La forme ne descend jamais sous MIN_FORM (50 %).
"""
from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from .database import Base
from . import game_logic

FORM_LOSS_PER_MATCH = 0.01       # 1 % de forme en moins par match 1v1 joué
MIN_FORM = 0.50                  # plancher : une carte n'est jamais sous 50 % de forme


class CardFatigue(Base):
    """Matchs 1v1 joués AUJOURD'HUI (jour de Paris) par une carte d'un joueur. Une ligne d'un autre jour ne compte plus."""
    __tablename__ = "card_fatigue"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_card_fatigue"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    card_id = Column(String, nullable=False, index=True)
    day = Column(String, nullable=False)                  # AAAA-MM-JJ (Paris)
    matches = Column(Integer, nullable=False, default=0)
    loss = Column(Integer, nullable=True)                 # perte de forme du jour en centièmes de % (vide : ancienne ligne, = matches x 100)


def _today() -> str:
    return game_logic.today_paris().isoformat()


def form_from_matches(matches: int) -> float:
    return max(MIN_FORM, 1.0 - FORM_LOSS_PER_MATCH * max(0, matches))


def loss_per_match(reduction: float = 0.0) -> int:
    """Perte de forme d'un match en centièmes de % : 100 (1 %) sans équipement, 40 avec -60 %."""
    return int(round(FORM_LOSS_PER_MATCH * 10000 * (1 - max(0.0, min(game_logic.EQUIPMENT_FATIGUE_MAX, reduction)))))


def _loss(row) -> int:
    return row.loss if row.loss is not None else int(round(row.matches * FORM_LOSS_PER_MATCH * 10000))


def form_from_loss(loss: int) -> float:
    return max(MIN_FORM, 1.0 - max(0, loss) / 10000)


def forms_for(db: Session, user_id: str) -> dict:
    """{carte: forme entre 0,5 et 1} des cartes d'un joueur qui ont déjà joué aujourd'hui (les autres sont à 100 %)."""
    today = _today()
    return {r.card_id: form_from_loss(_loss(r)) for r in db.query(CardFatigue).filter_by(user_id=user_id, day=today).all() if _loss(r) > 0}


def record_match(db: Session, user_id: str, card_ids, reduction: float = 0.0) -> None:
    """Un match 1v1 vient d'être joué avec ces cartes : chacune perd 1 % de forme, moins la réduction de l'équipement
    (0 à 60 %, game_logic.equipment_fatigue_reduction) ; remise à zéro si c'est un nouveau jour. Sans commit."""
    today, step = _today(), loss_per_match(reduction)
    for cid in set(card_ids):
        row = db.query(CardFatigue).filter_by(user_id=user_id, card_id=cid).first()
        if row is None:
            db.add(CardFatigue(user_id=user_id, card_id=cid, day=today, matches=1, loss=step))
            continue
        if row.day != today:
            row.day, row.matches, row.loss = today, 0, 0
        row.loss = _loss(row) + step
        row.matches += 1


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(CardFatigue).filter_by(user_id=user_id).delete()


def on_cards_deleted(db: Session, card_ids) -> None:
    if card_ids:
        db.query(CardFatigue).filter(CardFatigue.card_id.in_(list(card_ids))).delete(synchronize_session=False)
