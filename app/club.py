"""
Défi du club : un défi PERMANENT contre une équipe fictive du club, contrôlée par le jeu (ce n'est pas un compte joueur).

- 3 NIVEAUX, chacun avec sa propre équipe : Facile (communes et rares), Normal (rares et épiques), Difficile (légendaires et éditions limitées).
- ÉQUIPE DU JOUR : chaque jour (jour de Paris), l'équipe de chaque niveau est tirée au hasard parmi les vrais joueurs de l'effectif, en suivant
  les postes d'une formation du 1v1 tirée elle aussi au hasard (comme la tactique et le capitaine). Elle est créée au premier accès de la journée,
  puis gardée en base : la même pour tout le monde toute la journée. Sans carte du bon poste et de la bonne rareté, on prend la rareté la plus proche
  du niveau, puis n'importe quelle carte du poste. Une édition limitée pas encore commencée n'est jamais choisie (elle reste une surprise).
  Le club n'utilise QUE des cartes qui existent : sans légendaire dans le jeu, le Difficile aligne les meilleures cartes existantes (épique, puis en dessous).
  Sa tactique reste secrète (le site ne la reçoit pas) : seul le récit d'un match la dévoile.
- BONUS : le club Difficile a un bonus d'équipe de +15 % (comme un Fan), réglé par simulation.
- MATCH : moteur du 1v1, comme au tournoi (tournament.simulate : ni mise, ni arbitre) ; en cas d'égalité, tirs au but. 3 essais par niveau, par jour
  et par joueur, gagnés ou perdus.
- RÉCOMPENSE : seulement la PREMIÈRE VICTOIRE du jour de chaque niveau : 5 / 10 / 15 crédits et 10 / 20 / 30 points de Pass (source « club »,
  60 au maximum par jour ; le doublement du Pass s'applique comme d'habitude). Rejouer reste possible, sans gain.
- AUCUN effet sur l'Elo, les statistiques et l'historique 1v1, les packs match ni les missions du jour. Seules les cartes du JOUEUR comptent dans
  « les cartes les plus utilisées » (weekly.record_usage) ; celles du club jamais.
- PALMARÈS « Tombeurs du club » (victoires Difficile, puis Normal, puis Facile) et titre « Tombeur du club » à 10 victoires au niveau Difficile.
"""
import json
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, User, gen_id
from .common import card_out, optional_user, require_admin
from .schemas import TeamPayload
from .security import get_current_user
from . import battlepass, challenges, duel_engine, game_logic, profiles, tournament, weekly

router = APIRouter()

LEVELS = {
    "facile": {"label": "Facile", "icon": "🟢", "tiers": ["commune", "rare"], "credits": 5, "points": 10, "bonus": 0.0},
    "normal": {"label": "Normal", "icon": "🟠", "tiers": ["rare", "epique"], "credits": 10, "points": 20, "bonus": 0.0},
    # bonus d'équipe du club Difficile (+15 %) : réglé par simulation pour qu'une équipe de légendaires gagne environ 35 à 50 % de ses matchs
    "difficile": {"label": "Difficile", "icon": "🔴", "tiers": ["legendaire"] + list(game_logic.EDITION_TIERS), "credits": 15, "points": 30, "bonus": 0.15},
}
TRIES_PER_DAY = 3
TITLE_WINS = 10                         # victoires au niveau Difficile pour le titre « Tombeur du club »
NEVER_PLAYED = {"secrete", "saison"}    # jamais dans l'équipe du club (la carte secrète et les trophées)
RNG = random.SystemRandom()              # (remplacé dans les tests)


class ClubTeam(Base):
    """L'équipe du club d'un niveau pour un jour donné (la même pour tout le monde)."""
    __tablename__ = "club_teams"
    __table_args__ = (UniqueConstraint("day", "level", name="uq_club_team_day_level"),)
    id = Column(String, primary_key=True, default=gen_id)
    day = Column(String, nullable=False, index=True)           # AAAA-MM-JJ (heure de Paris)
    level = Column(String, nullable=False)
    formation = Column(String, nullable=False)
    tactic = Column(String, nullable=False)
    captain_card_id = Column(String, nullable=True)
    slots = Column(Text, nullable=False)                        # JSON [{"card_id", "slot_category"}]
    created_at = Column(DateTime, default=datetime.utcnow)


