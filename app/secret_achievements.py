"""
Succès secrets (fonction en essai « succes_secrets », novembre 2026).

- 21 succès cachés : ni nom, ni condition tant qu'ils ne sont pas trouvés. Le site montre seulement « 🔒 Succès secrets : 3 / 21 » ;
  un succès trouvé apparaît avec son nom et son explication. Chacun rapporte REWARD = 20 crédits et un titre à son nom
  (identifiant « secret-<id> », cosmetics).
- La plupart se lisent dans l'historique du jeu (matchs 1v1, tirs au but, défi du club, marché, pronostics, homme du match,
  communauté) : ils comptent le passé. Ceux que le jeu ne garde pas (contenu des packs, enchère au prix de départ, vente de
  500 doublons, crédits dépensés dans la journée, 0 crédit) sont notés au moment où ils arrivent (table secret_progress),
  pour tous les comptes, à partir de la mise en ligne.
- Pendant l'essai, seuls les comptes qui ont accès les reçoivent (features). Vérification au plus toutes les CHECK_EVERY secondes
  par joueur (et tout de suite après un événement noté), appelée par profiles.safe_unseen (donc par /me).
- Annonce dans le chat : au plus un message par vérification (« a trouvé un succès secret »), jamais pour un compte de test.
"""
import json
import time
from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, Integer, String, event, inspect, or_
from sqlalchemy.orm import Session

from .database import Base
from .models import Card, Duel, OwnedCard, Tier, User

FEATURE = "succes_secrets"
REWARD = 20                       # crédits par succès secret trouvé
TITLE_PREFIX = "secret-"          # titre d'un succès secret : « secret-<id> », son texte est le nom du succès
CHECK_EVERY = 120                 # secondes entre deux vérifications d'un même joueur (sauf événement noté entre-temps)

# Réglages des conditions
COMEBACK_GOALS = 3                # Remontada : mené de 3 buts
WALL_WINS = 5                     # Le mur : 5 victoires d'affilée sans encaisser
SHOOTOUT_LOSSES = 3               # Pas de chance : 3 séances de tirs au but perdues d'affilée
DRAWS_PER_DAY = 5                 # Le roi du nul
GOLIATH_GAP = 10                  # David contre Goliath : 10 points de note moyenne de plus en face
TIRED_FORM = 90                   # Increvable : une carte à 90 % de forme ou moins (la forme baisse de 0,5 % par match et remonte de 1 % par heure)
LOYAL_MATCHES = 20                # Fidèle au poste : la même équipe 20 matchs d'affilée
CURSED_PACKS = 50                 # Maudit : 50 packs d'affilée sans épique ni légendaire
HOARD_COPIES = 20                 # Collectionneur maniaque
GRAVEYARD_DUPES = 500             # Le cimetière : 500 doublons vendus d'un coup
SPEND_PER_DAY = 1000              # Panier percé
NIGHT_HOURS = (3, 4)              # Oiseau de nuit : entre 3 h et 5 h (heure de Paris)
MUSE_CARDS = 3                    # Muse
FIRST_TRY_WINS = 5                # Premier essai

