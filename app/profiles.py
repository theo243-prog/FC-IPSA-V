"""
Profil public, succès (badges) et vitrine.

- SUCCÈS : des séries de niveaux (Bronze, Argent, Or, Diamant, Légende). Chaque niveau atteint est gagné UNE SEULE FOIS, pour
  toujours (même si on revend des cartes ensuite), et rapporte quelques crédits. Les succès sont vérifiés automatiquement :
  rien à déclencher à la main. Les compteurs (packs ouverts, doublons vendus…) sont tenus ici ; les autres valeurs (collection,
  matchs 1v1…) sont calculées à partir du jeu lui-même, donc elles comptent aussi ce qui s'est passé avant l'arrivée des succès.
- VITRINE : jusqu'à 3 cartes choisies par le joueur, montrées sur son profil. À défaut, ses 3 cartes les plus rares.
- PROFIL PUBLIC : ce que n'importe qui peut voir d'un joueur (collection en pourcentage, matchs 1v1, succès, vitrine).

Tout est réglable en haut du fichier (LADDERS, LEVEL_REWARD).
"""
import json
from datetime import datetime
from typing import List

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, and_, func, or_

from .database import Base
from .models import Card, Duel, OwnedCard, Tier, User
from . import game_logic

# ------------------------------------------------------------------ réglages
LEVEL_NAMES = {
    2: ["Or", "Légende"],
    3: ["Bronze", "Argent", "Or"],
    4: ["Bronze", "Argent", "Or", "Diamant"],
    5: ["Bronze", "Argent", "Or", "Diamant", "Légende"],
}
LEVEL_REWARD = {"Bronze": 3, "Argent": 5, "Or": 10, "Diamant": 25, "Légende": 50}     # crédits offerts à l'obtention du niveau

# Une ligne par succès : identifiant, titre, icône, explication, mesure, unité, objectifs de chaque niveau.
LADDERS = [
    {"id": "collection", "title": "Collectionneur", "icon": "📚", "metric": "collection", "unit": "% de la collection", "desc": "Possède une part de toutes les cartes du jeu.", "goals": [10, 25, 50, 75, 100]},
    {"id": "packs", "title": "Ouvreur de packs", "icon": "📦", "metric": "packs", "unit": "packs ouverts", "desc": "Ouvre des packs.", "goals": [10, 50, 150, 500]},
    {"id": "secretes", "title": "Chasseur de secrètes", "icon": "🔮", "metric": "secretes", "unit": "cartes secrètes", "desc": "Débloque des cartes secrètes.", "goals": [1, 5, 10, 20]},
    {"id": "epiques", "title": "Amateur d'épiques", "icon": "💜", "metric": "epiques", "unit": "cartes épiques", "desc": "Possède des cartes épiques différentes.", "goals": [1, 5, 10]},
    {"id": "legendaires", "title": "Légendes", "icon": "👑", "metric": "legendaires", "unit": "cartes légendaires", "desc": "Possède des cartes légendaires différentes.", "goals": [1, 3]},
    {"id": "editions", "title": "Éditions limitées", "icon": "🎃", "metric": "editions", "unit": "cartes d'édition", "desc": "Possède des cartes d'éditions limitées (Halloween, Noël…).", "goals": [1, 5]},
    {"id": "series", "title": "Séries complètes", "icon": "🧩", "metric": "series", "unit": "raretés complètes", "desc": "Possède TOUTES les cartes d'une rareté.", "goals": [1, 3, 5]},
    {"id": "variete", "title": "Éventail de raretés", "icon": "🌈", "metric": "variete", "unit": "raretés possédées", "desc": "Possède au moins une carte de plusieurs raretés différentes.", "goals": [3, 5, 7]},
    {"id": "matchs", "title": "Joueur 1v1", "icon": "⚽", "metric": "duel_played", "unit": "matchs 1v1 joués", "desc": "Joue des matchs 1v1.", "goals": [1, 10, 50, 150]},
    {"id": "victoires", "title": "Vainqueur", "icon": "🏆", "metric": "duel_won", "unit": "victoires en 1v1", "desc": "Gagne des matchs 1v1.", "goals": [1, 10, 30, 100]},
    {"id": "serie", "title": "Assidu", "icon": "🔥", "metric": "best_streak", "unit": "jours d'affilée", "desc": "Récupère ta récompense de connexion plusieurs jours de suite.", "goals": [3, 7, 14, 30]},
    {"id": "missions", "title": "Missionnaire", "icon": "🎯", "metric": "bonus_days", "unit": "journées complètes", "desc": "Termine et récupère les 3 missions du jour (bonus).", "goals": [1, 7, 30]},
    {"id": "marche", "title": "Commerçant", "icon": "🛒", "metric": "market", "unit": "opérations au marché", "desc": "Achète ou mets en vente des cartes au marché.", "goals": [1, 10, 30]},
    {"id": "doublons", "title": "Recycleur", "icon": "♻️", "metric": "sell_dupes", "unit": "doublons vendus", "desc": "Revends des doublons.", "goals": [10, 50, 200]},
]
SHOWCASE_MAX = 3
# Pour la vitrine automatique : les raretés de la plus précieuse à la plus commune.
TIER_VALUE_ORDER = ["saison", "legendaire", "secrete", "speciale", "epique", "halloween", "noel", "gold", "rare", "commune"]


