"""
Missions du jour et série de connexion.

- SÉRIE DE CONNEXION : une récompense par jour (à récupérer à la main). La série continue tant qu'on récupère chaque
  jour ; un jour raté la remet à zéro. Les récompenses tournent sur 7 jours (le 7e jour donne aussi un pack), puis
  recommencent, alors que le compteur de jours d'affilée continue de monter.
- MISSIONS DU JOUR : 3 missions (une par catégorie, dont toujours le mini-jeu du jour), tirées au hasard mais toujours les mêmes pour un joueur donné pendant
  toute la journée. Elles changent à minuit, heure de Paris. Chacune rapporte quelques crédits quand on la récupère.
- BONUS : quand les 3 missions du jour sont récupérées, un pack est offert.

Tout est réglable ici (STREAK_REWARDS, MISSION_GROUPS, BONUS_PACK). Les événements (ouvrir un pack, vendre un doublon,
acheter au marché, jouer un match 1v1…) sont comptés par `safe_record`, appelé depuis les routes du site : un problème
ici ne bloque jamais l'action du joueur.
"""
import json
import random
from datetime import date, datetime, time, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from .database import Base
from . import game_logic, weekly, profiles

# ------------------------------------------------------------------ réglages
# Récompense du jour n°1 à n°7 de la série (puis ça recommence). "pack" = un pack de ce type offert en plus.
STREAK_REWARDS = [
    {"credits": 2}, {"credits": 2}, {"credits": 3}, {"credits": 3}, {"credits": 4}, {"credits": 5},
    {"credits": 5, "pack": "rare"},
]
STREAK_CYCLE = len(STREAK_REWARDS)

# Chaque joueur reçoit chaque jour UNE mission de chaque groupe : (identifiant = événement compté, texte, objectif, crédits).
MISSION_GROUPS = [
    [("open_packs", "Ouvre 3 packs", 3, 2),
     ("new_card", "Découvre 1 nouvelle carte", 1, 2)],
    [("minigame", "Joue au mini-jeu du jour", 1, 4)],          # le mini-jeu du jour (quiz foot ou tirs au but) est toujours l'un des trois défis
    [("play_duel", "Joue 2 matchs 1v1", 2, 3),
     ("win_duel", "Gagne 1 match 1v1", 1, 4),
     ("propose_duel", "Lance 1 défi 1v1", 1, 2)],
]
BONUS_PACK = "classique"      # offert quand les 3 missions du jour sont récupérées


LIFETIME_EVENTS = {"open_packs", "sell_dupes", "market_buy", "market_list"}      # aussi comptés à vie, pour les succès


# ------------------------------------------------------------------ base de données
class UserDaily(Base):
    """Une seule ligne par joueur : sa série et l'avancement de ses missions du jour."""
    __tablename__ = "user_dailies"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    streak = Column(Integer, nullable=False, default=0)          # nombre de jours d'affilée (à la dernière récompense)
    last_claim = Column(String, nullable=True)                   # « AAAA-MM-JJ » de la dernière récompense de série
    day = Column(String, nullable=True)                          # le jour auquel correspondent les missions ci-dessous
    progress = Column(Text, nullable=False, default="{}")        # {"open_packs": 2, ...} (événements du jour)
    claimed = Column(Text, nullable=False, default="[]")         # missions (et « bonus ») déjà récupérées aujourd'hui


class ClaimRequest(BaseModel):
    kind: str                         # "streak" | "mission" | "bonus"
    mission_id: Optional[str] = None  # pour kind = "mission"


def _load(text, default):
    try:
        v = json.loads(text or "")
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default


def _row(db, user) -> UserDaily:
    r = db.query(UserDaily).filter_by(user_id=user.id).first()
    if not r:
        r = UserDaily(user_id=user.id, streak=0, progress="{}", claimed="[]")
        db.add(r)
        db.flush()
    return r


def _roll_day(r: UserDaily, today: date) -> None:
    """Un nouveau jour (minuit à Paris) : les missions repartent de zéro."""
    if r.day != today.isoformat():
        r.day, r.progress, r.claimed = today.isoformat(), "{}", "[]"


def daily_count(db, user, key: str) -> int:
    """Un compteur du JOUR (repart de zéro à minuit, heure de Paris) : ex. les packs match gagnés en 1v1 aujourd'hui. Ne valide pas la transaction."""
    r = _row(db, user); _roll_day(r, game_logic.today_paris())
    return int(_load(r.progress, {}).get(key, 0))


def daily_add(db, user, key: str, n: int = 1) -> None:
    r = _row(db, user); _roll_day(r, game_logic.today_paris())
    p = _load(r.progress, {}); p[key] = int(p.get(key, 0)) + int(n); r.progress = json.dumps(p)


def todays_missions(user_id: str, today: date) -> list:
    """Les 3 missions d'un joueur pour un jour donné : toujours les mêmes ce jour-là (tirage fixé par le joueur et la date)."""
    rng = random.Random("%s|%s" % (user_id, today.isoformat()))
    out = []
    for group in MISSION_GROUPS:
        kind, label, target, reward = rng.choice(group)
        out.append({"id": kind, "label": label, "target": target, "reward": reward})
    return out


# ------------------------------------------------------------------ comptage des événements
def record(db, user, event: str, n: int = 1) -> None:
    today = game_logic.today_paris()
    r = _row(db, user)
    _roll_day(r, today)
    p = _load(r.progress, {})
    p[event] = int(p.get(event, 0)) + int(n)
    r.progress = json.dumps(p)
    from . import battlepass                                  # le Pass de saison : un match joué rapporte des points ; chaque pack ouvert fait avancer la barre du club
    if event == "play_duel":
        battlepass.add_points(db, user, "duel", 10, battlepass.DAILY_CAPS["duel"])
    elif event == "open_packs":
        battlepass.club_add(db, n)
    if event in LIFETIME_EVENTS:
        profiles.bump(db, user, event, n)
    db.commit()


