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
from .common import require_admin
from . import profiles

router = APIRouter()

MASTER_TITLES = {
    "collection": "Grand collectionneur", "packs": "Machine à packs", "secretes": "Maître des secrets", "epiques": "Seigneur des épiques",
    "legendaires": "Roi des légendes", "editions": "Roi des éditions", "series": "Perfectionniste", "variete": "Touche-à-tout",
    "matchs": "Gladiateur", "victoires": "Invincible", "serie": "Fidèle au poste", "missions": "Infatigable", "marche": "Magnat du marché",
    "doublons": "Roi du recyclage",
    # succès de novembre 2026
    "evolution": "Forgeron de cartes", "niveau_max": "Tout au max", "pronos": "Voyant", "scores_exacts": "Nostradamus", "minijeu": "Roi du mini-jeu",
    "electeur": "Grand électeur", "club": "Bourreau du club", "club_difficile": "Terreur du club", "encheres": "Commissaire-priseur",
    "echanges": "Roi du troc", "tournoi": "Bête de tournoi", "stars": "Chasseur d'étoiles", "completion": "Le jeu est fini", "pass": "Abonné à vie",
    "podiums": "Habitué du podium", "numerotees": "Pièce de musée",
}
BASE_TITLES = {"packs": "Ouvreur de packs", "legendaires": "Légendaire", "matchs": "Joueur 1v1", "serie": "Assidu",
               "pronos": "Parieur", "club": "Adversaire du club", "club_difficile": "Téméraire", "pass": "Abonné", "podiums": "Médaillé", "completion": "Complétiste"}
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


class UnlockAllRequest(BaseModel):
    pseudo: str
    enabled: bool = True              # True : tout débloquer ; False : revenir au déblocage normal (par les succès)


def _title_catalog():
    """Tous les titres qui existent : [(id, nom, explication, test de déblocage)]. Le test reçoit (niveaux par succès, a gagné une saison, a un podium, nb pronos réglés, nb scores exacts)."""
    out = []
    for lad in profiles.LADDERS:
        n = len(lad["goals"]); base_lv = min(2, n - 1) if n > 1 else 1
        names = profiles.LEVEL_NAMES[n]
        out.append((lad["id"], BASE_TITLES.get(lad["id"], lad["title"]), "Succès « %s » : niveau %s" % (lad["title"], names[base_lv - 1]), (lambda lid, lv: lambda c: c["levels"].get(lid, 0) >= lv)(lad["id"], base_lv)))
        top = lad.get("master_at", n)               # (un succès qui a reçu un niveau de plus garde son titre maître à l'ancien dernier niveau)
        out.append((lad["id"] + "_max", MASTER_TITLES[lad["id"]], "Succès « %s » : niveau %s%s" % (lad["title"], names[top - 1], " (le dernier)" if top == n else ""), (lambda lid, lv: lambda c: c["levels"].get(lid, 0) >= lv)(lad["id"], top)))
    out.append(("champion", "Champion de saison", "Gagner une saison 1v1", lambda c: c["champion"]))
    out.append(("podium", "Sur le podium", "Finir dans les 3 premiers d'une saison 1v1", lambda c: c["podium"]))
    out.append(("tournoi", "Champion de tournoi", "Remporter un tournoi mensuel", lambda c: c["tournament_wins"] >= 1))
    out.append(("club", "Tombeur du club", "Battre 10 fois le club au niveau Difficile (Défi du club)", lambda c: c["club_hard_wins"] >= 10))
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
    return {"levels": levels, "total": total, "champion": 1 in ranks, "podium": bool(ranks), "prono_placed": cnt("prono_placed"), "prono_exact": cnt("prono_exact"), "tournament_wins": cnt("tournament_wins"), "club_hard_wins": cnt("club_hard_wins")}


def pass_theme_name(item) -> str:
    from . import pass_catalog
    return pass_catalog.THEMES[item["theme"]]["name"] if item.get("theme") else "Objectif du club"


def catalog(db: Session, user: User) -> dict:
    ctx = _context(db, user.id)
    everything = profiles._counter(db, user.id, "cosmetics_all") == 1          # compte de test / admin : tout est débloqué à la main (commande d'administration)
    titles = [{"id": i, "label": nm, "desc": desc, "unlocked": everything or bool(test(ctx))} for i, nm, desc, test in _title_catalog()]
    frames = [{"id": i, "label": nm, "desc": "%d niveaux de succès au total (tu en as %d)" % (need, ctx["total"]), "unlocked": everything or ctx["total"] >= need} for i, nm, need in FRAMES]
    frames.append({"id": CHAMPION_FRAME[0], "label": CHAMPION_FRAME[1], "desc": "Gagner une saison 1v1", "unlocked": everything or ctx["champion"]})
    from . import battlepass
    for it in battlepass.owned_items(db, user):                                                  # objets du Pass possédés : cadres et titres en plus
        row = {"id": it["id"], "label": it["name"], "desc": ("Boutique, palier %d" % it["level"]) if it.get("shop") else "Objet du Pass (%s)" % pass_theme_name(it), "unlocked": True, "pass": True}
        (frames if it["kind"] == "frame" else titles if it["kind"] == "title" else []).append(row)
    for tid, name in trophy_titles(db, user.id):                                                  # une carte trophée possédée = un titre à son nom
        titles.append({"id": tid, "label": name, "desc": "Carte trophée", "unlocked": True, "trophy": True})
    sel = db.query(UserCosmetics).filter_by(user_id=user.id).first()
    return {"titles": titles, "frames": frames, "selected": {"title": sel.title if sel else None, "frame": sel.frame if sel else None}, "levels_total": ctx["total"]}


