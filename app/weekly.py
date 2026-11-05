"""
Tâches planifiées. Chaque VENDREDI à 17h00 (heure de Paris), le jeu crée des cartes SPÉCIALES pour les stars
du 1v1 de la semaine écoulée : la carte de joueur la plus utilisée DANS CHAQUE GROUPE DE RARETÉ (commune, rare,
épique, légendaire, édition limitée), le meilleur buteur et le meilleur passeur (toutes raretés confondues).
Au plus 7 cartes spéciales par semaine (5 groupes + buteur + passeur).

- La carte spéciale d'un joueur est créée avec une note de 80 ; si elle existe déjà, sa note gagne +1.
- Elles ne sortent que des packs gagnés en 1v1 (voir game_logic.PACK_TYPES["match"]).
- Le créneau traité est mémorisé en base (table job_runs) : un redémarrage du serveur ne fait ni rater ni
  répéter la tâche. Si le serveur était éteint à 17h, elle est rattrapée dès son retour.
"""
import json
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import Card, CardUsage, Duel, JobRun, Player, Tier
from . import game_logic

JOB_NAME = "weekly_specials"
CATEGORY_LABELS = {"most_used": "la plus utilisée", "top_scorer": "meilleur buteur", "top_assister": "meilleur passeur"}

# Groupes de rareté pour « la plus utilisée » : un gagnant par groupe. Les éditions limitées (Halloween, Noël et les
# éditions personnalisées ed1 à ed12) forment un seul groupe. Gold, secrète, spéciale et trophée de saison sont ignorées.
RARITY_GROUPS = [
    ("commune", "commune", ("commune",)),
    ("rare", "rare", ("rare",)),
    ("epique", "épique", ("epique",)),
    ("legendaire", "légendaire", ("legendaire",)),
    ("edition", "édition limitée", tuple(game_logic.EDITION_TIERS)),
]
GROUP_LABELS = {g: label for g, label, _t in RARITY_GROUPS}
_TIER_GROUP = {t: g for g, _l, tiers in RARITY_GROUPS for t in tiers}


def tier_group(tier):
    """Le groupe de rareté d'une carte pour « la plus utilisée » (None : rareté ignorée)."""
    return _TIER_GROUP.get(tier)


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

def record_usage(db: Session, source: str, user_id: str, players) -> None:
    """Note les cartes alignées par un joueur dans un match de tournoi ou du défi du club (pas de commit : l'appelant s'en charge)."""
    now = datetime.utcnow()
    for p in players or []:
        db.add(CardUsage(at=now, source=source, user_id=user_id, player_name=p["player"], tier=p["tier"]))


def _usage_rows(db: Session, start: datetime = None, end: datetime = None):
    q = db.query(CardUsage.player_name, CardUsage.tier)
    if start is not None:
        q = q.filter(CardUsage.at > start, CardUsage.at <= end)
    return q.all()


