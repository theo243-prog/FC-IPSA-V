"""
Saisons du 1v1 : le classement Elo repart à zéro chaque mois (minuit à Paris, le 1er).

À la fin d'un mois, le PODIUM (les 3 meilleurs Elo, parmi les joueurs qui ont joué au moins MIN_MATCHES matchs ce mois-là) gagne
des crédits et un TROPHÉE : une carte de rareté « Saison » qui s'appelle « Vainqueur de saison (octobre 2026) », « Deuxième de
la saison (octobre 2026) » ou « Troisième de la saison (octobre 2026) ». Un trophée par saison et par rang : être premier deux
fois donne DEUX cartes différentes, jamais un doublon.

Un trophée n'est qu'un souvenir : il ne sort d'aucun pack, n'a ni note ni bonus, ne peut pas jouer de match, ne se vend pas, ne
s'achète pas, ne compte pas dans le pourcentage de collection, et reste invisible pour ceux qui ne l'ont pas. Ces cartes sont créées
automatiquement à la clôture : il n'y a rien à configurer. Puis l'Elo de tout le monde est remis à 1000 et une nouvelle saison
commence. L'historique des saisons passées est gardé.

Le classement d'une saison se calcule à partir des matchs eux-mêmes (leur Elo après match), donc il est exact même si le
serveur redémarre au changement de mois.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, Duel, OwnedCard, Player, Tier, User
from . import game_logic, push
from .common import card_out, optional_user, require_admin

router = APIRouter()
PARIS, UTC = ZoneInfo("Europe/Paris"), ZoneInfo("UTC")
ELO_START = 1000
MIN_MATCHES = 5                                  # matchs à jouer dans le mois pour pouvoir monter sur le podium
PODIUM_CREDITS = {1: 100, 2: 60, 3: 30}          # crédits offerts au podium (en plus de la carte)
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


class SeasonState(Base):
    """Une seule ligne : le mois de la saison en cours (« AAAA-MM »)."""
    __tablename__ = "season_state"
    id = Column(Integer, primary_key=True, default=1)
    current_key = Column(String, nullable=False)


class SeasonResult(Base):
    """Le podium d'une saison terminée (gardé pour l'historique ; sans clés étrangères : il survit à la suppression d'un compte)."""
    __tablename__ = "season_results"
    season = Column(String, primary_key=True)
    rank = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    pseudo = Column(String, nullable=False)
    elo = Column(Integer, nullable=False)
    matches = Column(Integer, nullable=False)
    wins = Column(Integer, nullable=False)
    card_id = Column(String, nullable=True)
    credits = Column(Integer, nullable=False, default=0)
    closed_at = Column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------------------ trophées
RANK_TITLES = {1: "Vainqueur de saison", 2: "Deuxième de la saison", 3: "Troisième de la saison"}
TROPHY_RE = re.compile(r"^(Vainqueur de saison|Deuxième de la saison|Troisième de la saison) \((.+)\)$")


def trophy_name(key: str, rank: int) -> str:
    return "%s (%s)" % (RANK_TITLES[rank], label_of(key))


def key_from_label(label: str):
    """« octobre 2026 » -> « 2026-10 » (None si le texte n'est pas un mois)."""
    try:
        month, year = label.rsplit(" ", 1)
        return "%d-%02d" % (int(year), MONTHS.index(month) + 1)
    except (ValueError, IndexError):
        return None


def trophy_info(player):
    """Pour une carte-trophée : son rang, sa saison (« 2026-10 ») et le mois écrit ; None pour toute autre carte."""
    m = TROPHY_RE.match(player.name or "") if (player.poste or "").upper() == "TROPHEE" else None
    if not m:
        return None
    rank = next(r for r, t in RANK_TITLES.items() if t == m.group(1))
    return {"rank": rank, "title": m.group(1), "label": m.group(2), "season": key_from_label(m.group(2))}


def get_or_create_trophy(db: Session, key: str, rank: int) -> Card:
    """Le trophée « rang `rank` de la saison `key` » (créé la première fois : un par saison et par rang)."""
    name = trophy_name(key, rank)
    player = db.query(Player).filter_by(name=name).first()
    if player is None:
        player = Player(name=name, poste="TROPHEE")
        db.add(player)
        db.flush()
    card = db.query(Card).filter_by(player_id=player.id, tier=Tier.saison).first()
    if card is None:
        card = Card(player_id=player.id, tier=Tier.saison, vitesse=0, tir=0)
        db.add(card)
        db.flush()
    return card


