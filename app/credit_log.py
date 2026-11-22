"""
Historique des crédits (22/11/2026, branche historique-credits) : chaque mouvement des crédits d'un joueur est noté (table credit_log),
et le joueur voit la liste en touchant ses crédits en haut du site (« +12 Loup », « −50 Gel de fatigue », « +300 Podium de saison »…).

- Rien ne peut être oublié : un écouteur « before_flush » regarde les crédits de chaque User modifié et note la différence. Les endroits
  du code qui changent les crédits passent par `add(user, montant, libellé, détail)`, qui donne le libellé ; un mouvement sans libellé
  (nouvel endroit du code qui fait encore `user.credits += …`) est noté « Autre », jamais perdu.
- Une ligne par mouvement étiqueté ; plusieurs mouvements dans la même écriture restent séparés (mise puis gain d'un match).
- Pas de passé : l'historique commence à la mise en ligne. Gardé KEEP_DAYS jours (nettoyage par la tâche de fond).
- Visible par le joueur seul (GET /credits/history, compte connecté) ; jamais les crédits d'un autre.
- Ne fait jamais échouer une écriture : en cas d'erreur, le mouvement n'est simplement pas noté.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Column, DateTime, Integer, String, event, inspect
from sqlalchemy.orm import Session, object_session

from .database import Base, get_db
from .models import User
from .security import get_current_user

router = APIRouter()
KEEP_DAYS = 90                 # lignes gardées (jours)
PAGE = 50                      # lignes par page
OTHER = "Autre"                # libellé d'un mouvement sans étiquette
_NOTES = "_credit_notes"       # attribut (non enregistré) du User : mouvements étiquetés pas encore écrits
_PENDING = "credit_log_users"  # session.info : les User qui ont des mouvements étiquetés en attente


class CreditLog(Base):
    """Un mouvement de crédits d'un joueur."""
    __tablename__ = "credit_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    delta = Column(Integer, nullable=False)             # + gain, − dépense
    balance = Column(Integer, nullable=True)            # crédits après le mouvement
    label = Column(String(60), nullable=False)          # « Loup », « Gel de fatigue »…
    detail = Column(String(160), nullable=True)         # « match contre Théo », « pack rare »…


def note(user, amount: int, label: str, detail: Optional[str] = None) -> None:
    """Étiquette un mouvement déjà appliqué à user.credits (à appeler juste après le changement)."""
    try:
        amount = int(amount or 0)
        if not amount or user is None:
            return
        user.__dict__.setdefault(_NOTES, []).append((amount, str(label)[:60], (str(detail)[:160] if detail else None)))
        s = object_session(user)
        if s is not None:
            s.info.setdefault(_PENDING, set()).add(user)
    except Exception:
        pass


def add(user, amount, label: str, detail: Optional[str] = None) -> int:
    """Ajoute (ou retire, montant négatif) des crédits à un joueur et note le mouvement. Renvoie le montant."""
    amount = int(amount or 0)
    if user is None or not amount:
        return amount
    user.credits = (user.credits or 0) + amount
    note(user, amount, label, detail)
    return amount


def card_name(card) -> Optional[str]:
    """« Nom (rareté) » d'une carte pour le détail d'un mouvement, ou None."""
    try:
        name = card.player.name if card is not None and card.player is not None else None
        tier = card.tier.value if card is not None and card.tier is not None else None
        return ("%s (%s)" % (name, tier)) if name and tier else name
    except Exception:
        return None


def _flush_listener(session, flush_context, instances):
    try:
        users = set(session.info.pop(_PENDING, set()) or ())
        for obj in list(session.dirty):
            if isinstance(obj, User):
                users.add(obj)
        now = datetime.utcnow()
        for u in users:
            if u in session.deleted or u.id is None:
                u.__dict__.pop(_NOTES, None)
                continue
            hist = inspect(u).attrs.credits.history
            real = 0
            if hist.added and hist.deleted and hist.added[0] is not None and hist.deleted[0] is not None:
                real = int(hist.added[0]) - int(hist.deleted[0])
            notes = u.__dict__.pop(_NOTES, None) or []
            rest = real - sum(n[0] for n in notes)
            if rest:
                notes.append((rest, OTHER, None))
            balance = int(u.credits or 0)
            for amount, label, detail in notes:
                if amount:
                    session.add(CreditLog(user_id=u.id, at=now, delta=amount, balance=balance, label=label, detail=detail))
    except Exception:
        pass


def _rollback_listener(session, previous_transaction=None):
    try:
        for u in session.info.pop(_PENDING, set()) or ():
            u.__dict__.pop(_NOTES, None)
    except Exception:
        pass


event.listen(Session, "before_flush", _flush_listener)
event.listen(Session, "after_soft_rollback", _rollback_listener)


# ------------------------------------------------------------------ lecture
def _paris_day(dt: datetime):
    from . import weekly
    return weekly.to_paris(dt).date()


def history(db: Session, user: User, before: Optional[int] = None, kind: str = "all", limit: int = PAGE) -> dict:
    q = db.query(CreditLog).filter(CreditLog.user_id == user.id)
    if before:
        q = q.filter(CreditLog.id < before)
    if kind == "gains":
        q = q.filter(CreditLog.delta > 0)
    elif kind == "spent":
        q = q.filter(CreditLog.delta < 0)
    rows = q.order_by(CreditLog.id.desc()).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    now = datetime.utcnow()
    today = _paris_day(now)
    week_start = today - timedelta(days=today.weekday())                # lundi (Paris)
    tot = {"today": {"gains": 0, "spent": 0}, "week": {"gains": 0, "spent": 0}}
    for r in db.query(CreditLog).filter(CreditLog.user_id == user.id, CreditLog.at >= now - timedelta(days=8)).all():
        d = _paris_day(r.at)
        for k, ok in (("today", d == today), ("week", d >= week_start)):
            if ok:
                tot[k]["gains" if r.delta > 0 else "spent"] += abs(r.delta)
    return {"credits": user.credits, "keep_days": KEEP_DAYS, "totals": tot, "more": more,
            "items": [{"id": r.id, "at": r.at.isoformat(), "delta": r.delta, "balance": r.balance, "label": r.label, "detail": r.detail}
                      for r in rows]}


@router.get("/credits/history")
def get_history(before: Optional[int] = None, kind: str = Query("all", pattern="^(all|gains|spent)$"),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Mes mouvements de crédits, du plus récent au plus ancien (PAGE par page, `before` = id de la dernière ligne reçue)."""
    return history(db, user, before, kind)


# ------------------------------------------------------------------ entretien
def tick(db: Session) -> int:
    """Efface les lignes de plus de KEEP_DAYS jours (tâche de fond)."""
    n = db.query(CreditLog).filter(CreditLog.at < datetime.utcnow() - timedelta(days=KEEP_DAYS)).delete(synchronize_session=False)
    db.commit()
    return n


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(CreditLog).filter_by(user_id=user_id).delete(synchronize_session=False)
