"""
Mode draft (12/11/2026, branche draft) : un match 1v1 EN DIRECT où les deux joueurs construisent leur équipe aux enchères, avec des cartes
du jeu (pas celles de leur collection). Mode de test : ouvert seulement aux comptes choisis dans l'administration (réglage « draft »).

Déroulé :
- SALON : un joueur crée une partie (ouverte à tous ceux qui ont accès, ou réservée à un invité, qui reçoit une notification). Elle attend
  WAIT_SECONDS (3 min) qu'un adversaire la rejoigne ; si le créateur ne regarde plus la page (HOST_AFK_WAITING), elle disparaît.
- TIRAGE SECRET : 10 cartes de vrais joueurs (10 personnes différentes) et 2 fans, présentés une à une dans un ordre au hasard. Le nombre de
  gardiens, défenseurs, milieux et attaquants change à chaque partie (1 à 3 gardiens, 2 à 4 par ligne) : on ne peut pas deviner ce qui reste.
  Raretés au hasard (TIER_WEIGHTS) : communes, rares, éditions, épiques, spéciales, légendaires ; jamais de secrète, de trophée ni d'édition
  pas encore commencée. Les cartes jouent au niveau 0, à 100 % de forme, sans Loup, équipement, arbitre ni avantage du terrain.
- ENCHÈRES OUVERTES : BUDGET (500) pièces chacune, valables pour ce match seulement. À chaque carte, celui qui parle en premier change
  (alternance). Celui dont c'est le tour mise (à partir de 0 pour la première mise, puis au moins MIN_STEP de plus) ou passe :
  passer sans aucune mise laisse la carte à l'adversaire pour 0 ; passer après une mise de l'adversaire la lui laisse à ce prix.
  BID_SECONDS pour répondre (sinon : il passe). On peut tomber à 0 pièce : on ne peut plus surenchérir et on subit les choix de l'adversaire.
  Chaque équipe a exactement 5 joueurs et au plus 1 fan : une équipe complète ne peut plus enchérir, la carte va d'office à l'autre.
- COMPOSITION : LINEUP_SECONDS (1 min) pour choisir la formation, la tactique, le poste de chaque joueur et le capitaine (sinon, la meilleure
  équipe est choisie automatiquement). Le match est calculé une seule fois (moteur du 1v1, tournament.simulate, match nul possible) et
  démarre sur les deux écrans en même temps (START_DELAY).
- RÉCOMPENSES comme en 1v1, avec les MÊMES compteurs du jour : pack match au gagnant, pack classique au perdant et aux deux en cas de nul,
  10 packs par jour au plus en 1v1 et draft confondus ; au-delà, 1 à 5 crédits (50 par jour au plus).
- CLASSEMENT draft à part (table draft_ratings, Elo de départ 1000) : un par mois (heure de Paris), donc remis à zéro chaque mois.
  Aucun effet sur l'Elo 1v1, la forme des cartes, les missions, le Pass ni les cartes les plus utilisées.
- ABANDON : un joueur qui ne donne plus signe de vie pendant les enchères (AFK_SECONDS) perd par forfait ; le bouton « Abandonner » aussi.
"""
import json
import random
from datetime import datetime, timedelta
from itertools import permutations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean, UniqueConstraint, or_
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import AppSetting, Card, User, gen_id
from .common import card_out, require_admin
from .security import get_current_user
from . import duel_engine as DE, game_logic, tournament

router = APIRouter()

SETTING_KEY = "draft"
BUDGET = 500
MIN_STEP = 5                     # surenchère minimale
N_PLAYERS = 2 * DE.TEAM_SIZE     # 10 joueurs : 5 par équipe
N_FANS = 2
WAIT_SECONDS = 180               # une partie attend un adversaire 3 minutes
HOST_AFK_WAITING = 30            # … tant que son créateur regarde la page
BID_SECONDS = 12                 # temps pour miser ou passer
LINEUP_SECONDS = 60              # temps pour composer l'équipe
START_DELAY = 4                  # le match démarre sur les deux écrans 4 secondes après la fin de la composition
AFK_SECONDS = 45                 # sans signe de vie pendant les enchères : forfait
ELO_START = 1000
TIER_WEIGHTS = {"commune": 34, "rare": 28, "edition": 10, "epique": 14, "speciale": 6, "legendaire": 8}
GB_COUNTS = {1: 15, 2: 60, 3: 25}   # nombre de gardiens dans le tirage (poids)
LINE_MIN, LINE_MAX = 2, 4           # défenseurs, milieux, attaquants : 2 à 4 de chaque
NEVER = {"secrete", "saison", "numerotee", "gold"}
SIDES = ("host", "guest")
ACTIVE = ("waiting", "bidding", "lineup")
RNG = random.SystemRandom()      # (remplaçable dans les tests)
_now = datetime.utcnow           # (remplaçable dans les tests)