class ClubMatch(Base):
    """Un match joué contre le club (historique, palmarès, récit)."""
    __tablename__ = "club_matches"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False, index=True)
    day = Column(String, nullable=False, index=True)
    level = Column(String, nullable=False)
    result = Column(String, nullable=False)                     # victoire / défaite (les tirs au but tranchent toujours)
    score_user = Column(Integer, nullable=False)
    score_club = Column(Integer, nullable=False)
    pens_user = Column(Integer, nullable=True)
    pens_club = Column(Integer, nullable=True)
    rewarded = Column(Boolean, nullable=False, default=False)  # la première victoire du jour de ce niveau
    counted = Column(Boolean, nullable=False, default=True)    # False après une remise à zéro par l'admin (ne compte plus comme essai)
    events_json = Column(Text, nullable=True)
    lineups_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ResetRequest(BaseModel):
    pseudo: str


def today() -> str:
    return game_logic.today_paris().isoformat()


def club_name(level: str) -> str:
    return "Club · " + LEVELS[level]["label"]


# ------------------------------------------------------------------ l'équipe du jour
def _rank(tier: str) -> int:
    order = game_logic.TIER_ORDER
    return order.index(tier) if tier in order else 0


def _pick_card(pool: list, tiers: list, rng):
    """Une carte de la rareté du niveau ; sinon de la rareté la plus proche du niveau (l'ordre des raretés fait foi).
    La distance se mesure aux raretés principales du niveau, sans les éditions limitées : elles sont rangées juste au-dessus de la rare,
    et sinon une rare passerait pour « proche » du niveau Difficile."""
    exact = [c for c in pool if c.tier.value in tiers]
    if exact:
        return rng.choice(exact)
    core = [t for t in tiers if t not in game_logic.EDITION_TIERS] or tiers
    dist = lambda c: min(abs(_rank(c.tier.value) - _rank(t)) for t in core)
    best = min(dist(c) for c in pool)
    return rng.choice([c for c in pool if dist(c) == best])


def generate_team(db: Session, level: str, rng=None) -> dict:
    """Tire une équipe valide pour un niveau : formation, tactique, 5 cartes de vrais joueurs aux bons postes, capitaine."""
    rng = rng or RNG
    formation = rng.choice(sorted(duel_engine.FORMATIONS)); tactic = rng.choice(sorted(duel_engine.TACTICS))
    hidden = {k for k in game_logic.EDITION_TIERS if game_logic.edition_status(db, k) == "upcoming"}
    cards = [c for c in db.query(Card).all()
             if game_logic.card_kind(c.player) == "joueur" and c.tier.value not in NEVER_PLAYED and c.tier.value not in hidden]
    if not cards:
        raise HTTPException(status_code=503, detail="Le club n'a encore aucun joueur à aligner")
    tiers = LEVELS[level]["tiers"]
    slots, used_players, used_cards = [], set(), set()
    for cat in ("GB", "DEF", "MC", "ATT"):
        for _ in range(duel_engine.FORMATIONS[formation][cat]):
            free = [c for c in cards if c.player_id not in used_players] or [c for c in cards if c.id not in used_cards]
            pool = ([c for c in free if duel_engine.poste_category(c.player.poste) == cat]          # le bon poste
                    or [c for c in free if duel_engine.poste_category(c.player.poste) is None]       # sinon un joueur sans poste précis (X)
                    or free)
            card = _pick_card(pool, tiers, rng)
            slots.append({"card_id": card.id, "slot_category": cat}); used_players.add(card.player_id); used_cards.add(card.id)
    return {"formation": formation, "tactic": tactic, "slots": slots, "captain_card_id": rng.choice(slots)["card_id"]}


def _valid(db: Session, row: ClubTeam) -> bool:
    ids = [s["card_id"] for s in json.loads(row.slots)]
    return db.query(Card).filter(Card.id.in_(ids)).count() == len(set(ids))


def team_of_day(db: Session, level: str, day: str = None) -> ClubTeam:
    """L'équipe du jour d'un niveau : créée au premier accès, puis toujours la même (refaite seulement si une de ses cartes a été supprimée)."""
    day = day or today()
    row = db.query(ClubTeam).filter_by(day=day, level=level).first()
    if row is not None and _valid(db, row):
        return row
    spec = generate_team(db, level)
    try:
        if row is None:
            row = ClubTeam(day=day, level=level)
            db.add(row)
        row.formation, row.tactic, row.captain_card_id, row.slots = spec["formation"], spec["tactic"], spec["captain_card_id"], json.dumps(spec["slots"])
        db.commit()
    except IntegrityError:                     # un autre joueur vient de la créer : on prend la sienne
        db.rollback()
        row = db.query(ClubTeam).filter_by(day=day, level=level).first()
    return row


def _team_cards(db: Session, row: ClubTeam) -> list:
    """[(Card, emplacement)] dans l'ordre de l'équipe."""
    slots = json.loads(row.slots)
    by_id = {c.id: c for c in db.query(Card).filter(Card.id.in_([s["card_id"] for s in slots])).all()}
    return [(by_id[s["card_id"]], s["slot_category"]) for s in slots if s["card_id"] in by_id]