def window_stats(db: Session, start: datetime, end: datetime, by_group: dict = None):
    """Sur les matchs 1v1 de ]start, end] : utilisations, buts et passes décisives PAR JOUEUR (toutes raretés confondues).
    Les cartes alignées en tournoi et au défi du club comptent aussi dans les utilisations (jamais dans les buts ni les passes).
    Si `by_group` (dict) est donné, il est rempli avec les utilisations par groupe de rareté : {groupe: Counter(joueur)}."""
    used, goals, assists = Counter(), Counter(), Counter()

    def use(name, tier):
        used[name] += 1
        g = tier_group(tier)
        if by_group is not None and g is not None:
            by_group.setdefault(g, Counter())[name] += 1

    for name, tier in _usage_rows(db, start, end):
        use(name, tier)
    rows = db.query(Duel).filter(Duel.lineups_json.isnot(None), Duel.created_at > start, Duel.created_at <= end).all()
    for d in rows:
        try:
            lineups = json.loads(d.lineups_json)
            events = json.loads(d.events_json or "[]")
        except ValueError:
            continue
        for side in ("challenger", "defender"):
            for p in lineups.get(side, {}).get("players", []):
                use(p["player"], p.get("tier"))
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
    groups = {}
    _used, goals, assists, n_duels = window_stats(db, start, end, by_group=groups)
    picks = [("most_used", g, _best(db, groups.get(g, Counter()))) for g, _l, _t in RARITY_GROUPS]   # un gagnant par groupe de rareté
    picks += [("top_scorer", None, _best(db, goals)), ("top_assister", None, _best(db, assists))]
    report = {"from": start.isoformat(), "to": end.isoformat(), "duels": n_duels, "dry_run": dry_run, "awards": []}
    for category, group, (player, n) in picks:
        if player is None:                                 # groupe (ou catégorie) sans aucune utilisation : pas de carte
            continue
        label = CATEGORY_LABELS[category] + (" (%s)" % GROUP_LABELS[group] if group else "")
        entry = {"category": category, "group": group, "group_label": GROUP_LABELS.get(group), "label": label, "player": player.name, "count": n}
        if not dry_run:
            entry.update(award_special(db, player))        # un joueur qui gagne 2 catégories reçoit 2 fois +1
        report["awards"].append(entry)
    if not dry_run:
        db.commit()
        if report["awards"]:
            from . import push            # (import ici pour éviter une dépendance circulaire)
            push.safe(db, push.notify_weekly_specials, report["awards"])
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


# ----------------------------------------------- classement des cartes stars de la semaine ----

def next_slot(slot_utc: datetime) -> datetime:
    """Le vendredi 17h (Paris) suivant un créneau donné (le changement d'heure est géré)."""
    return from_paris(to_paris(slot_utc) + timedelta(days=7))


def window_tiers(db: Session, start: datetime, end: datetime) -> Counter:
    """Utilisations par carte (joueur, rareté) sur la fenêtre : sert à choisir quelle carte afficher pour un joueur."""
    tiers = Counter()
    for name, tier in _usage_rows(db, start, end):                  # tournoi et défi du club
        tiers[(name, tier)] += 1
    for d in db.query(Duel).filter(Duel.lineups_json.isnot(None), Duel.created_at > start, Duel.created_at <= end).all():
        try:
            lineups = json.loads(d.lineups_json)
        except ValueError:
            continue
        for side in ("challenger", "defender"):
            for p in lineups.get(side, {}).get("players", []):
                tiers[(p["player"], p["tier"])] += 1
    return tiers


def week_board(db: Session, now: datetime = None, limit: int = 5) -> dict:
    """Les stars de la semaine en cours : depuis le dernier vendredi 17h, remis à zéro au prochain.
    Compté exactement comme l'attribution des cartes spéciales : « la plus utilisée » a un classement PAR GROUPE
    DE RARETÉ (le n°1 de chaque groupe recevra sa carte spéciale vendredi) ; buts et passes sont comptés par joueur,
    toutes raretés confondues. Pour chaque joueur on indique la rareté qu'il a le plus utilisée (c'est la carte
    qu'on affiche), dans le groupe pour « la plus utilisée »."""
    now = now or datetime.utcnow()
    start = last_slot(now)
    groups = {}
    _used, goals, assists, _n = window_stats(db, start, now, by_group=groups)
    tiers = window_tiers(db, start, now)
    rank = {t: i for i, t in enumerate(game_logic.TIER_ORDER)}

    def display_tier(name, group=None):
        mine = [(n, rank.get(t, 0), t) for (nm, t), n in tiers.items() if nm == name and (group is None or tier_group(t) == group)]
        return max(mine)[2] if mine else "commune"            # le plus utilisé ; à égalité, la plus rare

    def top(counter, group=None):
        out = []
        for name, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
            player = db.query(Player).filter_by(name=name).first()
            if player is not None and game_logic.card_kind(player) == "joueur":
                out.append((name, display_tier(name, group), n))
            if len(out) >= limit:
                break
        return out

    return {"since": start, "resets_at": next_slot(start),
            "most_used_groups": [{"group": g, "label": label, "entries": top(groups.get(g, Counter()), g)} for g, label, _t in RARITY_GROUPS],
            "top_scorers": top(goals), "top_assisters": top(assists)}
