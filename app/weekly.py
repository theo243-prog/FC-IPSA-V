"""
Tâches planifiées. Chaque VENDREDI à 17h00 (heure de Paris), le jeu crée des cartes SPÉCIALES pour les stars
du 1v1 de la semaine écoulée : la carte de joueur la plus utilisée, le meilleur buteur et le meilleur passeur.

- La carte spéciale d'un joueur est créée avec une note de 80 ; si elle existe déjà, sa note gagne +1.
- Elles ne sortent que des packs gagnés en 1v1 (voir game_logic.PACK_TYPES["match"]).
- Le créneau traité est mémorisé en base (table job_runs) : un redémarrage du serveur ne fait ni rater ni
  répéter la tâche. Si le serveur était éteint à 17h, elle est rattrapée dès son retour.
"""
import json
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import Card, Duel, JobRun, Player, Tier
from . import game_logic

JOB_NAME = "weekly_specials"
CATEGORY_LABELS = {"most_used": "la plus utilisée", "top_scorer": "meilleur buteur", "top_assister": "meilleur passeur"}


# ------------------------------------------------------------ heure de Paris ----
# (sans dépendre de la base de fuseaux du système : heure d'été du dernier dimanche de mars au dernier dimanche d'octobre)

def _last_sunday(year: int, month: int) -> datetime:
    d = datetime(year, month, 31)            # mars et octobre ont 31 jours
    return d - timedelta(days=(d.weekday() + 1) % 7)


def paris_offset_hours(utc_dt: datetime) -> int:
    start = _last_sunday(utc_dt.year, 3).replace(hour=1)
    end = _last_sunday(utc_dt.year, 10).replace(hour=1)
    return 2 if start <= utc_dt < end else 1


def to_paris(utc_dt: datetime) -> datetime:
    return utc_dt + timedelta(hours=paris_offset_hours(utc_dt))


def from_paris(local_dt: datetime) -> datetime:
    for off in (2, 1):
        utc = local_dt - timedelta(hours=off)
        if paris_offset_hours(utc) == off:
            return utc
    return local_dt - timedelta(hours=1)


def last_slot(now_utc: datetime) -> datetime:
    """Le dernier vendredi 17h00 (Paris) déjà passé, exprimé en UTC (sans fuseau)."""
    local = to_paris(now_utc)
    candidate = (local - timedelta(days=(local.weekday() - 4) % 7)).replace(hour=17, minute=0, second=0, microsecond=0)
    if candidate > local:
        candidate -= timedelta(days=7)
    return from_paris(candidate)


# ----------------------------------------------------------------- calculs ----

def window_stats(db: Session, start: datetime, end: datetime):
    """Sur les matchs 1v1 de ]start, end] : utilisations, buts et passes décisives PAR JOUEUR (toutes raretés confondues)."""
    used, goals, assists = Counter(), Counter(), Counter()
    rows = db.query(Duel).filter(Duel.lineups_json.isnot(None), Duel.created_at > start, Duel.created_at <= end).all()
    for d in rows:
        try:
            lineups = json.loads(d.lineups_json)
            events = json.loads(d.events_json or "[]")
        except ValueError:
            continue
        for side in ("challenger", "defender"):
            for p in lineups.get(side, {}).get("players", []):
                used[p["player"]] += 1
        for ev in events:
            if ev.get("kind") != "goal":
                continue
            goals[ev["scorer"]] += 1
            if ev.get("assist"):
                assists[ev["assist"]] += 1
    return used, goals, assists, len(rows)


def _best(db: Session, counter: Counter):
    """Le premier (le plus fort, puis par ordre alphabétique) qui est un vrai joueur de l'effectif."""
    for name, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        player = db.query(Player).filter_by(name=name).first()
        if player is not None and game_logic.card_kind(player) == "joueur":
            return player, n
    return None, 0


def award_special(db: Session, player: Player) -> dict:
    """Crée la carte spéciale du joueur (note 80) ou, si elle existe déjà, lui ajoute +1."""
    card = db.query(Card).filter_by(player_id=player.id, tier=Tier.speciale).first()
    if card is None:
        card = Card(player_id=player.id, tier=Tier.speciale, vitesse=0, tir=0, note=game_logic.SPECIAL_BASE_NOTE)
        db.add(card)
        db.flush()
        return {"player": player.name, "created": True, "note": card.note}
    card.note = (card.note or game_logic.SPECIAL_BASE_NOTE) + 1
    return {"player": player.name, "created": False, "note": card.note}


def run_weekly_specials(db: Session, start: datetime, end: datetime, dry_run: bool = False) -> dict:
    used, goals, assists, n_duels = window_stats(db, start, end)
    picks = {"most_used": _best(db, used), "top_scorer": _best(db, goals), "top_assister": _best(db, assists)}
    report = {"from": start.isoformat(), "to": end.isoformat(), "duels": n_duels, "dry_run": dry_run, "awards": []}
    for category, (player, n) in picks.items():
        if player is None:
            continue
        entry = {"category": category, "label": CATEGORY_LABELS[category], "player": player.name, "count": n}
        if not dry_run:
            entry.update(award_special(db, player))        # un joueur qui gagne 2 catégories reçoit 2 fois +1
        report["awards"].append(entry)
    if not dry_run:
        db.commit()
    return report


def check_and_run(db: Session, now: datetime = None):
    """Appelée toutes les minutes par le serveur : exécute la tâche du vendredi 17h si elle n'a pas encore eu lieu.
    La toute première fois, elle se contente de noter le créneau courant (pas de rattrapage à l'installation)."""
    now = now or datetime.utcnow()
    slot = last_slot(now)
    job = db.query(JobRun).filter_by(name=JOB_NAME).with_for_update().first()
    if job is None:
        db.add(JobRun(name=JOB_NAME, last_slot=slot, last_run_at=None, last_report=None))
        db.commit()
        return None
    if job.last_slot is not None and job.last_slot >= slot:
        db.rollback()
        return None
    report = run_weekly_specials(db, slot - timedelta(days=7), slot)
    job.last_slot, job.last_run_at, job.last_report = slot, now, json.dumps(report, ensure_ascii=False)
    db.commit()
    return report
