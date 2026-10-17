"""
Titres et cadres de profil, débloqués par les succès.

- TITRE : un texte affiché sous le pseudo sur le profil. Chaque succès en donne deux : un titre au 2e niveau, et un titre « maître » au
  dernier niveau. D'autres viennent des podiums de saison et des pronostics.
- CADRE : un anneau de couleur autour de la photo de profil (profil, classement, chat). Il se débloque avec le nombre TOTAL de niveaux de
  succès, ou en gagnant une saison.
Le joueur choisit au plus un titre et un cadre parmi ceux qu'il a débloqués.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .security import get_current_user
from . import profiles

router = APIRouter()

MASTER_TITLES = {
    "collection": "Grand collectionneur", "packs": "Machine à packs", "secretes": "Maître des secrets", "epiques": "Seigneur des épiques",
    "legendaires": "Roi des légendes", "editions": "Roi des éditions", "series": "Perfectionniste", "variete": "Touche-à-tout",
    "matchs": "Gladiateur", "victoires": "Invincible", "serie": "Fidèle au poste", "missions": "Infatigable", "marche": "Magnat du marché",
    "doublons": "Roi du recyclage",
}
BASE_TITLES = {"packs": "Ouvreur de packs", "legendaires": "Légendaire", "matchs": "Joueur 1v1", "serie": "Assidu"}
# (id, nom, niveaux de succès au total)
FRAMES = [("bronze", "Bronze", 5), ("argent", "Argent", 12), ("or", "Or", 20), ("diamant", "Diamant", 30), ("legende", "Légende", 40)]
CHAMPION_FRAME = ("champion", "Champion de saison")
PRONO_TITLES = {"prono": ("Pronostiqueur", "Avoir 5 pronostics réglés"), "oracle": ("Oracle", "Trouver 3 scores exacts")}


class UserCosmetics(Base):
    """Le titre et le cadre choisis par un joueur (sans clé étrangère : nettoyage à la main à la suppression d'un compte)."""
    __tablename__ = "user_cosmetics"
    user_id = Column(String, primary_key=True)
    title = Column(String, nullable=True)
    frame = Column(String, nullable=True)


class CosmeticsRequest(BaseModel):
    title: Optional[str] = None
    frame: Optional[str] = None


def _title_catalog():
    """Tous les titres qui existent : [(id, nom, explication, test de déblocage)]. Le test reçoit (niveaux par succès, a gagné une saison, a un podium, nb pronos réglés, nb scores exacts)."""
    out = []
    for lad in profiles.LADDERS:
        n = len(lad["goals"]); base_lv = min(2, n - 1) if n > 1 else 1
        names = profiles.LEVEL_NAMES[n]
        out.append((lad["id"], BASE_TITLES.get(lad["id"], lad["title"]), "Succès « %s » : niveau %s" % (lad["title"], names[base_lv - 1]), (lambda lid, lv: lambda c: c["levels"].get(lid, 0) >= lv)(lad["id"], base_lv)))
        out.append((lad["id"] + "_max", MASTER_TITLES[lad["id"]], "Succès « %s » : niveau %s (le dernier)" % (lad["title"], names[n - 1]), (lambda lid, lv: lambda c: c["levels"].get(lid, 0) >= lv)(lad["id"], n)))
    out.append(("champion", "Champion de saison", "Gagner une saison 1v1", lambda c: c["champion"]))
    out.append(("podium", "Sur le podium", "Finir dans les 3 premiers d'une saison 1v1", lambda c: c["podium"]))
    out.append(("tournoi", "Champion de tournoi", "Remporter un tournoi mensuel", lambda c: c["tournament_wins"] >= 1))
    out.append(("prono", PRONO_TITLES["prono"][0], PRONO_TITLES["prono"][1], lambda c: c["prono_placed"] >= 5))
    out.append(("oracle", PRONO_TITLES["oracle"][0], PRONO_TITLES["oracle"][1], lambda c: c["prono_exact"] >= 3))
    return out


def _context(db: Session, user_id: str) -> dict:
    from .seasons import SeasonResult
    levels, total = {}, 0
    for b in db.query(profiles.UserBadge).filter_by(user_id=user_id).all():
        levels[b.badge_id] = max(levels.get(b.badge_id, 0), b.level); total += 1
    ranks = [r.rank for r in db.query(SeasonResult).filter_by(user_id=user_id).all()]
    cnt = lambda k: profiles._counter(db, user_id, k)
    return {"levels": levels, "total": total, "champion": 1 in ranks, "podium": bool(ranks), "prono_placed": cnt("prono_placed"), "prono_exact": cnt("prono_exact"), "tournament_wins": cnt("tournament_wins")}


def catalog(db: Session, user: User) -> dict:
    ctx = _context(db, user.id)
    titles = [{"id": i, "label": nm, "desc": desc, "unlocked": bool(test(ctx))} for i, nm, desc, test in _title_catalog()]
    frames = [{"id": i, "label": nm, "desc": "%d niveaux de succès au total (tu en as %d)" % (need, ctx["total"]), "unlocked": ctx["total"] >= need} for i, nm, need in FRAMES]
    frames.append({"id": CHAMPION_FRAME[0], "label": CHAMPION_FRAME[1], "desc": "Gagner une saison 1v1", "unlocked": ctx["champion"]})
    sel = db.query(UserCosmetics).filter_by(user_id=user.id).first()
    return {"titles": titles, "frames": frames, "selected": {"title": sel.title if sel else None, "frame": sel.frame if sel else None}, "levels_total": ctx["total"]}


def title_label(title_id):
    return next((nm for i, nm, _d, _t in _title_catalog() if i == title_id), None) if title_id else None


def display_map(db: Session) -> dict:
    """{joueur: (nom du titre, id du cadre)} pour ceux qui en ont choisi : affiché dans le classement, le profil et le chat."""
    labels = {i: nm for i, nm, _d, _t in _title_catalog()}
    return {r.user_id: (labels.get(r.title), r.frame) for r in db.query(UserCosmetics).all() if r.title or r.frame}


def user_display(db: Session, user_id: str):
    r = db.query(UserCosmetics).filter_by(user_id=user_id).first()
    return (title_label(r.title), r.frame) if r else (None, None)


@router.get("/cosmetics")
def get_cosmetics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return catalog(db, user)


@router.post("/cosmetics")
def set_cosmetics(payload: CosmeticsRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cat = catalog(db, user)
    if payload.title is not None and not any(t["id"] == payload.title and t["unlocked"] for t in cat["titles"]):
        raise HTTPException(status_code=400, detail="Ce titre n'est pas encore débloqué")
    if payload.frame is not None and not any(f["id"] == payload.frame and f["unlocked"] for f in cat["frames"]):
        raise HTTPException(status_code=400, detail="Ce cadre n'est pas encore débloqué")
    row = db.query(UserCosmetics).filter_by(user_id=user.id).first()
    if row is None:
        row = UserCosmetics(user_id=user.id); db.add(row)
    row.title, row.frame = payload.title, payload.frame
    db.commit()
    return {"status": "ok", "title": title_label(payload.title), "frame": payload.frame}
