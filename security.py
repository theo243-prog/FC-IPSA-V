"""
Authentification simple par pseudo + mot de passe. Pas de JWT ni d'OAuth :
à la connexion on génère un jeton aléatoire stocké en base, que le frontend
renvoie ensuite dans l'en-tête "Authorization: Bearer <token>". Largement
suffisant pour un site utilisé entre coéquipiers.
"""
import secrets

from fastapi import Depends, Header, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def generate_token() -> str:
    return secrets.token_hex(24)


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentification requise")
    token = authorization[len("Bearer "):].strip()
    user = db.query(User).filter(User.token == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide, reconnecte-toi")
    return user