def safe_record(db, user, event: str, n: int = 1) -> None:
    """Compte un événement sans JAMAIS faire échouer l'action du joueur."""
    try:
        if n > 0:
            record(db, user, event, n)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


# ------------------------------------------------------------------ état affiché
def _streak_view(r: UserDaily, today: date):
    last = date.fromisoformat(r.last_claim) if r.last_claim else None
    claimed_today = last == today
    effective = r.streak if (claimed_today or last == today - timedelta(days=1)) else 0     # un jour raté : la série est perdue
    return claimed_today, effective


def _seconds_until_midnight() -> int:
    now = weekly.to_paris(datetime.utcnow()).replace(tzinfo=None)
    return max(0, int((datetime.combine(now.date() + timedelta(days=1), time.min) - now).total_seconds()))


def state_out(db, user) -> dict:
    today = game_logic.today_paris()
    r = _row(db, user)
    _roll_day(r, today)
    db.commit()
    claimed_today, eff = _streak_view(r, today)
    if claimed_today:
        done_count = ((eff - 1) % STREAK_CYCLE) + 1            # la récompense d'aujourd'hui compte comme prise
        next_pos = None
    else:
        done_count = eff % STREAK_CYCLE                        # jours déjà faits dans le cycle de 7 en cours
        next_pos = done_count + 1
    rewards = [{"day": i + 1, **rw, "state": "done" if i + 1 <= done_count else ("today" if i + 1 == next_pos else "todo")}
               for i, rw in enumerate(STREAK_REWARDS)]
    progress, claimed = _load(r.progress, {}), _load(r.claimed, [])
    missions = []
    for m in todays_missions(user.id, today):
        prog = int(progress.get(m["id"], 0))
        missions.append({**m, "progress": min(prog, m["target"]), "done": prog >= m["target"], "claimed": m["id"] in claimed})
    all_claimed = all(m["claimed"] for m in missions)
    bonus = {"pack": BONUS_PACK, "label": "1 " + game_logic.PACK_TYPES[BONUS_PACK]["label"].lower(),
             "available": all_claimed and "bonus" not in claimed, "claimed": "bonus" in claimed}
    claimable = (0 if claimed_today else 1) + sum(1 for m in missions if m["done"] and not m["claimed"]) + (1 if bonus["available"] else 0)
    return {
        "day": today.isoformat(), "resets_in_seconds": _seconds_until_midnight(),
        "streak": {"days": eff, "claimed_today": claimed_today, "rewards": rewards,
                   "today_reward": None if claimed_today else STREAK_REWARDS[next_pos - 1]},
        "missions": missions, "bonus": bonus, "claimable": claimable,
    }


# ------------------------------------------------------------------ récupérer une récompense
def _grant(user, reward: dict) -> None:
    user.credits += int(reward.get("credits", 0))
    pack = reward.get("pack")
    if pack:
        ps = user.pack_state
        field = game_logic.PACK_TYPES[pack]["token_field"]
        setattr(ps, field, (getattr(ps, field, 0) or 0) + 1)


def claim(db, user, kind: str, mission_id: Optional[str] = None) -> dict:
    """Récupère la série, une mission ou le bonus. Lève ValueError (message lisible) si ce n'est pas possible."""
    today = game_logic.today_paris()
    r = _row(db, user)
    _roll_day(r, today)
    claimed = _load(r.claimed, [])
    if kind == "streak":
        claimed_today, eff = _streak_view(r, today)
        if claimed_today:
            raise ValueError("Tu as déjà récupéré ta récompense du jour : reviens demain pour continuer ta série")
        new_streak = eff + 1
        reward = dict(STREAK_REWARDS[(new_streak - 1) % STREAK_CYCLE])
        r.streak, r.last_claim = new_streak, today.isoformat()
        profiles.bump(db, user, "best_streak", new_streak, maximum=True)
        info = {"streak": new_streak}
    elif kind == "mission":
        mission = next((m for m in todays_missions(user.id, today) if m["id"] == mission_id), None)
        if not mission:
            raise ValueError("Cette mission n'est pas dans tes missions du jour")
        if mission_id in claimed:
            raise ValueError("Tu as déjà récupéré cette mission")
        if int(_load(r.progress, {}).get(mission_id, 0)) < mission["target"]:
            raise ValueError("Cette mission n'est pas encore terminée")
        reward = {"credits": mission["reward"]}
        claimed.append(mission_id)
        r.claimed = json.dumps(claimed)
        info = {}
    elif kind == "bonus":
        missions = todays_missions(user.id, today)
        if "bonus" in claimed:
            raise ValueError("Tu as déjà récupéré le bonus du jour")
        if not all(m["id"] in claimed for m in missions):
            raise ValueError("Récupère d'abord les 3 missions du jour pour avoir le bonus")
        reward = {"pack": BONUS_PACK}
        profiles.bump(db, user, "bonus_days")
        claimed.append("bonus")
        r.claimed = json.dumps(claimed)
        info = {}
    else:
        raise ValueError("Récompense inconnue")
    _grant(user, reward)
    if kind in ("mission", "bonus"):
        from . import battlepass
        battlepass.add_points(db, user, "mission", 20, battlepass.DAILY_CAPS["mission"])      # chaque mission (et le bonus du jour) : 20 points de Pass
    db.commit()
    return {"credits_gained": int(reward.get("credits", 0)), "pack": reward.get("pack"), "credits": user.credits, **info}