TROPHY_TITLE_PREFIX = "trophee-"        # titre d'une carte trophée : « trophee-<id de la fiche> », son texte est le nom de la carte
TROPHY_TITLE_RANKS = (1, 2, 3, 4, 5, 7, 8, 9, 10, 11)       # podium de saison, tournoi (vainqueur, finaliste, demi-finalistes), assidus, lanterne rouge (pas la carte du Pass, rang 6)


def trophy_titles(db: Session, user_id: str) -> list:
    """Les titres que donnent les cartes trophées possédées : [(id, nom de la carte)]. Seulement celles qu'on a : la lanterne rouge reste une surprise."""
    from .models import Card, OwnedCard, Player, Tier
    from . import seasons
    rows = (db.query(Player).join(Card, Card.player_id == Player.id).join(OwnedCard, OwnedCard.card_id == Card.id)
            .filter(OwnedCard.user_id == user_id, OwnedCard.quantity > 0, Card.tier == Tier.saison, Player.poste == "TROPHEE").all())
    out = []
    for p in rows:
        info = seasons.trophy_info(p)
        if info and info["rank"] in TROPHY_TITLE_RANKS:
            out.append((TROPHY_TITLE_PREFIX + p.id, p.name, info))
    out.sort(key=lambda x: (x[2]["season"] or "", x[2]["rank"]), reverse=True)        # les plus récents d'abord
    return [(i, nm) for i, nm, _ in out]


def _trophy_label(title_id, db=None):
    from .models import Player
    from .database import SessionLocal
    own = db is None
    db = db or SessionLocal()
    try:
        p = db.get(Player, title_id[len(TROPHY_TITLE_PREFIX):])
        return p.name if p is not None and (p.poste or "").upper() == "TROPHEE" else None
    finally:
        if own:
            db.close()


def title_label(title_id, db=None):
    if title_id and str(title_id).startswith(TROPHY_TITLE_PREFIX):         # titre d'une carte trophée
        return _trophy_label(title_id, db)
    if title_id and str(title_id).startswith(("pass-", "shop-")):          # titres du Pass et de la boutique
        from . import pass_catalog
        it = pass_catalog.ITEMS.get(title_id)
        return it["name"] if it and it["kind"] == "title" else None
    return next((nm for i, nm, _d, _t in _title_catalog() if i == title_id), None) if title_id else None


def display_map(db: Session) -> dict:
    """{joueur: (nom du titre, id du cadre)} pour ceux qui en ont choisi : affiché dans le classement, le profil et le chat."""
    labels = {i: nm for i, nm, _d, _t in _title_catalog()}
    from . import pass_catalog
    labels.update({i: it["name"] for i, it in pass_catalog.ITEMS.items() if it["kind"] == "title"})        # titres du Pass
    from .models import Player
    labels.update({TROPHY_TITLE_PREFIX + p.id: p.name for p in db.query(Player).filter(Player.poste == "TROPHEE").all()})      # titres des cartes trophées
    return {r.user_id: (labels.get(r.title), r.frame) for r in db.query(UserCosmetics).all() if r.title or r.frame}


def user_display(db: Session, user_id: str):
    r = db.query(UserCosmetics).filter_by(user_id=user_id).first()
    return (title_label(r.title, db), r.frame) if r else (None, None)


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
    return {"status": "ok", "title": title_label(payload.title, db), "frame": payload.frame}


@router.post("/admin/unlock-cosmetics", dependencies=[Depends(require_admin)])
def admin_unlock_cosmetics(payload: UnlockAllRequest, db: Session = Depends(get_db)):
    """Débloque TOUS les titres et cadres d'un compte (pour les essayer : compte de test ou d'administration), ou revient au déblocage normal.
    Le choix déjà fait par le joueur reste affiché ; on ne peut plus en choisir de nouveau verrouillé quand on retire le déblocage."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    row = db.query(profiles.UserCounter).filter_by(user_id=user.id, key="cosmetics_all").first()
    if row is None:
        db.add(profiles.UserCounter(user_id=user.id, key="cosmetics_all", value=1 if payload.enabled else 0))
    else:
        row.value = 1 if payload.enabled else 0
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "all_unlocked": payload.enabled}