class DraftRoom(Base):
    """Une partie draft : le salon, puis les enchères, la composition et le match. Le tirage reste dans `state` (jamais envoyé en entier)."""
    __tablename__ = "draft_rooms"
    id = Column(String, primary_key=True, default=gen_id)
    status = Column(String, nullable=False, default="waiting", index=True)   # waiting / bidding / lineup / done / cancelled / expired
    host_id = Column(String, nullable=False, index=True)
    guest_id = Column(String, nullable=True, index=True)
    invited_id = Column(String, nullable=True, index=True)
    season = Column(String, nullable=True)                                  # AAAA-MM (mois de Paris) du classement
    state = Column(Text, nullable=False, default="{}")
    deadline = Column(DateTime, nullable=True)                              # fin de l'attente, du tour d'enchère ou de la composition
    host_seen = Column(DateTime, nullable=True)
    guest_seen = Column(DateTime, nullable=True)
    result = Column(String, nullable=True)                                  # host / guest / draw
    forfeit = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class DraftRating(Base):
    """Classement draft d'un joueur pour un mois."""
    __tablename__ = "draft_ratings"
    __table_args__ = (UniqueConstraint("user_id", "season", name="uq_draft_rating"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    season = Column(String, nullable=False, index=True)
    elo = Column(Integer, nullable=False, default=ELO_START)
    played = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    draws = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)


class CreateRequest(BaseModel):
    invite: str = ""


class BidRequest(BaseModel):
    amount: int


class SlotIn(BaseModel):
    card_id: str
    slot_category: str


class LineupRequest(BaseModel):
    formation: str
    tactic: str
    slots: list[SlotIn]
    captain_card_id: str = None


class SettingsRequest(BaseModel):
    public: bool = None
    allowed: list[str] = None


class SeasonRequest(BaseModel):
    season: str = ""


class RoomRequest(BaseModel):
    room_id: str


# --------------------------------------------------------------------------------- réglages, accès ----
def get_settings(db: Session) -> dict:
    row = db.get(AppSetting, SETTING_KEY)
    s = {"public": False, "allowed": []}
    if row is not None:
        try:
            s.update({k: v for k, v in (json.loads(row.value) or {}).items() if k in s})
        except ValueError:
            pass
    return s


def _save_settings(db: Session, s: dict) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=json.dumps(s, ensure_ascii=False)))
    else:
        row.value = json.dumps(s, ensure_ascii=False)


def has_access(db: Session, user) -> bool:
    if user is None:
        return False
    s = get_settings(db)
    return bool(s["public"]) or user.pseudo.lower() in {p.lower() for p in s["allowed"]}


def _require_access(db, user):
    if not has_access(db, user):
        raise HTTPException(status_code=403, detail="Le mode draft n'est pas encore ouvert")


def season_now() -> str:
    return game_logic.today_paris(_now()).strftime("%Y-%m")


# --------------------------------------------------------------------------------- tirage des cartes ----
def _group(tier: str) -> str:
    return "edition" if tier in game_logic.EDITION_TIERS else tier


def _eligible(db: Session):
    hidden = {k for k in game_logic.EDITION_TIERS if game_logic.edition_status(db, k) == "upcoming"}
    players, fans = [], []
    for c in db.query(Card).all():
        t = c.tier.value
        if t in NEVER or t in hidden:
            continue
        kind = game_logic.card_kind(c.player)
        if kind == "joueur":                                   # (un joueur sans poste précis, X, complète n'importe quelle ligne)
            players.append(c)
        elif kind == "fan":
            fans.append(c)
    key = lambda c: c.id
    return sorted(players, key=key), sorted(fans, key=key)


def _pick_one(cands, used_people, rng):
    """Une carte d'une personne pas encore tirée : la rareté d'abord (TIER_WEIGHTS), puis la carte."""
    groups = {}
    for c in cands:
        if c.player_id not in used_people:
            groups.setdefault(_group(c.tier.value), []).append(c)
    if not groups:
        return None
    keys = sorted(groups)
    g = rng.choices(keys, weights=[TIER_WEIGHTS.get(k, 5) for k in keys])[0]
    return rng.choice(groups[g])


def line_counts(rng) -> dict:
    """Combien de gardiens, défenseurs, milieux et attaquants dans le tirage (10 en tout, change à chaque partie)."""
    keys = sorted(GB_COUNTS)
    counts = {"GB": rng.choices(keys, weights=[GB_COUNTS[k] for k in keys])[0], "DEF": LINE_MIN, "MC": LINE_MIN, "ATT": LINE_MIN}
    while sum(counts.values()) < N_PLAYERS:
        counts[rng.choice([l for l in ("DEF", "MC", "ATT") if counts[l] < LINE_MAX])] += 1
    return counts