def club_side(db: Session, level: str, row: ClubTeam):
    """L'équipe du club prête pour le moteur : ni Fan, ni Loup, ni équipement, mais le bonus d'équipe de son niveau."""
    side = {"pseudo": club_name(level), "formation": row.formation, "tactic": row.tactic, "team_bonus": LEVELS[level]["bonus"],
            "members": duel_engine.build_members(_team_cards(db, row), row.captain_card_id)}
    return side, None, [], None


def team_out(db: Session, row: ClubTeam) -> dict:
    """L'équipe telle que le site la montre : SANS sa tactique, qui reste secrète (le récit d'un match la dévoile)."""
    return {"formation": row.formation, "captain_card_id": row.captain_card_id,
            "cards": [{**card_out(c), "slot": cat, "captain": c.id == row.captain_card_id} for c, cat in _team_cards(db, row)]}


# ------------------------------------------------------------------ essais, victoires
def _today_rows(db: Session, user_id: str, level: str, day: str):
    return db.query(ClubMatch).filter_by(user_id=user_id, day=day, level=level, counted=True)


def tries_left(db: Session, user_id: str, level: str, day: str = None) -> int:
    return max(0, TRIES_PER_DAY - _today_rows(db, user_id, level, day or today()).count())


def rewarded_today(db: Session, user_id: str, level: str, day: str = None) -> bool:
    return _today_rows(db, user_id, level, day or today()).filter_by(rewarded=True).first() is not None


def wins_of(db: Session, user_id: str) -> dict:
    rows = db.query(ClubMatch.level, func.count()).filter_by(user_id=user_id, result="victoire").group_by(ClubMatch.level).all()
    out = {k: 0 for k in LEVELS}
    out.update({lv: n for lv, n in rows if lv in out})
    return out


def ranking(db: Session, limit: int = 10) -> list:
    """« Tombeurs du club » : victoires au niveau Difficile, puis Normal, puis Facile (les comptes de test n'y sont pas)."""
    per = {}
    for uid, lv, n in db.query(ClubMatch.user_id, ClubMatch.level, func.count()).filter(ClubMatch.result == "victoire").group_by(ClubMatch.user_id, ClubMatch.level).all():
        per.setdefault(uid, {k: 0 for k in LEVELS})[lv] = n
    users = {u.id: u for u in db.query(User).filter(User.id.in_(list(per)), User.is_test == False).all()} if per else {}     # noqa: E712
    rows = [{"pseudo": users[uid].pseudo, **w} for uid, w in per.items() if uid in users]
    rows.sort(key=lambda r: (-r["difficile"], -r["normal"], -r["facile"], r["pseudo"].lower()))
    return rows[:limit]


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(ClubMatch).filter_by(user_id=user_id).delete()


# ------------------------------------------------------------------ routes du site
def _level_or_404(level: str) -> str:
    level = (level or "").lower()
    if level not in LEVELS:
        raise HTTPException(status_code=404, detail="Niveau inconnu : facile, normal ou difficile")
    return level


@router.get("/club")
def get_club(viewer=Depends(optional_user), db: Session = Depends(get_db)):
    """Les 3 niveaux du jour : l'équipe du club, et pour le joueur connecté ses essais, sa récompense du jour et ses victoires."""
    day = today()
    wins = wins_of(db, viewer.id) if viewer else None
    levels = []
    for key, spec in LEVELS.items():
        row = team_of_day(db, key, day)
        item = {"level": key, "label": spec["label"], "icon": spec["icon"], "tiers": spec["tiers"], "name": club_name(key),
                "reward": {"credits": spec["credits"], "pass_points": spec["points"]}, "bonus_pct": round(spec["bonus"] * 100),
                "tries_max": TRIES_PER_DAY, "team": team_out(db, row)}
        if viewer:
            item.update({"tries_left": tries_left(db, viewer.id, key, day), "rewarded_today": rewarded_today(db, viewer.id, key, day), "my_wins": wins[key]})
        levels.append(item)
    out = {"day": day, "levels": levels, "title": {"label": "Tombeur du club", "needed": TITLE_WINS}}
    if viewer:
        out["title"].update({"hard_wins": wins["difficile"], "unlocked": profiles._counter(db, viewer.id, "club_hard_wins") >= TITLE_WINS})
        out["my_wins"] = wins
    return out


@router.get("/club/ranking")
def get_ranking(db: Session = Depends(get_db)):
    return ranking(db)