# ------------------------------------------------------------------ base de données
class UserCounter(Base):
    """Compteurs à vie d'un joueur (packs ouverts, doublons vendus, meilleure série…)."""
    __tablename__ = "user_counters"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    key = Column(String, primary_key=True)
    value = Column(Integer, nullable=False, default=0)


class UserBadge(Base):
    """Un niveau de succès obtenu. `seen` passe à vrai quand le joueur a vu l'annonce."""
    __tablename__ = "user_badges"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    badge_id = Column(String, primary_key=True)
    level = Column(Integer, primary_key=True)
    earned_at = Column(DateTime, default=datetime.utcnow)
    seen = Column(Boolean, nullable=False, default=False)


class UserProfile(Base):
    """La vitrine d'un joueur : jusqu'à 3 cartes choisies, en JSON."""
    __tablename__ = "user_profiles"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    showcase = Column(Text, nullable=False, default="[]")


class ShowcaseRequest(BaseModel):
    card_ids: List[str]


# ------------------------------------------------------------------ compteurs
def bump(db, user, key: str, n: int = 1, maximum: bool = False) -> None:
    """Ajoute n à un compteur (ou, avec maximum=True, garde la plus grande valeur). Ne fait jamais échouer l'appelant."""
    try:
        with db.begin_nested():
            row = db.query(UserCounter).filter_by(user_id=user.id, key=key).first()
            if row is None:
                db.add(UserCounter(user_id=user.id, key=key, value=max(0, int(n))))
            else:
                row.value = max(row.value, int(n)) if maximum else row.value + int(n)
    except Exception:
        pass


def _counter(db, user_id: str, key: str) -> int:
    row = db.query(UserCounter).filter_by(user_id=user_id, key=key).first()
    return int(row.value) if row else 0


# ------------------------------------------------------------------ mesures
def _tier_counts(db, user_id: str):
    """(cartes possédées par rareté, cartes existantes par rareté). Les cartes « Saison » (récompense du podium) ne comptent pas :
    elles ne peuvent pas se collectionner, donc elles n'entrent ni dans le pourcentage ni dans les séries complètes."""
    total = {t.value: n for t, n in db.query(Card.tier, func.count(Card.id)).group_by(Card.tier).all() if t.value != "saison"}
    owned = {t.value: n for t, n in db.query(Card.tier, func.count(Card.id))
             .join(OwnedCard, OwnedCard.card_id == Card.id)
             .filter(OwnedCard.user_id == user_id, OwnedCard.quantity > 0).group_by(Card.tier).all() if t.value != "saison"}
    return owned, total


