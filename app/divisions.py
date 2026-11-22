"""
Divisions de saison 1v1 (22/11/2026, branche divisions, seuils choisis par Théo) : un rang selon l'Elo, en plus du classement commun
(qui ne change pas). L'Elo repart à 1000 chaque mois, donc tout le monde recommence en Argent.

- Seuils (`DIVISIONS`) : Fer < 800, Bronze 800, Argent 1000, Or 1200, Platine 1400, Diamant 1600, Champion 1800, Élite 2000 et plus
  (pas de plafond d'Elo, pas de nombre limité de joueurs en Élite ; pas de protection : la division suit l'Elo, elle peut redescendre).
- Récompense de montée (`REWARDS`) : la PREMIÈRE fois du mois qu'on atteint une division (Or et au-dessus), une seule fois par division et
  par saison, gardée si on redescend. Notée dans `division_reached` (joueur, saison, division). Vérifiée après chaque match 1v1 (`check`,
  appelé par duel_engine.play_proposal) et à chaque /me (rattrapage : un joueur déjà à 1650 le jour de la mise en ligne reçoit Or, Platine et
  Diamant d'un coup). Notification ; annonce dans le chat à partir de `ANNOUNCE_FROM` (Champion), jamais pour un compte de test.
- Fin de saison (`close`, appelé par seasons.close_season AVANT la remise à 1000) : la division de fin de chaque joueur qui a joué est notée ;
  la meilleure division atteinte de chaque saison reste pour toujours sur le profil (`history`).
- Pas de récompense ni d'effet pour le draft, le tournoi ou le défi du club (seulement l'Elo 1v1).
"""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import credit_log
from .common import optional_user
from .database import Base, get_db
from .models import User

router = APIRouter()

# (identifiant, nom, icône, Elo minimum) — du plus bas au plus haut ; ne jamais changer un identifiant (enregistrés en base)
DIVISIONS = [
    ("fer", "Fer", "⛓️", None),
    ("bronze", "Bronze", "🥉", 800),
    ("argent", "Argent", "🥈", 1000),
    ("or", "Or", "🥇", 1200),
    ("platine", "Platine", "💠", 1400),
    ("diamant", "Diamant", "💎", 1600),
    ("champion", "Champion", "🏆", 1800),
    ("elite", "Élite", "👑", 2000),
]
# récompense de la première montée du mois : crédits et un pack (jeton de la réserve)
REWARDS = {
    "or": {"credits": 50},
    "platine": {"credits": 100, "pack": "rare"},
    "diamant": {"credits": 150, "pack": "match"},
    "champion": {"credits": 200, "pack": "epique"},
    "elite": {"credits": 300, "pack": "ultra"},
}
ANNOUNCE_FROM = "champion"     # annonce dans le chat à partir de cette division
IDS = [d[0] for d in DIVISIONS]
RANK = {d: i for i, d in enumerate(IDS)}
PACK_NAMES = {"rare": "pack rare", "match": "pack match", "epique": "pack épique", "ultra": "pack ultra", "classique": "pack classique"}