def generate_pool(db: Session, rng=None) -> list:
    rng = rng or RNG
    players, fans = _eligible(db)
    lots, used = [], set()
    for line, n in line_counts(rng).items():
        for _ in range(n):
            c = _pick_one([c for c in players if DE.poste_category(c.player.poste) == line], used, rng) or _pick_one(players, used, rng)
            if c is None:
                raise HTTPException(status_code=503, detail="Pas assez de joueurs différents dans le jeu pour un draft")
            used.add(c.player_id); lots.append({"card_id": c.id, "kind": "joueur"})
    used_fans = set()
    for _ in range(N_FANS):
        c = _pick_one(fans, used_fans, rng)
        if c is not None:
            used_fans.add(c.player_id); lots.append({"card_id": c.id, "kind": "fan"})
    rng.shuffle(lots)
    return lots


# --------------------------------------------------------------------------------- enchères ----
def other(side: str) -> str:
    return "guest" if side == "host" else "host"


def _st(room) -> dict:
    return json.loads(room.state or "{}")


def _save(room, st) -> None:
    room.state = json.dumps(st, ensure_ascii=False)


def _needs(st, side, kind) -> bool:
    have = sum(1 for p in st["picks"][side] if p["kind"] == kind)
    return have < (DE.TEAM_SIZE if kind == "joueur" else 1)


def _award(room, st, side, price, how, now) -> None:
    lot = st["lots"][st["i"]]
    st["coins"][side] -= price
    st["picks"][side].append({"card_id": lot["card_id"], "kind": lot["kind"], "price": price})
    st["log"].append({"lot": st["i"] + 1, "card_id": lot["card_id"], "kind": lot["kind"], "to": side, "price": price, "how": how})
    st["i"] += 1
    _open_lot(room, st, now)


def _open_lot(room, st, now) -> None:
    """Ouvre la carte suivante (ou passe à la composition) ; une carte qu'une seule équipe peut prendre lui va d'office."""
    while st["i"] < len(st["lots"]):
        lot = st["lots"][st["i"]]
        want = [s for s in SIDES if _needs(st, s, lot["kind"])]
        if len(want) == 2:
            st["opener"] = st["turn"] = SIDES[st["i"] % 2]       # celui qui parle en premier change à chaque carte
            st["high"] = None
            room.deadline = now + timedelta(seconds=BID_SECONDS)
            return
        if len(want) == 1:
            side = want[0]
            st["picks"][side].append({"card_id": lot["card_id"], "kind": lot["kind"], "price": 0})
            st["log"].append({"lot": st["i"] + 1, "card_id": lot["card_id"], "kind": lot["kind"], "to": side, "price": 0, "how": "auto"})
        st["i"] += 1                                             # (personne ne peut la prendre : elle est écartée)
    st["high"] = st["turn"] = None
    st["lineups"] = {"host": None, "guest": None}
    room.status = "lineup"
    room.deadline = now + timedelta(seconds=LINEUP_SECONDS)


def min_bid(st) -> int:
    return 0 if st["high"] is None else st["high"]["amount"] + MIN_STEP


def do_bid(room, st, side, amount, now) -> None:
    if room.status != "bidding":
        raise HTTPException(status_code=400, detail="Les enchères sont terminées")
    if st["turn"] != side:
        raise HTTPException(status_code=400, detail="Ce n'est pas ton tour")
    amount = int(amount)
    if amount < min_bid(st):
        raise HTTPException(status_code=400, detail="Mise trop basse : %d pièces au moins" % min_bid(st))
    if amount > st["coins"][side]:
        raise HTTPException(status_code=400, detail="Tu n'as que %d pièces" % st["coins"][side])
    st["high"] = {"side": side, "amount": amount}
    opp = other(side)
    if st["coins"][opp] < amount + MIN_STEP:                     # l'adversaire ne peut pas surenchérir : la carte est à toi
        _award(room, st, side, amount, "bid", now)
        return
    st["turn"] = opp
    room.deadline = now + timedelta(seconds=BID_SECONDS)


def do_pass(room, st, side, now, how="pass") -> None:
    if room.status != "bidding":
        raise HTTPException(status_code=400, detail="Les enchères sont terminées")
    if st["turn"] != side:
        raise HTTPException(status_code=400, detail="Ce n'est pas ton tour")
    if st["high"] is None:                                       # passer sans mise : la carte va à l'adversaire, pour 0
        _award(room, st, other(side), 0, "given" if how == "pass" else "timeout", now)
    else:
        _award(room, st, st["high"]["side"], st["high"]["amount"], "bid", now)


# --------------------------------------------------------------------------------- composition ----
def _cards(db, ids) -> dict:
    return {c.id: c for c in db.query(Card).filter(Card.id.in_(list(ids))).all()} if ids else {}