# ------------------------------------------------------------------ dates
def key_of(d) -> str:
    return "%d-%02d" % (d.year, d.month)


def current_key() -> str:
    return key_of(game_logic.today_paris())


def next_key(key: str) -> str:
    y, m = map(int, key.split("-"))
    return "%d-%02d" % (y + (m == 12), m % 12 + 1)


def label_of(key: str) -> str:
    y, m = map(int, key.split("-"))
    return "%s %d" % (MONTHS[m - 1], y)


def bounds(key: str):
    """Début et fin (heure UTC, sans fuseau) d'une saison : de minuit le 1er à minuit le 1er suivant, heure de Paris."""
    y, m = map(int, key.split("-"))
    start = datetime(y, m, 1, tzinfo=PARIS)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=PARIS)
    return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)


# ------------------------------------------------------------------ classement d'une saison
def standings(db: Session, key: str) -> list:
    """Le classement du mois, calculé à partir des matchs : Elo après le dernier match, victoires, matchs. Sans comptes de test."""
    start, end = bounds(key)
    acc = {}
    for d in db.query(Duel).filter(Duel.created_at >= start, Duel.created_at < end).order_by(Duel.created_at, Duel.id).all():
        for uid, mine, theirs, after in ((d.challenger_id, d.score_challenger, d.score_defender, d.elo_challenger_after),
                                         (d.defender_id, d.score_defender, d.score_challenger, d.elo_defender_after)):
            a = acc.setdefault(uid, {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "elo": ELO_START})
            a["matches"] += 1
            a["wins"] += int(mine > theirs)
            a["draws"] += int(mine == theirs)
            a["losses"] += int(mine < theirs)
            a["elo"] = after
    users = {u.id: u for u in db.query(User).filter(User.id.in_(list(acc))).all()} if acc else {}
    rows = [{"user_id": uid, "pseudo": users[uid].pseudo, **a, "eligible": a["matches"] >= MIN_MATCHES}
            for uid, a in acc.items() if uid in users and not users[uid].is_test]
    rows.sort(key=lambda r: (-r["elo"], -r["wins"], -r["matches"], r["pseudo"].lower()))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def podium_of(rows: list) -> list:
    """Les 3 premiers parmi ceux qui ont assez joué (rangs 1, 2, 3)."""
    top = [dict(r) for r in rows if r["eligible"]][:3]
    for i, r in enumerate(top):
        r["rank"] = i + 1
    return top


def podium_counts(db: Session, user_id: str) -> dict:
    out = {1: 0, 2: 0, 3: 0}
    for r in db.query(SeasonResult).filter_by(user_id=user_id).all():
        out[r.rank] = out.get(r.rank, 0) + 1
    return out


# ------------------------------------------------------------------ fin de saison
def close_season(db: Session, key: str) -> dict:
    """Termine la saison `key` : podium, récompenses, annonces, puis Elo de tout le monde remis à 1000."""
    rows = standings(db, key)
    podium = podium_of(rows)
    results = []
    for r in podium:
        user = db.query(User).filter_by(id=r["user_id"]).first()
        card = get_or_create_trophy(db, key, r["rank"])
        credits = PODIUM_CREDITS.get(r["rank"], 0)
        user.credits += credits
        owned = game_logic.get_or_create_owned(db, user, card)
        owned.quantity = 1                      # un trophée par saison et par rang : jamais de doublon
        db.merge(SeasonResult(season=key, rank=r["rank"], user_id=user.id, pseudo=user.pseudo, elo=r["elo"], matches=r["matches"], wins=r["wins"],
                              card_id=card.id, credits=credits, closed_at=datetime.utcnow()))
        results.append({"rank": r["rank"], "pseudo": user.pseudo, "elo": r["elo"], "card": card.player.name, "credits": credits})
        push.enqueue(db, user.id, "duels", "%s Podium de la saison de %s !" % (MEDALS[r["rank"]], label_of(key)),
                     "Tu finis n°%d (Elo %d) : +%d crédits et ton trophée « %s »." % (r["rank"], r["elo"], credits, card.player.name), url="/#duels", tag="season-podium")
    db.query(User).update({User.elo: ELO_START}, synchronize_session=False)
    nxt = label_of(next_key(key))
    for u in db.query(User).filter(User.is_test == False).all():          # noqa: E712
        push.enqueue(db, u.id, "duels", "Nouvelle saison 1v1 ! 🏆", "Le classement Elo est remis à zéro pour %s. À toi de jouer !" % nxt, url="/#duels", tag="season-new")
    db.commit()
    return {"season": key, "podium": results, "players_ranked": len(rows)}