# Ne jamais retirer un succès ni changer un identifiant (ils sont enregistrés par identifiant).
SECRETS = [
    {"id": "remontada", "name": "Remontada", "icon": "🔄", "desc": "Gagner un match 1v1 après avoir été mené de 3 buts."},
    {"id": "le_mur", "name": "Le mur", "icon": "🧱", "desc": "Gagner 5 matchs 1v1 d'affilée sans encaisser de but."},
    {"id": "pas_de_chance", "name": "Pas de chance", "icon": "🍀", "desc": "Perdre 3 séances de tirs au but d'affilée (tournoi ou défi du club)."},
    {"id": "roi_du_nul", "name": "Le roi du nul", "icon": "🤝", "desc": "Faire 5 matchs nuls en 1v1 le même jour."},
    {"id": "david_goliath", "name": "David contre Goliath", "icon": "🪨", "desc": "Battre en 1v1 une équipe qui a au moins 10 points de note moyenne de plus que la tienne."},
    {"id": "increvable", "name": "Increvable", "icon": "🔋", "desc": "Gagner un match 1v1 avec une carte à 90 % de forme ou moins."},
    {"id": "fidele", "name": "Fidèle au poste", "icon": "💍", "desc": "Aligner exactement la même équipe pendant 20 matchs 1v1 d'affilée."},
    {"id": "bonne_etoile", "name": "Né sous une bonne étoile", "icon": "🌠", "desc": "Obtenir une légendaire dans un pack classique."},
    {"id": "maudit", "name": "Maudit", "icon": "🐈‍⬛", "desc": "Ouvrir 50 packs d'affilée sans épique ni légendaire."},
    {"id": "jackpot", "name": "Jackpot", "icon": "🎰", "desc": "Obtenir 2 légendaires dans le même pack."},
    {"id": "maniaque", "name": "Collectionneur maniaque", "icon": "🗃️", "desc": "Avoir 20 exemplaires de la même carte."},
    {"id": "cimetiere", "name": "Le cimetière", "icon": "🪦", "desc": "Vendre 500 doublons d'un coup."},
    {"id": "radin", "name": "Radin", "icon": "🪙", "desc": "Remporter une enchère au prix de départ, sans autre enchère."},
    {"id": "panier_perce", "name": "Panier percé", "icon": "🕳️", "desc": "Dépenser 1 000 crédits dans la même journée."},
    {"id": "coup_de_poker", "name": "Coup de poker", "icon": "🃏", "desc": "Revendre une carte au moins le double du prix que tu l'as payée."},
    {"id": "a_sec", "name": "À sec", "icon": "🏜️", "desc": "Tomber à exactement 0 crédit."},
    {"id": "oiseau_nuit", "name": "Oiseau de nuit", "icon": "🦉", "desc": "Jouer un match 1v1 entre 3 h et 5 h du matin."},
    {"id": "prophete", "name": "Prophète", "icon": "🔮", "desc": "Trouver le score exact d'un match officiel que personne d'autre n'a trouvé."},
    {"id": "supporter", "name": "Supporter numéro 1", "icon": "📣", "desc": "Voter pour le joueur élu homme du match."},
    {"id": "muse", "name": "Muse", "icon": "💡", "desc": "Voir 3 de tes propositions devenir des cartes de la communauté."},
    {"id": "premier_essai", "name": "Du premier coup", "icon": "🎯", "desc": "Battre le club en Difficile au premier essai du jour, 5 fois."},
]
BY_ID = {s["id"]: s for s in SECRETS}
TOTAL = len(SECRETS)


# ------------------------------------------------------------------ base de données
class SecretAchievement(Base):
    """Un succès secret trouvé. `seen` passe à vrai quand le joueur a vu l'annonce."""
    __tablename__ = "secret_achievements"
    user_id = Column(String, primary_key=True)
    secret_id = Column(String, primary_key=True)
    earned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    seen = Column(Boolean, nullable=False, default=False)


class SecretProgress(Base):
    """Ce que le jeu ne garde pas ailleurs : un événement arrivé (valeur 1), une série en cours, les crédits dépensés d'un jour (« spent:AAAA-MM-JJ »)."""
    __tablename__ = "secret_progress"
    user_id = Column(String, primary_key=True)
    key = Column(String, primary_key=True)
    value = Column(Integer, nullable=False, default=0)


_last_check = {}                  # {joueur: heure de la dernière vérification} (mémoire du serveur)


def _paris_day(dt=None) -> str:
    from . import weekly
    return weekly.to_paris(dt or datetime.utcnow()).strftime("%Y-%m-%d")


def has_access(db, user) -> bool:
    from . import features
    try:
        return features.has_access(db, user, FEATURE)
    except Exception:
        return False


# ------------------------------------------------------------------ événements notés au moment où ils arrivent
def _progress(db, user_id: str, key: str):
    return db.get(SecretProgress, (user_id, key))


def _set(db, user_id: str, key: str, value: int, add: bool = False):
    """Écrit une valeur (ou l'ajoute) et renvoie la ligne (une ligne tout juste ajoutée n'est pas encore lisible par db.get)."""
    row = _progress(db, user_id, key)
    if row is None:
        row = SecretProgress(user_id=user_id, key=key, value=max(0, int(value)))
        db.add(row)
    else:
        row.value = row.value + int(value) if add else int(value)
    _last_check.pop(user_id, None)                # vérifier à la prochaine visite
    return row


def flag(db, user_id: str, secret_id: str) -> None:
    """Un succès secret « du moment » vient d'arriver (noté pour tous les comptes, attribué à la vérification). Ne fait jamais échouer l'appelant."""
    try:
        with db.begin_nested():
            _set(db, user_id, "flag:" + secret_id, 1)
    except Exception:
        pass