def auto_lineup(cards: list, rng=None) -> dict:
    """La meilleure équipe possible avec ces 5 cartes : formation et postes qui donnent la plus grosse somme de notes (malus hors poste compris),
    capitaine = la meilleure note ; tactique au hasard."""
    rng = rng or RNG
    best = None
    for formation in ("1-2-1", "2-1-1", "1-1-2"):
        slots = [cat for cat in ("GB", "DEF", "MC", "ATT") for _ in range(DE.FORMATIONS[formation][cat])]
        for perm in permutations(range(len(cards))):
            total = 0.0
            for idx, slot in zip(perm, slots):
                c = cards[idx]; nat = DE.poste_category(c.player.poste)
                total += game_logic.card_note(c.player, c.tier.value, c) * (1 - DE.OUT_OF_POSITION_MALUS if nat and nat != slot else 1)
            if best is None or total > best[0] + 1e-9:
                best = (total, formation, [{"card_id": cards[i].id, "slot_category": s} for i, s in zip(perm, slots)])
    cap = max(cards, key=lambda c: (game_logic.card_note(c.player, c.tier.value, c), c.id))
    return {"formation": best[1], "tactic": rng.choice(sorted(DE.TACTICS)), "slots": best[2], "captain_card_id": cap.id, "auto": True}


def _check_lineup(st, side, p: LineupRequest) -> dict:
    if p.formation not in DE.FORMATIONS:
        raise HTTPException(status_code=400, detail="Formation inconnue")
    if p.tactic not in DE.TACTICS:
        raise HTTPException(status_code=400, detail="Tactique inconnue")
    mine = {x["card_id"] for x in st["picks"][side] if x["kind"] == "joueur"}
    ids = [s.card_id for s in p.slots]
    if len(ids) != DE.TEAM_SIZE or set(ids) != mine:
        raise HTTPException(status_code=400, detail="Place tes 5 joueurs, chacun une fois")
    need = DE.FORMATIONS[p.formation]
    got = {k: sum(1 for s in p.slots if s.slot_category == k) for k in need}
    if got != need:
        raise HTTPException(status_code=400, detail="La formation %s demande %s" % (p.formation, ", ".join("%d %s" % (n, DE.SLOT_LABELS[k].lower()) for k, n in need.items())))
    if p.captain_card_id and p.captain_card_id not in mine:
        raise HTTPException(status_code=400, detail="Le capitaine doit être un de tes joueurs")
    return {"formation": p.formation, "tactic": p.tactic, "slots": [{"card_id": s.card_id, "slot_category": s.slot_category} for s in p.slots],
            "captain_card_id": p.captain_card_id, "auto": False}


# --------------------------------------------------------------------------------- match, classement, récompenses ----
def rating(db: Session, user_id: str, season: str) -> DraftRating:
    r = db.query(DraftRating).filter_by(user_id=user_id, season=season).first()
    if r is None:
        r = DraftRating(user_id=user_id, season=season, elo=ELO_START, played=0, wins=0, draws=0, losses=0)
        db.add(r); db.flush()
    return r


def _rewards(db: Session, winner, classic_to) -> dict:
    """Comme en 1v1, avec les mêmes compteurs du jour (« duel_packs », « after_cap_credits ») : {pseudo: {"pack": …, "credits": …}}."""
    from . import missions
    out = {}

    def give(user, pack):
        if missions.daily_count(db, user, "duel_packs") < DE.DUEL_PACK_DAILY_CAP:
            missions.daily_add(db, user, "duel_packs")
            if pack == "match":
                user.pack_state.match_pack_tokens += 1
            else:
                user.pack_state.shop_pack_tokens += 1
            out[user.pseudo] = {"pack": pack, "credits": 0}
            return
        n = min(RNG.randint(*DE.AFTER_CAP_CREDITS), max(0, DE.AFTER_CAP_DAILY_MAX - missions.daily_count(db, user, "after_cap_credits")))
        if n > 0:
            user.credits += n
            missions.daily_add(db, user, "after_cap_credits", n)
        out[user.pseudo] = {"pack": None, "credits": n}

    if winner is not None:
        give(winner, "match")
    for u in classic_to:
        give(u, "classique")
    return out


def _finish(db, room, st, result, now, recap=None) -> None:
    """Enregistre le résultat : classement du mois, récompenses."""
    users = {s: db.get(User, getattr(room, s + "_id")) for s in SIDES}
    if any(u is None for u in users.values()):
        room.status, room.finished_at = "cancelled", now
        return
    ra, rb = rating(db, users["host"].id, room.season), rating(db, users["guest"].id, room.season)
    score_a = {"host": 1.0, "guest": 0.0, "draw": 0.5}[result]
    before = {"host": ra.elo, "guest": rb.elo}
    ra.elo, rb.elo = DE.elo_update(ra.elo, rb.elo, score_a)
    for r, s in ((ra, "host"), (rb, "guest")):
        r.played += 1
        if result == "draw":
            r.draws += 1
        elif result == s:
            r.wins += 1
        else:
            r.losses += 1
    if result == "draw":
        rewards = _rewards(db, None, [users["host"], users["guest"]])
    elif room.forfeit:
        rewards = _rewards(db, users[result], [])                # forfait : rien pour celui qui abandonne
    else:
        rewards = _rewards(db, users[result], [users[other(result)]])
    st["match"] = {**(recap or {}), "result": result, "forfeit": room.forfeit,
                   "elo": {s: {"before": before[s], "after": (ra if s == "host" else rb).elo} for s in SIDES},
                   "rewards": {s: rewards.get(users[s].pseudo) for s in SIDES},
                   "starts_at": (now + timedelta(seconds=START_DELAY)).isoformat() if recap else None}
    room.result, room.status, room.finished_at, room.deadline = result, "done", now, None