@router.post("/club/{level}/play")
def play(level: str, payload: TeamPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Joue un match contre l'équipe du club du jour (mêmes données d'équipe qu'au tournoi ; l'enveloppe de l'arbitre est ignorée)."""
    level = _level_or_404(level); day = today(); spec = LEVELS[level]
    if tries_left(db, user.id, level, day) <= 0:
        raise HTTPException(status_code=400, detail="Tu as joué tes %d essais du jour au niveau %s : reviens demain !" % (TRIES_PER_DAY, spec["label"]))
    challenges.check_no_trophy(db, payload.slots)
    slots = [{"card_id": s.card_id, "slot_category": s.slot_category} for s in payload.slots]
    try:
        cards, cap, fan, equip, mascot = duel_engine.validate_team(db, user, payload.formation, payload.tactic, slots, payload.captain_card_id,
                                                                    payload.fan_card_id, payload.equipment_card_ids, payload.mascot_card_id)
    except duel_engine.DuelError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    mine = ({"pseudo": user.pseudo, "formation": payload.formation, "tactic": payload.tactic,
             "members": duel_engine.build_members(cards, cap.id if cap else None)}, fan, equip, mascot)
    row = team_of_day(db, level, day)
    res = tournament.simulate(mine, club_side(db, level, row))
    res["lineups"]["defender"]["club_bonus_pct"] = round(spec["bonus"] * 100)          # (affiché dans les compositions du récit)
    su, sc = res["score"]; pens = res["pens"]
    won = (pens[0] > pens[1]) if pens else su > sc
    first = won and not rewarded_today(db, user.id, level, day)
    credits = pass_points = 0
    if first:
        credits = spec["credits"]; user.credits += credits
        pass_points = battlepass.add_points(db, user, "club", spec["points"], battlepass.DAILY_CAPS["club"])
    if won and level == "difficile":
        profiles.bump(db, user, "club_hard_wins")
    db.add(ClubMatch(user_id=user.id, day=day, level=level, result="victoire" if won else "défaite", score_user=su, score_club=sc,
                     pens_user=pens[0] if pens else None, pens_club=pens[1] if pens else None, rewarded=first,
                     events_json=json.dumps(res["events"], ensure_ascii=False), lineups_json=json.dumps(res["lineups"], ensure_ascii=False)))
    weekly.record_usage(db, "club", user.id, res["lineups"]["challenger"]["players"])        # seulement les cartes du joueur, jamais celles du club
    db.commit()
    left = tries_left(db, user.id, level, day)
    return {"duel_id": None, "date": datetime.utcnow().isoformat(), "challenger": user.pseudo, "defender": club_name(level),
            "score_challenger": su, "score_defender": sc, "stake": 0, "result": "victoire" if won else "défaite",
            "elo_challenger_before": None, "elo_challenger_after": None, "elo_defender_before": None, "elo_defender_after": None,
            "tactics": {"challenger": payload.tactic, "defender": row.tactic}, "events": res["events"], "lineups": res["lineups"],
            "club": {"level": level, "label": spec["label"], "icon": spec["icon"], "won": won, "bonus_pct": round(spec["bonus"] * 100), "pens": list(pens) if pens else None,
                     "rewarded": first, "credits": credits, "pass_points": pass_points, "tries_left": left, "tries_max": TRIES_PER_DAY,
                     "hard_wins": profiles._counter(db, user.id, "club_hard_wins"), "title_wins": TITLE_WINS},
            "credits_total": user.credits}


# ------------------------------------------------------------------ administration
@router.get("/admin/club", dependencies=[Depends(require_admin)])
def admin_club(db: Session = Depends(get_db)):
    """Les équipes du club du jour (créées si besoin) et le nombre de matchs joués aujourd'hui par niveau."""
    day = today(); out = []
    for key, spec in LEVELS.items():
        row = team_of_day(db, key, day)
        out.append({"niveau": spec["label"], "formation": row.formation, "tactique": row.tactic, "bonus": "+%d %%" % round(spec["bonus"] * 100),
                    "joueurs": ", ".join("%s (%s, %s%s)" % (c.player.name, c.tier.value, cat, ", capitaine" if c.id == row.captain_card_id else "") for c, cat in _team_cards(db, row)),
                    "matchs_aujourd_hui": db.query(ClubMatch).filter_by(day=day, level=key).count()})
    return {"jour": day, "equipes": out}


@router.post("/admin/club-reset", dependencies=[Depends(require_admin)])
def admin_club_reset(payload: ResetRequest, db: Session = Depends(get_db)):
    """Rend à un joueur ses 3 essais du jour à chaque niveau, et la possibilité de regagner la récompense (pour tester).
    Les matchs restent dans l'historique et le palmarès ; les crédits et points déjà gagnés ne sont pas repris."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    n = db.query(ClubMatch).filter_by(user_id=user.id, day=today(), counted=True).update({"counted": False}, synchronize_session=False)
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "matchs_remis_a_zero": n}