def on_pack(db, user, pack_type: str, cards) -> None:
    """Après l'ouverture d'un pack : légendaire en pack classique, 2 légendaires, série de packs sans épique ni légendaire."""
    try:
        tiers = [c.tier for c in cards]
        legend = sum(1 for t in tiers if t == Tier.legendaire)
        with db.begin_nested():
            if legend and pack_type in ("classique", "free"):
                _set(db, user.id, "flag:bonne_etoile", 1)
            if legend >= 2:
                _set(db, user.id, "flag:jackpot", 1)
            if any(t in (Tier.epique, Tier.legendaire) for t in tiers):
                _set(db, user.id, "streak:no_epic", 0)
            else:
                if _set(db, user.id, "streak:no_epic", 1, add=True).value >= CURSED_PACKS:
                    _set(db, user.id, "flag:maudit", 1)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _credits_listener(session, flush_context, instances):
    """Avant chaque écriture : crédits qui baissent (dépenses du jour) et compte tombé à 0. Ne fait jamais échouer l'écriture."""
    try:
        changes = []
        for obj in list(session.dirty):
            if not isinstance(obj, User):
                continue
            hist = inspect(obj).attrs.credits.history
            if not hist.added or not hist.deleted:
                continue
            old, new = hist.deleted[0], hist.added[0]
            if old is None or new is None:
                continue
            changes.append((obj.id, int(old), int(new)))
        if not changes:
            return
        day = _paris_day()
        with session.no_autoflush:
            for uid, old, new in changes:
                if new < old:
                    if _set(session, uid, "spent:" + day, old - new, add=True).value >= SPEND_PER_DAY:
                        _set(session, uid, "flag:panier_perce", 1)
                if new == 0 and old > 0:                 # (un compte tout neuf qui commence à 0 ne compte pas)
                    _set(session, uid, "flag:a_sec", 1)
    except Exception:
        pass


event.listen(Session, "before_flush", _credits_listener)


# ------------------------------------------------------------------ conditions lues dans l'historique
def _duels(db, uid):
    return db.query(Duel).filter(or_(Duel.challenger_id == uid, Duel.defender_id == uid)).order_by(Duel.created_at, Duel.id).all()


def _side(d, uid):
    """(mes buts, ses buts, ma composition, la sienne) dans un duel."""
    lu = {}
    try:
        lu = json.loads(d.lineups_json) if d.lineups_json else {}
    except ValueError:
        lu = {}
    if d.challenger_id == uid:
        return d.score_challenger, d.score_defender, lu.get("challenger"), lu.get("defender"), "c"
    return d.score_defender, d.score_challenger, lu.get("defender"), lu.get("challenger"), "d"


def _duel_secrets(db, uid, want) -> set:
    """Les succès 1v1 obtenus d'après tous les matchs du joueur."""
    from . import weekly
    got = set()
    run_wall, last_team, run_team = 0, None, 0
    draws = {}
    for d in _duels(db, uid):
        mine, theirs, me, other, side = _side(d, uid)
        win = mine > theirs
        if "remontada" in want and win and d.events_json:
            try:
                for ev in json.loads(d.events_json):
                    if ev.get("kind") == "goal" and ev.get("score"):
                        a, b = ev["score"]
                        lag = (b - a) if side == "c" else (a - b)
                        if lag >= COMEBACK_GOALS:
                            got.add("remontada"); break
            except (ValueError, TypeError):
                pass
        run_wall = run_wall + 1 if (win and theirs == 0) else 0
        if run_wall >= WALL_WINS:
            got.add("le_mur")
        if mine == theirs:
            day = _paris_day(d.created_at)
            draws[day] = draws.get(day, 0) + 1
            if draws[day] >= DRAWS_PER_DAY:
                got.add("roi_du_nul")
        players = (me or {}).get("players") or []
        if win and players and other and other.get("players"):
            avg = lambda ps: sum(p.get("base_note") or 0 for p in ps) / len(ps)
            if avg(other["players"]) - avg(players) >= GOLIATH_GAP:
                got.add("david_goliath")
            if any((p.get("form") if p.get("form") is not None else 100) <= TIRED_FORM for p in players):
                got.add("increvable")
        team = tuple(sorted((p.get("player"), p.get("tier")) for p in players)) if players else None
        run_team = run_team + 1 if (team is not None and team == last_team) else (1 if team is not None else 0)
        last_team = team
        if run_team >= LOYAL_MATCHES:
            got.add("fidele")
        if side == "c" and d.created_at is not None and weekly.to_paris(d.created_at).hour in NIGHT_HOURS:
            got.add("oiseau_nuit")                   # (le match est joué par celui qui relève le défi)
    return got