def _play(db, room, st, now) -> None:
    lots_cards = _cards(db, [p["card_id"] for s in SIDES for p in st["picks"][s]])
    if len(lots_cards) < len({p["card_id"] for s in SIDES for p in st["picks"][s]}):   # une carte supprimée entre-temps
        room.status, room.finished_at = "cancelled", now
        st["cancel_reason"] = "une carte a été supprimée du jeu"
        return
    users = {s: db.get(User, getattr(room, s + "_id")) for s in SIDES}
    for s in SIDES:
        if st["lineups"][s] is None:
            st["lineups"][s] = auto_lineup([lots_cards[p["card_id"]] for p in st["picks"][s] if p["kind"] == "joueur"])

    def prep(s):
        lu = st["lineups"][s]
        cws = [(lots_cards[x["card_id"]], x["slot_category"]) for x in lu["slots"]]
        fan = next((lots_cards[p["card_id"]] for p in st["picks"][s] if p["kind"] == "fan"), None)
        side = {"pseudo": users[s].pseudo, "formation": lu["formation"], "tactic": lu["tactic"], "levels": {},
                "members": DE.build_members(cws, lu["captain_card_id"])}
        return side, fan, [], None

    res = tournament.simulate(prep("host"), prep("guest"))
    sa, sb = res["score"]
    result = "host" if sa > sb else ("guest" if sb > sa else "draw")
    recap = {"challenger": users["host"].pseudo, "defender": users["guest"].pseudo, "score_challenger": sa, "score_defender": sb,
             "events": res["events"], "lineups": res["lineups"],
             "tactics": {"challenger": st["lineups"]["host"]["tactic"], "defender": st["lineups"]["guest"]["tactic"]}}
    _finish(db, room, st, result, now, recap)


def _forfeit(db, room, st, loser, now) -> None:
    room.forfeit = True
    st["forfeit_by"] = loser
    _finish(db, room, st, other(loser), now)


def advance(db: Session, room: DraftRoom, now=None) -> None:
    """Fait avancer une partie selon l'heure : attente expirée, tour d'enchère écoulé, composition finie, joueur parti."""
    now = now or _now()
    if room.status not in ACTIVE:
        return
    st = _st(room)
    for _ in range(40):
        if room.status == "waiting":
            if now >= room.deadline or (now - (room.host_seen or room.created_at)).total_seconds() > HOST_AFK_WAITING:
                room.status, room.finished_at = "expired", now
            break
        if room.status == "bidding":
            gone = [s for s in SIDES if (now - getattr(room, s + "_seen")).total_seconds() > AFK_SECONDS]
            if len(gone) == 2:
                room.status, room.finished_at = "cancelled", now; st["cancel_reason"] = "les deux joueurs sont partis"
                break
            if gone:
                _forfeit(db, room, st, gone[0], now)
                break
            if now >= room.deadline:
                do_pass(room, st, st["turn"], now, how="timeout")        # temps écoulé : il passe
                continue
            break
        if room.status == "lineup":
            if all(st["lineups"][s] for s in SIDES) or now >= room.deadline:
                _play(db, room, st, now)
            break
        break
    _save(room, st)


# --------------------------------------------------------------------------------- ce que voit le site ----
def side_of(room, user) -> str:
    return "host" if room.host_id == user.id else ("guest" if room.guest_id == user.id else None)


def _pseudo(db, uid):
    u = db.get(User, uid) if uid else None
    return u.pseudo if u else None