def duel_stats(db, user_id: str) -> dict:
    mine = or_(Duel.challenger_id == user_id, Duel.defender_id == user_id)
    played = db.query(Duel).filter(mine).count()
    won = db.query(Duel).filter(or_(and_(Duel.challenger_id == user_id, Duel.score_challenger > Duel.score_defender),
                                    and_(Duel.defender_id == user_id, Duel.score_defender > Duel.score_challenger))).count()
    lost = db.query(Duel).filter(or_(and_(Duel.challenger_id == user_id, Duel.score_challenger < Duel.score_defender),
                                     and_(Duel.defender_id == user_id, Duel.score_defender < Duel.score_challenger))).count()
    return {"played": played, "won": won, "drawn": played - won - lost, "lost": lost,
            "win_rate": round(100 * won / played) if played else None}


def metrics(db, user) -> dict:
    owned, total = _tier_counts(db, user.id)
    total_cards = sum(total.values())
    owned_cards = sum(owned.values())
    duels = duel_stats(db, user.id)
    return {
        "collection": round(100 * owned_cards / total_cards, 1) if total_cards else 0.0,
        "packs": _counter(db, user.id, "open_packs"),
        "secretes": owned.get("secrete", 0),
        "epiques": owned.get("epique", 0),
        "legendaires": owned.get("legendaire", 0),
        "editions": sum(owned.get(k, 0) for k in game_logic.EDITION_TIERS),
        "series": sum(1 for t, n in total.items() if n > 0 and owned.get(t, 0) >= n),
        "variete": sum(1 for n in owned.values() if n > 0),
        "duel_played": duels["played"], "duel_won": duels["won"],
        "best_streak": _counter(db, user.id, "best_streak"),
        "bonus_days": _counter(db, user.id, "bonus_days"),
        "market": _counter(db, user.id, "market_buy") + _counter(db, user.id, "market_list"),
        "sell_dupes": _counter(db, user.id, "sell_dupes"),
    }


def _levels(ladder: dict) -> list:
    names = LEVEL_NAMES[len(ladder["goals"])]
    return [{"n": i + 1, "name": names[i], "goal": g, "reward": LEVEL_REWARD[names[i]]} for i, g in enumerate(ladder["goals"])]


# ------------------------------------------------------------------ attribution des succès
def check(db, user) -> list:
    """Donne les niveaux de succès atteints et pas encore gagnés (avec leurs crédits). Renvoie les nouveaux niveaux."""
    m = metrics(db, user)
    have = {(b.badge_id, b.level) for b in db.query(UserBadge).filter_by(user_id=user.id).all()}
    new = []
    for ladder in LADDERS:
        value = m[ladder["metric"]]
        for lv in _levels(ladder):
            if value >= lv["goal"] and (ladder["id"], lv["n"]) not in have:
                db.add(UserBadge(user_id=user.id, badge_id=ladder["id"], level=lv["n"], earned_at=datetime.utcnow(), seen=False))
                user.credits += lv["reward"]
                new.append({"id": ladder["id"], "title": ladder["title"], "icon": ladder["icon"], "level": lv["n"], "level_name": lv["name"], "reward": lv["reward"]})
    if new:
        db.commit()
    return new


def safe_unseen(db, user) -> list:
    """Les niveaux gagnés dont l'annonce n'a pas encore été vue (après vérification). Ne fait jamais échouer l'appelant."""
    try:
        check(db, user)
        by_id = {l["id"]: l for l in LADDERS}
        out = []
        for b in db.query(UserBadge).filter_by(user_id=user.id, seen=False).order_by(UserBadge.earned_at).all():
            lad = by_id.get(b.badge_id)
            if lad:
                lv = _levels(lad)[b.level - 1]
                out.append({"id": b.badge_id, "title": lad["title"], "icon": lad["icon"], "level": b.level, "level_name": lv["name"], "reward": lv["reward"]})
        return out
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return []


def mark_seen(db, user) -> None:
    db.query(UserBadge).filter_by(user_id=user.id, seen=False).update({"seen": True})
    db.commit()


