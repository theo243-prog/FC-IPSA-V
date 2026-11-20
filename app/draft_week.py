"""
La semaine draft (branche draft-mensuel, 20/11/2026) : chaque mois, le mode draft (app/draft.py) s'ouvre à TOUT LE MONDE pendant 7 jours
consécutifs (WEEK_DAYS), à une date tirée au hasard ; en dehors de cette semaine, seuls les comptes choisis dans l'administration (réglage
« draft » de features.py, pour essayer) peuvent jouer. Décidé avec Théo : un rendez-vous qui rassemble les joueurs (le draft se joue à deux,
en même temps), plutôt qu'un mode ouvert tout le mois où l'on attend un adversaire.

- Tirage (`ensure`) : le jour de départ est tiré parmi les jours qui laissent la semaine DANS le mois (1 à dernier jour − 6) et qui ne
  touchent pas les jours de match du tournoi mensuel (AVOID_DAYS, du 8 au 15 : décidé ainsi ; la dernière semaine, points du Pass ×2, est
  permise). Un tirage fait en cours de mois ne prend que des jours à venir (pas aujourd'hui). Le tirage du mois suivant se fait dès les
  DRAW_AHEAD_DAYS derniers jours du mois, pour que l'annonce 48 h avant marche aussi pour un départ le 1er. Enregistré dans
  app_settings « draft_week:AAAA-MM » : le même pour tous, il survit aux redémarrages. Aucun jour possible : pas de semaine ce mois-là.
- La date reste SECRÈTE jusqu'à l'annonce, ANNOUNCE_HOURS (48) avant l'ouverture : notification à tous et message du chat.
- Ouverture (0 h, heure de Paris) : notification et chat ; le classement draft du mois repart de zéro (les parties d'essai d'avant ne comptent
  pas). Fermeture à la fin du 7e jour : on ne crée ni ne rejoint plus de partie ; une partie commencée va jusqu'au bout.
- Podium à la fermeture (une seule fois, `podium_done`) : les MIN_GAMES (5) parties au moins pour être classé, comptes de test exclus ;
  PODIUM_CREDITS 150 / 100 / 50 crédits et une carte trophée « Champion du draft (mois) », « Deuxième du draft », « Troisième du draft »
  (seasons.RANK_TITLES 12, 13, 14, rareté saison, avec un titre), notification aux trois et message du chat.
- Admin : `GET /admin/draft-week`, `POST /admin/draft-week {month?, start?, redraw?, paused?, open_now?}`.
"""
import calendar
import json
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .common import require_admin
from .models import AppSetting, User

router = APIRouter()
WEEK_DAYS = 7
ANNOUNCE_HOURS = 48
AVOID_DAYS = range(8, 16)              # jours de match du tournoi mensuel (tirage le 8, finale vers le 12-15)
DRAW_AHEAD_DAYS = 3                    # le tirage du mois suivant se fait pendant les 3 derniers jours du mois
MIN_GAMES = 5
PODIUM_CREDITS = {1: 150, 2: 100, 3: 50}
PODIUM_RANKS = {1: 12, 2: 13, 3: 14}   # rangs des cartes trophées (seasons.RANK_TITLES)
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
RNG = random.Random()                  # (remplaçable dans les tests)


def now_paris() -> datetime:
    from .club_auctions import paris_now
    return paris_now()


def key_of(d) -> str:
    return "%d-%02d" % (d.year, d.month)


def next_key(key: str) -> str:
    y, m = int(key[:4]), int(key[5:])
    return "%d-%02d" % (y + (m == 12), 1 if m == 12 else m + 1)


def dim(key: str) -> int:
    return calendar.monthrange(int(key[:4]), int(key[5:]))[1]


def label_of(key: str) -> str:
    from .seasons import label_of as lab
    return lab(key)


def possible_starts(key: str, after_day: int = 0) -> list:
    """Jours de départ possibles d'un mois : la semaine reste dans le mois, ne touche pas AVOID_DAYS, et commence après `after_day`."""
    last = dim(key) - WEEK_DAYS + 1
    return [s for s in range(1, last + 1) if s > after_day and not any(d in AVOID_DAYS for d in range(s, s + WEEK_DAYS))]


# ------------------------------------------------------------------ enregistrement
def _get(db: Session, key: str) -> dict:
    row = db.get(AppSetting, "draft_week:" + key)
    try:
        return json.loads(row.value) if row is not None else None
    except ValueError:
        return None


def _put(db: Session, key: str, data: dict) -> None:
    row = db.get(AppSetting, "draft_week:" + key)
    value = json.dumps(data, ensure_ascii=False)
    if row is None:
        db.add(AppSetting(key="draft_week:" + key, value=value))
    else:
        row.value = value
    db.flush()