def room_out(db: Session, room: DraftRoom, user: User, now=None) -> dict:
    now = now or _now()
    me = side_of(room, user); opp = other(me) if me else None
    st = _st(room)
    rel = lambda s: "me" if s == me else "opp"
    out = {"id": room.id, "status": room.status, "host": _pseudo(db, room.host_id), "guest": _pseudo(db, room.guest_id),
           "invited": _pseudo(db, room.invited_id), "me": me,
           "remaining": max(0.0, (room.deadline - now).total_seconds()) if room.deadline and room.status in ACTIVE else None,
           "cancel_reason": st.get("cancel_reason")}
    if room.status == "waiting" or not st.get("lots"):
        return out
    ids = [p["card_id"] for s in SIDES for p in st["picks"][s]] + [l["card_id"] for l in st["log"]]
    cur = st["lots"][st["i"]] if room.status == "bidding" else None
    cards = _cards(db, set(ids) | ({cur["card_id"]} if cur else set()))
    co = lambda cid, extra: ({**card_out(cards[cid]), **extra} if cid in cards else {"id": cid, "player_name": "?", **extra})
    out.update({
        "coins": {"me": st["coins"][me], "opp": st["coins"][opp]},
        "picks": {rel(s): [co(p["card_id"], {"kind": p["kind"], "price": p["price"]}) for p in st["picks"][s]] for s in SIDES},
        "log": [{"lot": l["lot"], "card": co(l["card_id"], {"kind": l["kind"]}), "to": rel(l["to"]), "price": l["price"], "how": l["how"]} for l in st["log"]][::-1],
        "total_lots": len(st["lots"]), "budget": BUDGET, "min_step": MIN_STEP, "bid_seconds": BID_SECONDS, "lineup_seconds": LINEUP_SECONDS,
    })
    if cur:
        out["lot"] = {"number": st["i"] + 1, "card": co(cur["card_id"], {"kind": cur["kind"]}), "opener": rel(st["opener"]), "turn": rel(st["turn"]),
                      "high": {"by": rel(st["high"]["side"]), "amount": st["high"]["amount"]} if st["high"] else None, "min_bid": min_bid(st)}
        out["left"] = len(st["lots"]) - st["i"] - 1
    if room.status in ("lineup", "done") and st.get("lineups"):
        out["lineup"] = {"mine": st["lineups"][me], "submitted_opp": bool(st["lineups"][opp]) if room.status == "lineup" else True}
    if room.status == "done" and st.get("match"):
        m = st["match"]
        out["match"] = {**m, "result": "draw" if m["result"] == "draw" else rel(m["result"]),
                        "elo": {rel(s): v for s, v in m["elo"].items()}, "rewards": {rel(s): v for s, v in m["rewards"].items()},
                        "starts_in": max(0.0, (datetime.fromisoformat(m["starts_at"]) - now).total_seconds()) if m.get("starts_at") else None,
                        "forfeit_by": rel(st["forfeit_by"]) if st.get("forfeit_by") else None}
        out["match"].pop("starts_at", None)
    return out


def ranking(db: Session, season: str = None, limit: int = 30) -> list:
    season = season or season_now()
    rows = db.query(DraftRating).filter_by(season=season).all()
    users = {u.id: u for u in db.query(User).filter(User.id.in_([r.user_id for r in rows]), User.is_test == False).all()} if rows else {}   # noqa: E712
    out = [{"pseudo": users[r.user_id].pseudo, "elo": r.elo, "played": r.played, "wins": r.wins, "draws": r.draws, "losses": r.losses}
           for r in rows if r.user_id in users]
    out.sort(key=lambda r: (-r["elo"], -r["wins"], r["pseudo"].lower()))
    return out[:limit]


def _active_room(db, user):
    rooms = db.query(DraftRoom).filter(DraftRoom.status.in_(ACTIVE), or_(DraftRoom.host_id == user.id, DraftRoom.guest_id == user.id)).all()
    for r in rooms:
        advance(db, r)
    return next((r for r in rooms if r.status in ACTIVE), None)


def _seen(room, user, now):
    s = side_of(room, user)
    if s:
        setattr(room, s + "_seen", now)


def _locked(db, room_id) -> DraftRoom:
    room = db.query(DraftRoom).filter_by(id=room_id).with_for_update().first()
    if room is None:
        raise HTTPException(status_code=404, detail="Partie introuvable")
    return room


def _mine(db, room_id, user) -> tuple:
    room = _locked(db, room_id)
    side = side_of(room, user)
    if side is None:
        raise HTTPException(status_code=403, detail="Tu ne joues pas cette partie")
    now = _now(); _seen(room, user, now); advance(db, room, now)
    return room, side, now


