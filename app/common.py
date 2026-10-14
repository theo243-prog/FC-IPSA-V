"""Petits outils partagés par les modules ajoutés au site (défis privés, offres d'achat, saisons, page d'administration)."""
import os

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import User


def require_admin(x_admin_key: str = Header(default=None)):
    """Même règle que les commandes d'admin de main.py : la clé ADMIN_KEY de Railway, envoyée dans l'en-tête X-Admin-Key."""
    key = os.getenv("ADMIN_KEY", "")
    if not key or x_admin_key != key:
        raise HTTPException(status_code=403, detail="Clé admin manquante ou invalide")


def optional_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Le joueur connecté s'il y en a un, sinon None (pour les pages publiques qui s'adaptent à celui qui regarde)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    from . import sessions
    return sessions.find_user(db, authorization[len("Bearer "):].strip())


def card_out(card):
    """La carte telle que le site la reçoit (importé au dernier moment pour éviter une boucle d'imports avec main.py)."""
    from .main import card_out as _card_out
    return _card_out(card)