def ensure(db: Session, key: str, now: datetime = None) -> dict:
    """La semaine draft du mois `key`, tirée au hasard la première fois (sans commit)."""
    data = _get(db, key)
    if data is not None:
        return data
    now = now or now_paris()
    after = now.day if key_of(now) == key else 0                       # tirage en cours de mois : seulement des jours à venir
    choices = possible_starts(key, after)
    start = ("%s-%02d" % (key, RNG.choice(choices))) if choices else None
    data = {"start": start, "paused": False, "announced": False, "opened": False, "podium_done": False, "podium": []}
    _put(db, key, data)
    return data


def bounds(data: dict):
    """(ouverture, fermeture) en heure de Paris, ou (None, None)."""
    if not data or not data.get("start"):
        return None, None
    start = datetime.strptime(data["start"], "%Y-%m-%d")
    return start, start + timedelta(days=WEEK_DAYS)


def is_open(db: Session, now: datetime = None) -> bool:
    now = now or now_paris()
    data = _get(db, key_of(now))
    if not data or data.get("paused"):
        return False
    start, end = bounds(data)
    return start is not None and start <= now < end


def status(db: Session, now: datetime = None) -> dict:
    """Ce que le site affiche : « soon » (date encore secrète), « announced » (ouvre bientôt), « open », « closed » (fini pour ce mois)."""
    now = now or now_paris()
    key = key_of(now)
    data = _get(db, key) or {}
    start, end = bounds(data)
    out = {"month": key, "label": label_of(key), "week_days": WEEK_DAYS, "min_games": MIN_GAMES,
           "podium_credits": [PODIUM_CREDITS[r] for r in (1, 2, 3)], "state": "soon", "starts_at": None, "ends_at": None}
    if start is None or data.get("paused"):
        out["state"] = "none" if data and (data.get("paused") or not data.get("start")) else "soon"
    elif now >= end:
        out.update(state="closed", starts_at=start.isoformat(), ends_at=end.isoformat())
    elif now >= start:
        out.update(state="open", starts_at=start.isoformat(), ends_at=end.isoformat(), seconds_left=int((end - now).total_seconds()))
    elif now >= start - timedelta(hours=ANNOUNCE_HOURS):
        out.update(state="announced", starts_at=start.isoformat(), ends_at=end.isoformat(), seconds_to_open=int((start - now).total_seconds()))
    out["podium"] = data.get("podium") or []
    if not out["podium"]:                                              # le podium du dernier mois qui en a un (pour l'afficher en attendant)
        prev = _get(db, _prev_key(key)) or {}
        if prev.get("podium"):
            out["last_podium"] = {"label": label_of(_prev_key(key)), "podium": prev["podium"]}
    return out


def _prev_key(key: str) -> str:
    y, m = int(key[:4]), int(key[5:])
    return "%d-%02d" % (y - (m == 1), 12 if m == 1 else m - 1)


# ------------------------------------------------------------------ tâche de fond
def _when(start: datetime) -> str:
    from .seasons import MONTHS
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return "%s %d %s" % (days[start.weekday()], start.day, MONTHS[start.month - 1])


def tick(db: Session, now: datetime = None) -> None:
    """Toutes les minutes (main._background_tick) : tirage, annonce 48 h avant, ouverture, podium à la fermeture."""
    from . import push, chat, draft
    now = now or now_paris()
    key = key_of(now)
    data = ensure(db, key, now)
    if now.day > dim(key) - DRAW_AHEAD_DAYS:
        ensure(db, next_key(key), now)
    start, end = bounds(data)
    if start is None or data.get("paused"):
        db.commit(); return
    last = end - timedelta(days=1)
    if not data.get("announced") and now >= start - timedelta(hours=ANNOUNCE_HOURS) and now < start:
        data["announced"] = True; _put(db, key, data)
        chat.add_event(db, "⚔️ La semaine draft arrive ! Ouverture le %s à 0 h, pendant 7 jours. Prépare tes enchères !" % _when(start))
        push.safe(db, push.notify_all, "draft", "⚔️ La semaine draft arrive", "Ouverture le %s, pendant 7 jours." % _when(start), url="/#draft")
    if not data.get("opened") and start <= now < end:
        data["opened"] = data["announced"] = True; _put(db, key, data)
        db.query(draft.DraftRating).filter_by(season=key).delete()     # classement de la semaine : les parties d'essai d'avant ne comptent pas
        chat.add_event(db, "⚔️ La semaine draft est ouverte jusqu'au %s soir ! Enchères en direct, podium à la fin : %d / %d / %d crédits et un trophée."
                       % (_when(last), PODIUM_CREDITS[1], PODIUM_CREDITS[2], PODIUM_CREDITS[3]))
        push.safe(db, push.notify_all, "draft", "⚔️ La semaine draft est ouverte", "Jusqu'au %s soir : défie les autres en direct !" % _when(last), url="/#draft")
    if data.get("opened") and not data.get("podium_done") and now >= end:
        award_podium(db, key, data)
    db.commit()