def run_scheduled(db: Session) -> list:
    """Appelée chaque minute : si un mois est terminé, clôture sa saison (et celles qu'un arrêt du serveur aurait fait manquer)."""
    now_key = current_key()
    st = db.query(SeasonState).first()
    if st is None:
        db.add(SeasonState(id=1, current_key=now_key))
        db.commit()
        return []
    done = []
    while st.current_key < now_key:
        done.append(close_season(db, st.current_key))
        st.current_key = next_key(st.current_key)
        db.commit()
    return done


# ------------------------------------------------------------------ pages publiques
def _prize_rows(db: Session, key: str) -> list:
    """Les 3 récompenses de la saison `key` : les crédits et un aperçu du trophée (la carte est créée à la clôture)."""
    return [{"rank": r, "medal": MEDALS[r], "credits": PODIUM_CREDITS[r], "title": RANK_TITLES[r],
             "card": {"id": "trophy-%s-%d" % (key, r), "tier": "saison", "player_name": trophy_name(key, r), "poste": "TROPHEE", "player_photo_url": None,
                      "display_note": None, "vitesse": 0, "tir": 0, "surnom": None, "numero": None,
                      "trophy": {"rank": r, "title": RANK_TITLES[r], "label": label_of(key), "season": key}}} for r in (1, 2, 3)]


@router.get("/duel/season")
def current_season(viewer=Depends(optional_user), db: Session = Depends(get_db)):
    """La saison en cours : classement du mois, récompenses, temps restant, et le podium de la saison précédente."""
    key = current_key()
    start, end = bounds(key)
    rows = standings(db, key)
    now = datetime.utcnow()
    mine = next((r for r in rows if viewer is not None and r["user_id"] == viewer.id), None)
    last = db.query(SeasonResult).order_by(SeasonResult.season.desc(), SeasonResult.rank).all()
    last_key = last[0].season if last else None
    return {
        "key": key, "label": label_of(key), "ends_at": end.isoformat(), "seconds_left": max(0, int((end - now).total_seconds())),
        "min_matches": MIN_MATCHES, "standings": [{k: v for k, v in r.items() if k not in ("user_id", "draws", "losses")} for r in rows[:10]],
        "me": ({k: v for k, v in mine.items() if k != "user_id"} if mine else None), "prizes": _prize_rows(db, key),
        "last": {"key": last_key, "label": label_of(last_key), "podium": [{"rank": r.rank, "medal": MEDALS[r.rank], "pseudo": r.pseudo, "elo": r.elo} for r in last if r.season == last_key]} if last_key else None,
    }


@router.get("/duel/seasons")
def past_seasons(db: Session = Depends(get_db)):
    """L'historique : le podium de chaque saison terminée, de la plus récente à la plus ancienne."""
    out = {}
    for r in db.query(SeasonResult).order_by(SeasonResult.season.desc(), SeasonResult.rank).all():
        out.setdefault(r.season, {"key": r.season, "label": label_of(r.season), "podium": []})["podium"].append(
            {"rank": r.rank, "medal": MEDALS[r.rank], "pseudo": r.pseudo, "elo": r.elo, "matches": r.matches, "wins": r.wins})
    return list(out.values())


# ------------------------------------------------------------------ administration
@router.get("/admin/seasons", dependencies=[Depends(require_admin)])
def admin_seasons(db: Session = Depends(get_db)):
    """La saison en cours : le classement complet et ce que gagneraient les 3 premiers (aucun réglage à faire : les trophées se créent seuls)."""
    key = current_key()
    rows = standings(db, key)
    return {
        "current": key, "label": label_of(key), "min_matches": MIN_MATCHES, "podium_credits": PODIUM_CREDITS,
        "standings": [{k: v for k, v in r.items() if k != "user_id"} for r in rows],
        "would_win": [{"rank": r["rank"], "pseudo": r["pseudo"], "trophy": trophy_name(key, r["rank"]), "credits": PODIUM_CREDITS[r["rank"]]} for r in podium_of(rows)],
        "state": (db.query(SeasonState).first().current_key if db.query(SeasonState).first() else None),
    }