def _shootouts(db, uid) -> bool:
    """3 séances de tirs au but perdues d'affilée (tournoi et défi du club, dans l'ordre)."""
    from . import club, tournament
    rows = []
    for m in db.query(club.ClubMatch).filter(club.ClubMatch.user_id == uid, club.ClubMatch.pens_user.isnot(None)).all():
        rows.append((m.created_at or datetime.min, m.result != "victoire"))
    TM = tournament.TournamentMatch
    for m in db.query(TM).filter(or_(TM.p1_id == uid, TM.p2_id == uid), TM.pens1.isnot(None), TM.via == "play").all():
        rows.append((m.decided_at or m.deadline_at or datetime.min, m.winner_id != uid))
    run = 0
    for _, lost in sorted(rows, key=lambda r: r[0]):
        run = run + 1 if lost else 0
        if run >= SHOOTOUT_LOSSES:
            return True
    return False


def _first_try(db, uid) -> bool:
    from . import club
    CM = club.ClubMatch
    first = {}
    for m in db.query(CM).filter(CM.user_id == uid, CM.level == "difficile").order_by(CM.created_at, CM.id).all():
        first.setdefault(m.day, m.result == "victoire")
    return sum(1 for v in first.values() if v) >= FIRST_TRY_WINS


def _prophet(db, uid) -> bool:
    from . import prono
    PB = prono.PronoBet
    for b in db.query(PB).filter(PB.user_id == uid, PB.exact == 1).all():
        if db.query(PB).filter(PB.upcoming_id == b.upcoming_id, PB.exact == 1, PB.user_id != uid).count() == 0:
            return True
    return False


def _supporter(db, uid) -> bool:
    from . import motm
    for bal in db.query(motm.MotmBallot).filter(motm.MotmBallot.user_id == uid).all():
        v = db.get(motm.MotmVote, bal.vote_id)
        if v is None or v.status != "closed":
            continue
        top = db.query(motm.MotmPoint).filter_by(vote_id=v.id, rank=1).first()
        if top is not None and top.player_name in (bal.first, bal.second, bal.third):
            return True
    return False


def _coup_de_poker(db, uid) -> bool:
    from . import offers
    T = offers.Trade
    bought = {}
    for t in db.query(T).filter(or_(T.buyer_id == uid, T.seller_id == uid)).order_by(T.created_at, T.id).all():
        if t.buyer_id == uid:
            bought.setdefault(t.card_id, []).append(t.price)
        elif t.seller_id == uid and t.price > 0 and any(0 < p and t.price >= 2 * p for p in bought.get(t.card_id, [])):
            return True
    return False


def _muse(db, uid) -> bool:
    from . import communaute
    return db.query(communaute.CommunityProposal).filter_by(user_id=uid, status="released").count() >= MUSE_CARDS


def _hoard(db, uid) -> bool:
    return db.query(OwnedCard).filter(OwnedCard.user_id == uid, OwnedCard.quantity >= HOARD_COPIES).count() > 0


def found(db, user, want=None) -> set:
    """Les succès secrets que le joueur remplit (sans rien attribuer). Chaque mesure est protégée : une erreur ne compte pas."""
    want = set(want if want is not None else BY_ID)
    got = set()

    def safe(f):
        try:
            with db.begin_nested():
                return f()
        except Exception:
            return None

    flags = {r.key[5:] for r in db.query(SecretProgress).filter(SecretProgress.user_id == user.id, SecretProgress.key.like("flag:%"), SecretProgress.value > 0).all()}
    got |= flags & want
    duel_ids = {"remontada", "le_mur", "roi_du_nul", "david_goliath", "increvable", "fidele", "oiseau_nuit"}
    if want & duel_ids:
        got |= (safe(lambda: _duel_secrets(db, user.id, want)) or set())
    for sid, f in (("pas_de_chance", _shootouts), ("premier_essai", _first_try), ("prophete", _prophet), ("supporter", _supporter),
                   ("coup_de_poker", _coup_de_poker), ("muse", _muse), ("maniaque", _hoard)):
        if sid in want and sid not in got and safe(lambda: f(db, user.id)):
            got.add(sid)
    return got & set(BY_ID) & want