class DivisionReached(Base):
    """Une division atteinte par un joueur pendant une saison (mois de Paris, AAAA-MM)."""
    __tablename__ = "division_reached"
    __table_args__ = (UniqueConstraint("user_id", "season", "division", name="uq_division_reached"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    season = Column(String, nullable=False, index=True)
    division = Column(String, nullable=False)
    reached_at = Column(DateTime, default=datetime.utcnow)
    credits = Column(Integer, nullable=False, default=0)      # récompense versée (0 : aucune, ex. division de fin de saison)
    pack = Column(String, nullable=True)


def _info(i: int) -> dict:
    did, name, icon, low = DIVISIONS[i]
    return {"id": did, "name": name, "icon": icon, "min": low, "reward": REWARDS.get(did)}


def division_of(elo: int) -> dict:
    """La division d'un Elo, avec la suivante (None en Élite)."""
    i = 0
    for k, d in enumerate(DIVISIONS):
        if d[3] is None or elo >= d[3]:
            i = k
    out = _info(i)
    out["next"] = _info(i + 1) if i + 1 < len(DIVISIONS) else None
    return out


def _season() -> str:
    from . import seasons
    return seasons.current_key()


def reached(db: Session, user_id: str, season: str = None) -> set:
    season = season or _season()
    return {r.division for r in db.query(DivisionReached).filter_by(user_id=user_id, season=season).all()}


def check(db: Session, user: User) -> list:
    """Donne les divisions atteintes pour la première fois ce mois-ci (Or et au-dessus) avec leur récompense. Sans commit.
    Renvoie les nouvelles divisions [{id, name, icon, credits, pack}]."""
    from . import missions, push
    if user is None or user.elo is None:
        return []
    season = _season()
    have = reached(db, user.id, season)
    cur = RANK[division_of(user.elo)["id"]]
    new = []
    for i in range(RANK["or"], cur + 1):
        did = IDS[i]
        if did in have:
            continue
        rw = REWARDS.get(did) or {}
        try:
            with db.begin_nested():                                    # (deux appels en même temps : une seule récompense)
                db.add(DivisionReached(user_id=user.id, season=season, division=did, credits=rw.get("credits", 0), pack=rw.get("pack")))
        except IntegrityError:
            continue
        info = _info(i)
        credit_log.add(user, rw.get("credits", 0), "Division " + info["name"], "première montée du mois")
        if rw.get("pack"):
            missions._grant(user, {"pack": rw["pack"]})
        new.append({"id": did, "name": info["name"], "icon": info["icon"], "credits": rw.get("credits", 0), "pack": rw.get("pack")})
    if new:
        top = new[-1]
        gifts = " + ".join(x for x in ("%d crédits" % sum(n["credits"] for n in new) if any(n["credits"] for n in new) else "",
                                         ", ".join(PACK_NAMES.get(n["pack"], n["pack"]) for n in new if n["pack"])) if x)
        try:
            push.enqueue(db, user.id, "duels", "%s Division %s atteinte !" % (top["icon"], top["name"]),
                         "Première montée du mois : %s." % gifts, url="/#duels", tag="division")
        except Exception:
            pass
        if RANK[top["id"]] >= RANK[ANNOUNCE_FROM] and not user.is_test:
            try:
                from . import chat
                chat.add_event(db, "%s %s atteint la division %s en 1v1 (Elo %d) !" % (top["icon"], user.pseudo, top["name"], user.elo), user)
            except Exception:
                pass
    return new


def safe_check(db: Session, user: User) -> list:
    """check() qui ne fait jamais échouer l'appelant (/me)."""
    try:
        new = check(db, user)
        if new:
            db.commit()
        return new
    except Exception:
        db.rollback()
        return []


def close(db: Session, key: str, final_elos: dict) -> None:
    """Fin de la saison `key` (avant la remise à 1000) : note la division de fin de chaque joueur qui a joué (sans récompense)."""
    for uid, elo in final_elos.items():
        did = division_of(elo)["id"]
        if not db.query(DivisionReached).filter_by(user_id=uid, season=key, division=did).first():
            db.add(DivisionReached(user_id=uid, season=key, division=did, credits=0))


def best_of(db: Session, user_id: str, season: str):
    rows = reached(db, user_id, season)
    return max(rows, key=lambda d: RANK.get(d, -1)) if rows else None


def history(db: Session, user_id: str) -> list:
    """La meilleure division de chaque saison passée (la plus récente d'abord), pour le profil."""
    from . import seasons
    cur = _season()
    best = {}
    for r in db.query(DivisionReached).filter(DivisionReached.user_id == user_id, DivisionReached.season < cur).all():
        if r.season not in best or RANK.get(r.division, -1) > RANK.get(best[r.season], -1):
            best[r.season] = r.division
    return [{"season": k, "label": seasons.label_of(k), **{x: _info(RANK[v])[x] for x in ("id", "name", "icon")}}
            for k, v in sorted(best.items(), reverse=True) if v in RANK]


def state(db: Session, user: User) -> dict:
    """Pour /me et le profil : division actuelle, progression vers la suivante, meilleure du mois, récompenses déjà prises."""
    cur = division_of(user.elo or 1000)
    got = reached(db, user.id)
    best = max(got | {cur["id"]}, key=lambda d: RANK[d])
    nxt = cur["next"]
    lo = cur["min"] if cur["min"] is not None else (nxt["min"] - 200 if nxt else 0)
    progress = None if nxt is None else max(0, min(100, round(100 * (user.elo - lo) / (nxt["min"] - lo))))
    return {"elo": user.elo, "division": {k: cur[k] for k in ("id", "name", "icon", "min")}, "next": nxt, "progress": progress,
            "season_best": {k: _info(RANK[best])[k] for k in ("id", "name", "icon")}, "rewarded": sorted(got & set(REWARDS), key=lambda d: RANK[d])}


@router.get("/divisions")
def get_divisions(viewer=Depends(optional_user), db: Session = Depends(get_db)):
    """Les divisions (seuils et récompenses) ; pour un joueur connecté, sa division et les récompenses déjà prises ce mois-ci."""
    out = {"divisions": [_info(i) for i in range(len(DIVISIONS))], "pack_names": PACK_NAMES}
    if viewer is not None:
        out["me"] = state(db, viewer)
    return out


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(DivisionReached).filter_by(user_id=user_id).delete(synchronize_session=False)