# --------------------------------------------------------------------------------- routes ----
@router.get("/draft")
def get_draft(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Le salon du draft : ma partie en cours, les parties qui attendent un adversaire, le classement du mois."""
    _require_access(db, user)
    now = _now()
    mine = _active_room(db, user)
    if mine is not None:
        _seen(mine, user, now)
    waiting = db.query(DraftRoom).filter(DraftRoom.status == "waiting", DraftRoom.host_id != user.id,
                                         or_(DraftRoom.invited_id == None, DraftRoom.invited_id == user.id)).all()   # noqa: E711
    for r in waiting:
        advance(db, r, now)
    my_rating = db.query(DraftRating).filter_by(user_id=user.id, season=season_now()).first()
    out = {"access": True, "season": season_now(), "my_room": room_out(db, mine, user, now) if mine else None,
           "open_rooms": [{"id": r.id, "host": _pseudo(db, r.host_id), "invited": r.invited_id == user.id,
                           "remaining": max(0, int((r.deadline - now).total_seconds()))} for r in waiting if r.status == "waiting"],
           "ranking": ranking(db), "my_rating": {"elo": my_rating.elo, "played": my_rating.played} if my_rating else {"elo": ELO_START, "played": 0},
           "rules": {"budget": BUDGET, "min_step": MIN_STEP, "bid_seconds": BID_SECONDS, "lineup_seconds": LINEUP_SECONDS, "players": N_PLAYERS,
                     "fans": N_FANS, "wait_seconds": WAIT_SECONDS, "pack_cap": DE.DUEL_PACK_DAILY_CAP}}
    db.commit()
    return out


@router.post("/draft/create")
def create_room(payload: CreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Crée une partie : ouverte à tous ceux qui ont accès au draft, ou réservée à un invité (pseudo)."""
    _require_access(db, user)
    db.query(User).filter_by(id=user.id).with_for_update().first()        # (deux clics : une seule partie)
    if _active_room(db, user) is not None:
        db.commit()
        raise HTTPException(status_code=400, detail="Tu as déjà une partie en cours")
    invited = None
    name = (payload.invite or "").strip()
    if name:
        invited = db.query(User).filter(User.pseudo == name).first()
        if invited is None:
            raise HTTPException(status_code=404, detail="Joueur introuvable : " + name)
        if invited.id == user.id:
            raise HTTPException(status_code=400, detail="Tu ne peux pas t'inviter toi-même")
        if not has_access(db, invited):
            raise HTTPException(status_code=400, detail="%s n'a pas encore accès au mode draft" % invited.pseudo)
    now = _now()
    room = DraftRoom(host_id=user.id, invited_id=invited.id if invited else None, status="waiting", state="{}",
                     deadline=now + timedelta(seconds=WAIT_SECONDS), host_seen=now, created_at=now)
    db.add(room); db.flush()
    if invited is not None:
        from . import push
        push.safe(db, lambda d: push.enqueue(d, invited.id, "duels", "🃏 Invitation au draft",
                                             "%s t'invite à un match draft : 3 minutes pour le rejoindre" % user.pseudo, url="/#draft", tag="draft"))
    db.commit()
    return room_out(db, room, user, now)


@router.post("/draft/{room_id}/join")
def join_room(room_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_access(db, user)
    if _active_room(db, user) is not None:
        db.commit()
        raise HTTPException(status_code=400, detail="Tu as déjà une partie en cours")
    room = _locked(db, room_id); now = _now()
    advance(db, room, now)
    if room.status != "waiting":
        db.commit()
        raise HTTPException(status_code=400, detail="Cette partie n'attend plus d'adversaire")
    if room.host_id == user.id:
        raise HTTPException(status_code=400, detail="C'est ta propre partie")
    if room.invited_id and room.invited_id != user.id:
        raise HTTPException(status_code=403, detail="Cette partie est réservée à un autre joueur")
    lots = generate_pool(db)
    room.guest_id, room.status, room.season = user.id, "bidding", season_now()
    room.host_seen = room.guest_seen = now
    st = {"lots": lots, "i": 0, "coins": {"host": BUDGET, "guest": BUDGET}, "picks": {"host": [], "guest": []}, "log": [], "high": None,
          "turn": None, "opener": None}
    _open_lot(room, st, now)
    _save(room, st)
    db.commit()
    return room_out(db, room, user, now)


@router.post("/draft/{room_id}/cancel")
def cancel_room(room_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, side, now = _mine(db, room_id, user)
    if room.status != "waiting" or side != "host":
        db.commit()
        raise HTTPException(status_code=400, detail="La partie a déjà commencé : utilise « Abandonner »")
    room.status, room.finished_at = "cancelled", now
    db.commit()
    return {"status": "ok"}


@router.get("/draft/{room_id}")
def get_room(room_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """L'état de la partie (appelé chaque seconde par le site : il sert aussi de signe de vie)."""
    room, side, now = _mine(db, room_id, user)
    db.commit()
    return room_out(db, room, user, now)


@router.post("/draft/{room_id}/bid")
def bid(room_id: str, payload: BidRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, side, now = _mine(db, room_id, user)
    st = _st(room)
    try:
        do_bid(room, st, side, payload.amount, now)
    except HTTPException:
        db.commit(); raise
    _save(room, st); db.commit()
    return room_out(db, room, user, now)


@router.post("/draft/{room_id}/pass")
def pass_turn(room_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, side, now = _mine(db, room_id, user)
    st = _st(room)
    try:
        do_pass(room, st, side, now)
    except HTTPException:
        db.commit(); raise
    _save(room, st); db.commit()
    return room_out(db, room, user, now)


@router.post("/draft/{room_id}/lineup")
def set_lineup(room_id: str, payload: LineupRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, side, now = _mine(db, room_id, user)
    if room.status != "lineup":
        db.commit()
        raise HTTPException(status_code=400, detail="Ce n'est pas le moment de composer l'équipe")
    st = _st(room)
    st["lineups"][side] = _check_lineup(st, side, payload)
    _save(room, st)
    advance(db, room, now)                                       # les deux équipes sont prêtes : le match est joué tout de suite
    db.commit()
    return room_out(db, room, user, now)


@router.post("/draft/{room_id}/forfeit")
def forfeit(room_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, side, now = _mine(db, room_id, user)
    if room.status not in ("bidding", "lineup"):
        db.commit()
        raise HTTPException(status_code=400, detail="Il n'y a rien à abandonner")
    st = _st(room)
    _forfeit(db, room, st, side, now)
    _save(room, st); db.commit()
    return room_out(db, room, user, now)


@router.get("/draft-ranking")
def get_ranking(season: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_access(db, user)
    return {"season": season or season_now(), "ranking": ranking(db, season or None)}


def tick(db: Session) -> None:
    """Tâche de fond : fait avancer les parties abandonnées (attente expirée, tours écoulés, joueurs partis)."""
    for room in db.query(DraftRoom).filter(DraftRoom.status.in_(ACTIVE)).with_for_update(skip_locked=True).all():
        advance(db, room)
    db.commit()


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(DraftRating).filter_by(user_id=user_id).delete()
    db.query(DraftRoom).filter(or_(DraftRoom.host_id == user_id, DraftRoom.guest_id == user_id, DraftRoom.invited_id == user_id)).delete(synchronize_session=False)


# --------------------------------------------------------------------------------- administration ----
@router.get("/admin/draft", dependencies=[Depends(require_admin)])
def admin_draft(db: Session = Depends(get_db)):
    """Réglages du draft, parties en cours, 10 dernières parties, classement du mois."""
    pse = lambda uid: _pseudo(db, uid)
    active = db.query(DraftRoom).filter(DraftRoom.status.in_(ACTIVE)).all()
    last = db.query(DraftRoom).filter(DraftRoom.status == "done").order_by(DraftRoom.finished_at.desc()).limit(10).all()
    score = lambda r: (lambda m: "%s-%s" % (m.get("score_challenger", "—"), m.get("score_defender", "—")) if m else "")(_st(r).get("match"))
    return {"reglages": get_settings(db), "mois": season_now(),
            "en_cours": [{"id": r.id, "etat": r.status, "createur": pse(r.host_id), "adversaire": pse(r.guest_id) or pse(r.invited_id)} for r in active],
            "dernieres": [{"id": r.id, "createur": pse(r.host_id), "adversaire": pse(r.guest_id), "score": score(r), "resultat": r.result,
                           "forfait": r.forfeit, "fin": r.finished_at.isoformat() if r.finished_at else None} for r in last],
            "classement": ranking(db)}


@router.post("/admin/draft-settings", dependencies=[Depends(require_admin)])
def admin_draft_settings(payload: SettingsRequest, db: Session = Depends(get_db)):
    """Qui a accès au draft : « public » = tout le monde ; sinon seulement la liste « allowed » (pseudos exacts)."""
    s = get_settings(db)
    if payload.public is not None:
        s["public"] = bool(payload.public)
    if payload.allowed is not None:
        names = [n.strip() for n in payload.allowed if n and n.strip()]
        found = {u.pseudo for u in db.query(User).filter(User.pseudo.in_(names)).all()} if names else set()
        unknown = [n for n in names if n not in found]
        if unknown:
            raise HTTPException(status_code=400, detail="Pseudo(s) introuvable(s) : " + ", ".join(unknown))
        s["allowed"] = sorted(set(names), key=str.lower)
    _save_settings(db, s); db.commit()
    return {"status": "ok", "reglages": s}


@router.post("/admin/draft-reset-ranking", dependencies=[Depends(require_admin)])
def admin_draft_reset(payload: SeasonRequest, db: Session = Depends(get_db)):
    """Efface le classement draft d'un mois (vide : le mois en cours), par exemple après les essais. Les packs déjà gagnés restent."""
    season = (payload.season or "").strip() or season_now()
    n = db.query(DraftRating).filter_by(season=season).delete()
    db.commit()
    return {"status": "ok", "mois": season, "lignes_effacees": n}


@router.post("/admin/draft-cancel", dependencies=[Depends(require_admin)])
def admin_draft_cancel(payload: RoomRequest, db: Session = Depends(get_db)):
    """Annule une partie en cours, sans résultat ni récompense."""
    room = _locked(db, payload.room_id)
    if room.status not in ACTIVE:
        raise HTTPException(status_code=400, detail="Cette partie n'est plus en cours")
    st = _st(room); st["cancel_reason"] = "annulée par l'administrateur"; _save(room, st)
    room.status, room.finished_at = "cancelled", _now()
    db.commit()
    return {"status": "ok"}