def award_podium(db: Session, key: str, data: dict) -> list:
    """Le podium de la semaine draft (une seule fois) : crédits, carte trophée, notification, chat. Sans commit."""
    from . import draft, seasons, push, chat, game_logic
    data["podium_done"] = True
    rows = [r for r in draft.ranking(db, key, limit=1000) if r["played"] >= MIN_GAMES][:3]
    podium = []
    for i, r in enumerate(rows, start=1):
        user = db.query(User).filter_by(pseudo=r["pseudo"]).first()
        if user is None:
            continue
        user.credits += PODIUM_CREDITS[i]
        card = seasons.get_or_create_trophy(db, key, PODIUM_RANKS[i])
        owned = game_logic.get_or_create_owned(db, user, card); owned.quantity = max(owned.quantity, 1)
        podium.append({"rank": i, "pseudo": user.pseudo, "elo": r["elo"], "played": r["played"], "credits": PODIUM_CREDITS[i], "trophy": card.player.name})
        push.enqueue(db, user.id, "draft", "%s Semaine draft : %s !" % (MEDALS[i], ("1re place", "2e place", "3e place")[i - 1]),
                     "+%d crédits et la carte « %s »." % (PODIUM_CREDITS[i], card.player.name), url="/#draft")
    data["podium"] = podium
    _put(db, key, data)
    if podium:
        chat.add_event(db, "🏁 Fin de la semaine draft de %s : " % label_of(key) + ", ".join("%s %s" % (MEDALS[p["rank"]], p["pseudo"]) for p in podium) + ". Rendez-vous le mois prochain !")
    else:
        chat.add_event(db, "🏁 Fin de la semaine draft de %s. Personne n'a joué les %d parties pour être classé : rendez-vous le mois prochain !" % (label_of(key), MIN_GAMES))
    return podium


# ------------------------------------------------------------------ administration
class AdminWeekRequest(BaseModel):
    month: str = ""                    # AAAA-MM (vide : le mois en cours)
    start: str = ""                    # AAAA-MM-JJ : forcer le jour de départ
    redraw: bool = False               # refaire le tirage au hasard
    paused: bool = None                # pas de semaine draft ce mois-là
    open_now: bool = False             # ouvrir tout de suite (pour 7 jours à partir d'aujourd'hui)


def _check_month(key: str) -> str:
    try:
        datetime.strptime(key + "-01", "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="Le mois doit s'écrire comme 2026-11")
    return key


@router.get("/admin/draft-week", dependencies=[Depends(require_admin)])
def admin_draft_week(db: Session = Depends(get_db)):
    now = now_paris(); key = key_of(now)
    out = {"now": now.isoformat(), "current": {"month": key, **(ensure(db, key, now))}, "status": status(db, now)}
    nxt = _get(db, next_key(key))
    out["next"] = {"month": next_key(key), **nxt} if nxt else {"month": next_key(key), "start": None, "note": "tiré pendant les %d derniers jours du mois" % DRAW_AHEAD_DAYS}
    db.commit()
    return out


@router.post("/admin/draft-week", dependencies=[Depends(require_admin)])
def admin_set_draft_week(payload: AdminWeekRequest, db: Session = Depends(get_db)):
    now = now_paris(); key = _check_month(payload.month.strip() or key_of(now))
    data = ensure(db, key, now)
    if data.get("opened") and (payload.start or payload.redraw or payload.open_now):
        raise HTTPException(status_code=400, detail="La semaine draft de ce mois a déjà commencé : on ne change plus sa date")
    if payload.open_now:
        if key != key_of(now):
            raise HTTPException(status_code=400, detail="« Ouvrir tout de suite » ne vaut que pour le mois en cours")
        data["start"] = now.strftime("%Y-%m-%d")
    elif payload.start:
        try:
            d = datetime.strptime(payload.start.strip(), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="La date doit s'écrire comme 2026-11-22")
        if key_of(d) != key or d.day > dim(key) - WEEK_DAYS + 1:
            raise HTTPException(status_code=400, detail="La semaine doit tenir dans le mois : départ entre le 1er et le %d" % (dim(key) - WEEK_DAYS + 1))
        data["start"] = d.strftime("%Y-%m-%d"); data["announced"] = False
    elif payload.redraw:
        choices = possible_starts(key, now.day if key == key_of(now) else 0)
        data["start"] = ("%s-%02d" % (key, RNG.choice(choices))) if choices else None; data["announced"] = False
    if payload.paused is not None:
        data["paused"] = bool(payload.paused)
    _put(db, key, data); db.commit()
    tick(db)                                                           # annonce / ouverture tout de suite si c'est le moment
    return {"status": "ok", "month": key, **_get(db, key)}
