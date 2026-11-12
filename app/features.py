"""
Fonctions en essai (12/11/2026) : une fonctionnalité terminée mais pas encore sortie reste cachée aux joueurs, sauf aux comptes choisis.
Le but : préparer plusieurs nouveautés et les sortir ensemble dans une grosse mise à jour (cocher « ouvert à tous » pour chacune, le même jour).

- Réglage `app_settings` dont la clé est le nom de la fonction : {"public": bool, "allowed": [pseudos]} ; fermé par défaut.
  (Le mode draft garde sa clé « draft » : même format, il passe par ce module.)
- Le serveur refuse les comptes sans accès (403, `require`) ; `/me` renvoie `features` {nom: bool} pour que le site affiche ou cache l'onglet.
- Admin : `GET /admin/features` (toutes les fonctions en essai et leur accès), `POST /admin/feature-settings {feature, public?, allowed?}`.
- POUR AJOUTER UNE FONCTION EN ESSAI : une ligne dans FEATURES, puis `features.require(db, user, "nom")` dans ses routes et
  `meInfo.features.nom` sur le site.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .models import AppSetting, User
from .common import require_admin

router = APIRouter()

FEATURES = {                         # nom : ce que c'est (affiché dans l'administration)
    "draft": "Mode draft (match en direct, équipe aux enchères)",
    "pantheon": "Panthéon (palmarès et records du jeu et du club)",
}


class FeatureRequest(BaseModel):
    feature: str
    public: bool = None
    allowed: list[str] = None


def get(db: Session, name: str) -> dict:
    row = db.get(AppSetting, name)
    s = {"public": False, "allowed": []}
    if row is not None:
        try:
            s.update({k: v for k, v in (json.loads(row.value) or {}).items() if k in s})
        except ValueError:
            pass
    return s


def save(db: Session, name: str, s: dict) -> None:
    row = db.get(AppSetting, name)
    value = json.dumps({"public": bool(s.get("public")), "allowed": list(s.get("allowed") or [])}, ensure_ascii=False)
    if row is None:
        db.add(AppSetting(key=name, value=value))
    else:
        row.value = value


def has_access(db: Session, user, name: str) -> bool:
    if user is None:
        return False
    s = get(db, name)
    return bool(s["public"]) or user.pseudo.lower() in {p.lower() for p in s["allowed"]}


def require(db: Session, user, name: str, message: str = "Cette fonction n'est pas encore ouverte") -> None:
    if not has_access(db, user, name):
        raise HTTPException(status_code=403, detail=message)


def flags_for(db: Session, user) -> dict:
    return {name: has_access(db, user, name) for name in FEATURES}


def update(db: Session, name: str, public=None, allowed=None) -> dict:
    """Change l'accès d'une fonction (pseudos exacts, refus s'il y en a d'inconnus). Ne valide pas la transaction."""
    s = get(db, name)
    if public is not None:
        s["public"] = bool(public)
    if allowed is not None:
        names = [n.strip() for n in allowed if n and n.strip()]
        found = {u.pseudo for u in db.query(User).filter(User.pseudo.in_(names)).all()} if names else set()
        unknown = [n for n in names if n not in found]
        if unknown:
            raise HTTPException(status_code=400, detail="Pseudo(s) introuvable(s) : " + ", ".join(unknown))
        s["allowed"] = sorted(set(names), key=str.lower)
    save(db, name, s)
    return s


@router.get("/admin/features", dependencies=[Depends(require_admin)])
def admin_features(db: Session = Depends(get_db)):
    """Les fonctions en essai : ouvertes à tous ou réservées à une liste de comptes."""
    return {"fonctions": [{"fonction": n, "description": d, **get(db, n)} for n, d in FEATURES.items()]}


@router.post("/admin/feature-settings", dependencies=[Depends(require_admin)])
def admin_feature_settings(payload: FeatureRequest, db: Session = Depends(get_db)):
    """Qui a accès à une fonction en essai : « public » = tout le monde ; sinon seulement les pseudos de « allowed »."""
    if payload.feature not in FEATURES:
        raise HTTPException(status_code=400, detail="Fonction inconnue (au choix : %s)" % ", ".join(FEATURES))
    s = update(db, payload.feature, payload.public, payload.allowed)
    db.commit()
    return {"status": "ok", "fonction": payload.feature, "reglages": s}