# ------------------------------------------------------------------ attribution
def check(db, user, force: bool = False) -> list:
    """Attribue les succès secrets remplis et pas encore gagnés (20 crédits chacun). Seulement avec l'accès. Renvoie les nouveaux."""
    if not has_access(db, user):
        return []
    now = time.time()
    if not force and now - _last_check.get(user.id, 0) < CHECK_EVERY:
        return []
    _last_check[user.id] = now
    have = {r.secret_id for r in db.query(SecretAchievement).filter_by(user_id=user.id).all()}
    todo = set(BY_ID) - have
    if not todo:
        return []
    got = found(db, user, todo)                                 # (une seule vérification, pas une par succès)
    new = [s for s in SECRETS if s["id"] in got]
    for s in new:
        db.add(SecretAchievement(user_id=user.id, secret_id=s["id"], earned_at=datetime.utcnow(), seen=False))
        user.credits += REWARD
    if new:
        if not user.is_test:
            from . import chat
            more = len(new) - 1
            chat.add_event(db, "🔒 %s a trouvé un succès secret : « %s »%s !" % (user.pseudo, new[0]["name"], (" (et %d autre%s)" % (more, "s" if more > 1 else "")) if more > 0 else ""), user)
        db.commit()
    return [_out(s) for s in new]


def _out(s, earned_at=None) -> dict:
    return {"id": s["id"], "name": s["name"], "icon": s["icon"], "desc": s["desc"], "reward": REWARD,
            "earned_at": earned_at.date().isoformat() if earned_at else None}


def unseen(db, user) -> list:
    """Annonces pas encore vues, au format des succès (profiles.safe_unseen)."""
    rows = db.query(SecretAchievement).filter_by(user_id=user.id, seen=False).order_by(SecretAchievement.earned_at).all()
    return [{"id": TITLE_PREFIX + r.secret_id, "title": BY_ID[r.secret_id]["name"], "icon": BY_ID[r.secret_id]["icon"],
             "level": 1, "level_name": "succès secret", "reward": REWARD, "secret": True} for r in rows if r.secret_id in BY_ID]


def mark_seen(db, user) -> None:
    db.query(SecretAchievement).filter_by(user_id=user.id, seen=False).update({"seen": True})


def summary(db, user, full: bool) -> dict:
    """Ce que montre le profil : le nombre trouvé sur TOTAL ; la liste des trouvés seulement pour son propre profil (full)."""
    rows = db.query(SecretAchievement).filter_by(user_id=user.id).order_by(SecretAchievement.earned_at).all()
    rows = [r for r in rows if r.secret_id in BY_ID]
    out = {"found": len(rows), "total": TOTAL}
    if full:
        out["list"] = [_out(BY_ID[r.secret_id], r.earned_at) for r in rows]
    return out


def titles(db, user_id: str) -> list:
    """Les titres des succès secrets trouvés : [(id, nom)]. Jamais ceux qui ne sont pas trouvés."""
    return [(TITLE_PREFIX + r.secret_id, BY_ID[r.secret_id]["name"])
            for r in db.query(SecretAchievement).filter_by(user_id=user_id).order_by(SecretAchievement.earned_at).all() if r.secret_id in BY_ID]


def title_label(title_id: str):
    s = BY_ID.get(str(title_id)[len(TITLE_PREFIX):]) if title_id and str(title_id).startswith(TITLE_PREFIX) else None
    return s["name"] if s else None


def admin_view(db) -> dict:
    users = {u.id: u.pseudo for u in db.query(User).all()}
    by = {}
    for r in db.query(SecretAchievement).order_by(SecretAchievement.earned_at).all():
        by.setdefault(r.secret_id, []).append({"pseudo": users.get(r.user_id, "?"), "date": r.earned_at.date().isoformat()})
    return {"total": TOTAL, "reward": REWARD,
            "secrets": [{**s, "found_by": by.get(s["id"], [])} for s in SECRETS]}


def on_user_deleted(db, user_id: str) -> None:
    db.query(SecretAchievement).filter_by(user_id=user_id).delete()
    db.query(SecretProgress).filter_by(user_id=user_id).delete()
    _last_check.pop(user_id, None)


# ------------------------------------------------------------------ routes
from fastapi import APIRouter, Depends                     # noqa: E402
from .common import require_admin                          # noqa: E402
from .database import get_db                               # noqa: E402
from .security import get_current_user                     # noqa: E402

router = APIRouter()


@router.get("/secret-achievements")
def my_secrets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Mes succès secrets : le nombre trouvé sur le total et la liste des trouvés (jamais ceux qui restent à trouver)."""
    from . import features
    features.require(db, user, FEATURE)
    check(db, user, force=True)
    return summary(db, user, full=True)


@router.get("/admin/succes-secrets", dependencies=[Depends(require_admin)])
def admin_secrets(db: Session = Depends(get_db)):
    return admin_view(db)