def badges_out(db, user, award: bool = True) -> list:
    """Tous les succès d'un joueur avec leur avancement. (award=False : simple consultation, rien n'est attribué.)"""
    if award:
        check(db, user)
    m = metrics(db, user)
    earned = {(b.badge_id, b.level): b.earned_at for b in db.query(UserBadge).filter_by(user_id=user.id).all()}
    out = []
    for ladder in LADDERS:
        levels = [{**lv, "earned": (ladder["id"], lv["n"]) in earned,
                   "earned_at": earned[(ladder["id"], lv["n"])].date().isoformat() if (ladder["id"], lv["n"]) in earned else None} for lv in _levels(ladder)]
        got = [lv for lv in levels if lv["earned"]]
        nxt = next((lv for lv in levels if not lv["earned"]), None)
        out.append({"id": ladder["id"], "title": ladder["title"], "icon": ladder["icon"], "desc": ladder["desc"], "unit": ladder["unit"],
                    "value": m[ladder["metric"]], "levels": levels, "level": len(got), "level_name": got[-1]["name"] if got else None,
                    "next_goal": nxt["goal"] if nxt else None})
    return out


# ------------------------------------------------------------------ vitrine
def _showcase_ids(db, user) -> list:
    row = db.query(UserProfile).filter_by(user_id=user.id).first()
    try:
        ids = json.loads(row.showcase) if row else []
    except Exception:
        ids = []
    return ids if isinstance(ids, list) else []


def showcase_cards(db, user):
    """(cartes de la vitrine, vitrine_automatique). Les cartes que le joueur ne possède plus en sont retirées."""
    owned = {o.card_id for o in db.query(OwnedCard).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    chosen = [i for i in _showcase_ids(db, user) if i in owned][:SHOWCASE_MAX]
    if chosen:
        cards = {c.id: c for c in db.query(Card).filter(Card.id.in_(chosen)).all()}
        return [cards[i] for i in chosen if i in cards], False
    cards = db.query(Card).filter(Card.id.in_(owned)).all() if owned else []
    rank = {t: i for i, t in enumerate(TIER_VALUE_ORDER)}
    cards.sort(key=lambda c: (rank.get(c.tier.value, 99), c.player.name))
    return cards[:SHOWCASE_MAX], True


def set_showcase(db, user, card_ids: list) -> None:
    ids = list(dict.fromkeys(card_ids))             # sans doublons, dans l'ordre choisi
    if len(ids) > SHOWCASE_MAX:
        raise ValueError("Ta vitrine peut contenir %d cartes au maximum" % SHOWCASE_MAX)
    owned = {o.card_id for o in db.query(OwnedCard).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    if any(i not in owned for i in ids):
        raise ValueError("Tu ne peux mettre en vitrine que des cartes que tu possèdes")
    row = db.query(UserProfile).filter_by(user_id=user.id).first()
    if row is None:
        row = UserProfile(user_id=user.id)
        db.add(row)
    row.showcase = json.dumps(ids)
    db.commit()


# ------------------------------------------------------------------ profil public
def profile_out(db, user, rank=None) -> dict:
    """Ce que n'importe qui peut voir d'un joueur. Aucun nom de carte que le joueur n'a pas, aucun crédit."""
    owned, total = _tier_counts(db, user.id)
    total_cards = sum(total.values())
    owned_cards = sum(owned.values())
    upcoming = {k for k in game_logic.EDITION_TIERS if game_logic.edition_status(db, k) == "upcoming"}
    tiers = [{"tier": t, "owned": owned.get(t, 0), "total": total[t]} for t in TIER_VALUE_ORDER[::-1] if t in total and (t not in upcoming or owned.get(t, 0) > 0)]
    levels = badges_out(db, user, award=False)         # consulter le profil de quelqu'un ne lui attribue rien
    earned_levels = sum(b["level"] for b in levels)
    all_levels = sum(len(b["levels"]) for b in levels)
    top = [{"id": b["id"], "title": b["title"], "icon": b["icon"], "level": b["level"], "level_name": b["level_name"]} for b in levels if b["level"]]
    duels = duel_stats(db, user.id)
    return {
        "pseudo": user.pseudo, "member_since": user.created_at.date().isoformat() if user.created_at else None,
        "completion_pct": round(100 * owned_cards / total_cards, 1) if total_cards else 0.0, "cards_owned": owned_cards, "cards_total": total_cards,
        "rank": rank, "elo": user.elo, "duels": duels, "tiers": tiers,
        "packs_opened": _counter(db, user.id, "open_packs"), "best_streak": _counter(db, user.id, "best_streak"),
        "badges": {"earned": earned_levels, "total": all_levels, "top": top},
    }
