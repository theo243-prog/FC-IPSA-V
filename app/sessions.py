"""
Connexions multi-appareils.

Avant, chaque connexion REMPLAÇAIT l'unique jeton du joueur : se connecter sur son téléphone déconnectait l'ordinateur. Maintenant
chaque connexion crée sa propre session ; un joueur peut en avoir jusqu'à MAX_SESSIONS en même temps (au-delà, la plus ancienne
est retirée). Les jetons d'AVANT cette mise à jour restent valides : ils sont convertis en session la première fois qu'ils servent.
« Dernière activité » (mise à jour au plus toutes les 10 minutes) alimente le tableau de bord de l'administration.
"""
import secrets
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base
from .models import User

MAX_SESSIONS = 10
TOUCH_EVERY = timedelta(minutes=10)


class UserSession(Base):
    """Une connexion d'un joueur sur un appareil (volontairement sans clé étrangère : on nettoie à la main à la suppression d'un compte)."""
    __tablename__ = "user_sessions"
    token = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)


def open_session(db: Session, user: User) -> str:
    """Nouvelle connexion : un nouveau jeton, SANS invalider les autres appareils. (Pas de commit : l'appelant s'en charge.)"""
    token = secrets.token_hex(24)
    db.add(UserSession(token=token, user_id=user.id))
    user.token = token                      # (gardé pour compatibilité : dernier jeton émis)
    db.flush()
    rows = db.query(UserSession).filter_by(user_id=user.id).order_by(UserSession.last_seen.desc(), UserSession.created_at.desc()).all()
    for old in rows[MAX_SESSIONS:]:
        db.delete(old)
    return token


def adopt_token(db: Session, user: User) -> None:
    """Le jeton déjà posé sur le compte (création de compte) devient une session."""
    db.add(UserSession(token=user.token, user_id=user.id))


def find_user(db: Session, token: str, touch: bool = False):
    """Le joueur d'un jeton, ou None. touch=True : note l'activité et convertit un ancien jeton en session."""
    now = datetime.utcnow()
    s = db.query(UserSession).filter_by(token=token).first()
    if s is not None:
        user = db.query(User).filter_by(id=s.user_id).first()
        if user is None:
            db.delete(s)
            db.commit()
            return None
        if touch and (s.last_seen is None or now - s.last_seen > TOUCH_EVERY):
            s.last_seen = now
            db.commit()
        return user
    user = db.query(User).filter(User.token == token).first()          # jeton d'avant les sessions multiples
    if user is not None and touch:
        try:
            db.add(UserSession(token=token, user_id=user.id))
            db.commit()
        except IntegrityError:
            db.rollback()
    return user


def close_session(db: Session, token: str) -> None:
    """Déconnexion volontaire : seule la session de CET appareil disparaît."""
    s = db.query(UserSession).filter_by(token=token).first()
    if s is not None:
        db.delete(s)
    user = db.query(User).filter(User.token == token).first()
    if user is not None:
        user.token = None
