"""
Tournoi 1v1 mensuel à élimination directe.

CALENDRIER (heure de Paris, chaque mois)
  - Du 1er au 7 inclus : INSCRIPTIONS. Chaque joueur paie le droit d'entrée ; les droits (plus un éventuel bonus du club) forment la cagnotte.
  - Le 8 à minuit : TIRAGE. Tous les inscrits participent (aucune limite). Têtes de série = les mieux classés en Elo ; le tableau est celui d'un
    tournoi classique : les meilleures têtes de série ne se rencontrent que tard, et s'il manque des joueurs pour remplir le premier tour, les
    mieux classés l'enjambent (« exempt »). On commence donc par les seizièmes, huitièmes, quarts… selon le nombre d'inscrits, jusqu'à la finale.
  - Le 8 à midi : le 1er tour s'ouvre. Chaque tour dure 24 h (midi → midi) : chacun compose son équipe en secret ; dès que les deux ont validé, le
    match est joué (moteur du 1v1) ; qui n'a pas validé à l'heure limite perd par FORFAIT (si les deux oublient, le mieux classé passe).
    Avec N inscrits il y a log2(N) tours : la finale se joue vers le 12 (16 joueurs), le 13 (32), le 14 (64) ou le 15 (128) : la fin du mois reste
    libre pour la course au classement Elo.
  - Égalité : TIRS AU BUT simulés, pondérés par la force des deux équipes.
  - Ces matchs ne comptent NI pour l'Elo, NI pour les statistiques de saison, et ne rapportent ni pack ni crédits.
RÉCOMPENSES : la cagnotte est répartie (vainqueur 50 %, finaliste 25 %, chacun des 2 demi-finalistes battus 12,5 % ; à 2 joueurs 70/30 ;
  à 3 joueurs 60/25/15) et le vainqueur reçoit un trophée de tournoi à son nom ; tout est annoncé dans le chat.
S'il y a moins de 2 inscrits au tirage, le tournoi est annulé et chacun est remboursé.
"""
import json
import random
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import AppSetting, User, gen_id
from .common import require_admin, optional_user
from .schemas import TeamPayload
from .security import get_current_user
from . import battlepass, challenges, duel_engine, game_logic, profiles, push, seasons
from .prono import now_paris

router = APIRouter()
REG_LAST_DAY, START_HOUR, ROUND_HOURS = 7, 12, 24
DEFAULT_FEE, MAX_FEE = 20, 500
ROUND_NAMES = {1: "Finale", 2: "Demi-finales", 4: "Quarts de finale", 8: "Huitièmes de finale", 16: "Seizièmes de finale",
               32: "Trente-deuxièmes de finale", 64: "Soixante-quatrièmes de finale"}


class Tournament(Base):
    __tablename__ = "tournaments"
    id = Column(String, primary_key=True, default=gen_id)
    month_key = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="registration")       # registration / running / finished / cancelled
    bonus = Column(Integer, nullable=False, default=0)                    # crédits offerts par le club, ajoutés à la cagnotte
    start_at = Column(DateTime, nullable=True)                            # ouverture du 1er tour
    size = Column(Integer, nullable=False, default=0)                     # taille du tableau (puissance de 2)
    rounds = Column(Integer, nullable=False, default=0)
    announced_round = Column(Integer, nullable=False, default=0)
    champion_id = Column(String, nullable=True)
    paid_out = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class TournamentEntry(Base):
    __tablename__ = "tournament_entries"
    __table_args__ = (UniqueConstraint("tournament_id", "user_id", name="uq_tournament_entry"),)
    id = Column(String, primary_key=True, default=gen_id)
    tournament_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    paid = Column(Integer, nullable=False, default=0)
    seed = Column(Integer, nullable=True)
    place = Column(Integer, nullable=True)                 # 1 vainqueur, 2 finaliste, 3 demi-finaliste
    eliminated_round = Column(Integer, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)


class TournamentMatch(Base):
    __tablename__ = "tournament_matches"
    id = Column(String, primary_key=True, default=gen_id)
    tournament_id = Column(String, nullable=False, index=True)
    round = Column(Integer, nullable=False)
    slot = Column(Integer, nullable=False)
    p1_id = Column(String, nullable=True)
    p2_id = Column(String, nullable=True)
    seed1 = Column(Integer, nullable=True)
    seed2 = Column(Integer, nullable=True)
    team1 = Column(Text, nullable=True)                    # l'équipe de chacun, secrète jusqu'au match
    team2 = Column(Text, nullable=True)
    sub1 = Column(DateTime, nullable=True)
    sub2 = Column(DateTime, nullable=True)
    winner_id = Column(String, nullable=True)
    score1 = Column(Integer, nullable=True)
    score2 = Column(Integer, nullable=True)
    pens1 = Column(Integer, nullable=True)
    pens2 = Column(Integer, nullable=True)
    via = Column(String, nullable=True)                    # play / forfeit / double_forfeit / bye
    state = Column(String, nullable=False, default="waiting")      # waiting / done
    opens_at = Column(DateTime, nullable=False)
    deadline_at = Column(DateTime, nullable=False)
    events_json = Column(Text, nullable=True)
    lineups_json = Column(Text, nullable=True)
    decided_at = Column(DateTime, nullable=True)


class SettingsRequest(BaseModel):
    entry_fee: Optional[int] = Field(default=None, ge=0, le=MAX_FEE)
    bonus: Optional[int] = Field(default=None, ge=0, le=10000)


# ------------------------------------------------------------------ calendrier et tableau
def ym(key: str):
    y, m = map(int, key.split("-")); return y, m


def reg_close(key: str) -> datetime:
    y, m = ym(key); return datetime(y, m, REG_LAST_DAY + 1, 0, 0)


def planned_start(key: str) -> datetime:
    y, m = ym(key); return datetime(y, m, REG_LAST_DAY + 1, START_HOUR, 0)


def round_name(matches_in_round: int) -> str:
    return ROUND_NAMES.get(matches_in_round, "Tour des %d" % (matches_in_round * 2))


def bracket_order(size: int) -> list:
    """Les têtes de série dans l'ordre du tableau : deux cases voisines se rencontrent au 1er tour (1 contre le dernier, etc.), et les meilleures
    têtes de série sont placées pour ne se croiser qu'en demi-finale ou en finale."""
    order = [1]
    n = 1
    while n < size:
        n *= 2
        order = [x for s in order for x in (s, n + 1 - s)]
    return order


def fee(db: Session) -> int:
    row = db.get(AppSetting, "tournament_fee")
    return int(row.value) if row is not None else DEFAULT_FEE


def current(db: Session, now: datetime):
    """Le tournoi du mois ; créé la première fois pendant les jours d'inscription."""
    key = seasons.key_of(now)
    t = db.query(Tournament).filter_by(month_key=key).first()
    if t is None and now.day <= REG_LAST_DAY:
        bonus_row = db.get(AppSetting, "tournament_next_bonus")
        t = Tournament(month_key=key, bonus=int(bonus_row.value) if bonus_row is not None else 0)
        if bonus_row is not None:
            db.delete(bonus_row)
        db.add(t); db.flush()
    return t


def _entries(db, t):
    return db.query(TournamentEntry).filter_by(tournament_id=t.id).all()


def pool_of(db, t) -> int:
    return sum(e.paid for e in _entries(db, t)) + t.bonus


def prize_shares(n: int) -> dict:
    """Parts de la cagnotte en millièmes : place 1 (vainqueur), 2 (finaliste), 3 (CHACUN des demi-finalistes battus)."""
    if n <= 2:
        return {1: 700, 2: 300}
    if n == 3:
        return {1: 600, 2: 250, 3: 150}
    return {1: 500, 2: 250, 3: 125}


def projected_prizes(pool: int, n: int) -> list:
    shares = prize_shares(max(n, 2)); out = []
    semis = 2 if n >= 4 else 1
    others = sum(pool * shares[p] // 1000 * (semis if p == 3 else 1) for p in shares if p != 1)
    out.append({"place": 1, "label": "Vainqueur", "amount": pool - others})
    out.append({"place": 2, "label": "Finaliste", "amount": pool * shares[2] // 1000})
    if 3 in shares:
        out.append({"place": 3, "label": "Chaque demi-finaliste battu" if n >= 4 else "Demi-finaliste battu", "amount": pool * shares[3] // 1000})
    return out


def _shootout(sa: float, sb: float):
    """Tirs au but : 5 tirs chacun puis mort subite. Le tireur de l'équipe la plus forte marque un peu plus souvent (de 55 % à 88 %)."""
    share = sa / (sa + sb) if (sa + sb) > 0 else 0.5
    pa = min(0.88, max(0.55, 0.75 + (share - 0.5) * 0.5)); pb = min(0.88, max(0.55, 0.75 + (0.5 - share) * 0.5))
    a = sum(1 for _ in range(5) if random.random() < pa); b = sum(1 for _ in range(5) if random.random() < pb)
    rounds = 0
    while a == b and rounds < 50:
        a += random.random() < pa; b += random.random() < pb; rounds += 1
    if a == b:                                              # (quasi impossible) on tranche selon la force
        if random.random() < share: a += 1
        else: b += 1
    return int(a), int(b)


def _prepare(db, user, spec):
    """Valide l'équipe enregistrée et la prépare pour le moteur ; None si elle n'est plus valable (cartes vendues…)."""
    if user is None or not spec:
        return None
    try:
        cards, cap, fan, equip, mascot = duel_engine.validate_team(db, user, spec["formation"], spec["tactic"], spec["slots"], spec.get("captain_card_id"),
                                                                    spec.get("fan_card_id"), spec.get("equipment_card_ids"), spec.get("mascot_card_id"))
    except duel_engine.DuelError:
        return None
    side = {"pseudo": user.pseudo, "formation": spec["formation"], "tactic": spec["tactic"], "members": duel_engine.build_members(cards, cap.id if cap else None)}
    return side, fan, equip, mascot


def simulate(prep_a, prep_b) -> dict:
    """Le match, avec le moteur du 1v1 (sans Elo, sans crédits, sans enregistrement dans l'historique 1v1)."""
    side_a, fan_a, eq_a, mas_a = prep_a; side_b, fan_b, eq_b, mas_b = prep_b
    wt = duel_engine.tactic_advantage(side_a["tactic"], side_b["tactic"])
    ma = 1 + duel_engine.TACTIC_BONUS if wt == "a" else 1.0; mb = 1 + duel_engine.TACTIC_BONUS if wt == "b" else 1.0
    att_a, def_a, *_ = duel_engine.team_powers(side_a["members"], fan_a, ma, eq_a, mas_a, 0.0)
    att_b, def_b, *_ = duel_engine.team_powers(side_b["members"], fan_b, mb, eq_b, mas_b, 0.0)
    xg_a, xg_b = duel_engine.expected_goals(att_a, def_b), duel_engine.expected_goals(att_b, def_a)
    sa, sb = duel_engine.poisson_random(xg_a), duel_engine.poisson_random(xg_b)
    events = duel_engine.build_events(side_a, side_b, sa, sb, xg_a, xg_b, wt)
    pens = _shootout(att_a + def_a, att_b + def_b) if sa == sb else None
    none_ref = {"challenger": 0, "defender": 0, "winner": None, "bonus_pct": 0}
    lineups = {"challenger": duel_engine._lineup_snapshot(side_a, fan_a, eq_a, mas_a, 0.0), "defender": duel_engine._lineup_snapshot(side_b, fan_b, eq_b, mas_b, 0.0), "referee": none_ref}
    return {"score": (sa, sb), "pens": pens, "events": events, "lineups": lineups}


# ------------------------------------------------------------------ déroulement
def _users(db, ids) -> dict:
    ids = [i for i in set(ids) if i]
    return {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}


def _chat(db, text, user=None):
    from . import chat
    chat.add_event(db, text, user)


def _push(db, user_id, title, body):
    push.safe(db, lambda d: push.enqueue(d, user_id, "duels", title, body, url="/#tournoi", tag="tournoi"))


def _cancel(db, t, reason: str):
    users = _users(db, [e.user_id for e in _entries(db, t)])
    for e in _entries(db, t):
        if e.user_id in users:
            users[e.user_id].credits += e.paid
    t.status, t.finished_at = "cancelled", datetime.utcnow()
    _chat(db, "🏆 Le tournoi de %s est annulé (%s). Les droits d'entrée sont remboursés." % (seasons.label_of(t.month_key), reason))


def _start(db, t, now):
    entries = _entries(db, t); users = _users(db, [e.user_id for e in entries])
    for e in [e for e in entries if e.user_id not in users]:
        db.delete(e)
    entries = [e for e in entries if e.user_id in users]
    if len(entries) < 2:
        _cancel(db, t, "il faut au moins 2 inscrits"); return
    ordered = sorted(entries, key=lambda e: (-users[e.user_id].elo, e.joined_at, users[e.user_id].pseudo))
    for i, e in enumerate(ordered):
        e.seed = i + 1
    n = len(ordered); size = 1 << max(1, (n - 1).bit_length()); rounds = size.bit_length() - 1
    start = planned_start(t.month_key)
    if now > start + timedelta(hours=6):                    # tirage en retard (site arrêté…) : les joueurs gardent leurs 24 h
        start = now
    t.start_at, t.size, t.rounds, t.status = start, size, rounds, "running"
    order = bracket_order(size); by_seed = {e.seed: e.user_id for e in ordered}; matches = {}
    for r in range(1, rounds + 1):
        opens = start + timedelta(hours=ROUND_HOURS * (r - 1))
        for i in range(size >> r):
            m = TournamentMatch(tournament_id=t.id, round=r, slot=i, opens_at=opens, deadline_at=opens + timedelta(hours=ROUND_HOURS)); db.add(m); matches[(r, i)] = m
    for i in range(size // 2):
        m = matches[(1, i)]; s1, s2 = order[2 * i], order[2 * i + 1]
        m.seed1, m.seed2 = (s1 if s1 <= n else None), (s2 if s2 <= n else None); m.p1_id, m.p2_id = by_seed.get(s1), by_seed.get(s2)
    db.flush()
    for i in range(size // 2):                                # les têtes de série sans adversaire passent le 1er tour
        m = matches[(1, i)]
        if (m.p1_id is None) != (m.p2_id is None):
            m.winner_id = m.p1_id or m.p2_id; m.via, m.state, m.decided_at = "bye", "done", now
            _advance_winner(db, t, m, matches)
    top = ordered[0]
    _chat(db, "🏆 Le tournoi de %s est lancé : %d joueurs, cagnotte de %d crédits ! Tête de série n°1 : %s. Le 1er tour (%s) s'ouvre à %dh : 24 h pour composer ton équipe." %
          (seasons.label_of(t.month_key), n, pool_of(db, t), users[top.user_id].pseudo, round_name(size // 2), start.hour))


def _advance_winner(db, t, m, matches=None):
    if m.round >= t.rounds:
        return
    nxt = (matches or {}).get((m.round + 1, m.slot // 2)) or db.query(TournamentMatch).filter_by(tournament_id=t.id, round=m.round + 1, slot=m.slot // 2).first()
    seed = db.query(TournamentEntry.seed).filter_by(tournament_id=t.id, user_id=m.winner_id).scalar()
    if m.slot % 2 == 0:
        nxt.p1_id, nxt.seed1 = m.winner_id, seed
    else:
        nxt.p2_id, nxt.seed2 = m.winner_id, seed


def _mark_loser(db, t, m, loser_id, now):
    e = db.query(TournamentEntry).filter_by(tournament_id=t.id, user_id=loser_id).first()
    if e is None:
        return
    e.eliminated_round = m.round
    if m.round == t.rounds:
        e.place = 2
    elif m.round == t.rounds - 1:
        e.place = 3


def _resolve(db, t, m, now):
    u1, u2 = db.get(User, m.p1_id), db.get(User, m.p2_id)
    prep1 = _prepare(db, u1, json.loads(m.team1)) if m.team1 else None
    prep2 = _prepare(db, u2, json.loads(m.team2)) if m.team2 else None
    if prep1 and prep2:
        res = simulate(prep1, prep2); m.score1, m.score2 = res["score"]; m.via = "play"
        if res["pens"]:
            m.pens1, m.pens2 = res["pens"]; m.winner_id = m.p1_id if m.pens1 > m.pens2 else m.p2_id
        else:
            m.winner_id = m.p1_id if m.score1 > m.score2 else m.p2_id
        m.events_json, m.lineups_json = json.dumps(res["events"], ensure_ascii=False), json.dumps(res["lineups"], ensure_ascii=False)
    elif prep1 or prep2:
        m.winner_id = m.p1_id if prep1 else m.p2_id; m.via = "forfeit"
    else:                                                      # personne n'a joué : le mieux classé passe
        m.winner_id = m.p1_id if (m.seed1 or 10 ** 9) <= (m.seed2 or 10 ** 9) else m.p2_id; m.via = "double_forfeit"
    loser = m.p2_id if m.winner_id == m.p1_id else m.p1_id
    m.state, m.decided_at = "done", now
    if m.round == t.rounds:                                    # la finale : le vainqueur est premier
        we = db.query(TournamentEntry).filter_by(tournament_id=t.id, user_id=m.winner_id).first()
        if we is not None: we.place = 1
    _mark_loser(db, t, m, loser, now); _advance_winner(db, t, m)
    pw, pl = (db.get(User, m.winner_id), db.get(User, loser))
    name = lambda u: u.pseudo if u else "(compte supprimé)"
    if pw: battlepass.add_points(db, pw, "tournoi", 20)                     # Pass de saison : un tour gagné, un match joué
    if pl and m.via == "play": battlepass.add_points(db, pl, "tournoi", 10)
    score = ("%d–%d" % (m.score1, m.score2) + (" (tirs au but %d–%d)" % (m.pens1, m.pens2) if m.pens1 is not None else "")) if m.via == "play" else "par forfait"
    if pw: _push(db, pw.id, "Tournoi : tu es qualifié 🏆", "Tu bats %s (%s) en %s." % (name(pl), score, round_name(t.size >> m.round).lower()))
    if pl: _push(db, pl.id, "Tournoi : éliminé", "%s te bat (%s) en %s. Merci d'avoir joué !" % (name(pw), score, round_name(t.size >> m.round).lower()))


def _finish(db, t, now):
    entries = _entries(db, t); users = _users(db, [e.user_id for e in entries]); n = len(entries)
    pool = sum(e.paid for e in entries) + t.bonus; shares = prize_shares(n)
    by_place = {}
    for e in entries:
        if e.place:
            by_place.setdefault(e.place, []).append(e)
    pay = {}
    for place in (2, 3):
        for e in by_place.get(place, []):
            pay[e.user_id] = pool * shares[place] // 1000
    champ = by_place.get(1, [None])[0]
    if champ is not None:
        pay[champ.user_id] = pool - sum(pay.values())
    for uid, amount in pay.items():
        if uid in users: users[uid].credits += amount
    t.status, t.finished_at, t.paid_out = "finished", now, sum(pay.values())
    fin_e = (by_place.get(2) or [None])[0]                     # le finaliste reçoit sa carte « Finaliste du tournoi (mois année) »
    if fin_e is not None and fin_e.user_id in users:
        owned2 = game_logic.get_or_create_owned(db, users[fin_e.user_id], seasons.get_or_create_trophy(db, t.month_key, 5)); owned2.quantity = max(owned2.quantity, 1)
    if champ is None or champ.user_id not in users:
        return
    t.champion_id = champ.user_id; winner = users[champ.user_id]
    card = seasons.get_or_create_trophy(db, t.month_key, 4)
    owned = game_logic.get_or_create_owned(db, winner, card); owned.quantity = max(owned.quantity, 1)
    profiles.bump(db, winner, "tournament_wins")
    fin = users.get(by_place.get(2, [None])[0].user_id) if by_place.get(2) else None
    semis = [users[e.user_id].pseudo for e in by_place.get(3, []) if e.user_id in users]
    _chat(db, "🏆 %s remporte le tournoi de %s et gagne %d crédits + le trophée !%s" % (winner.pseudo, seasons.label_of(t.month_key), pay[champ.user_id],
          (" Finaliste : %s." % fin.pseudo if fin else "") + (" Demi-finalistes : %s." % ", ".join(semis) if semis else "")), winner)
    for uid, amount in pay.items():
        if uid in users:
            _push(db, uid, "Tournoi terminé 🏆", "Tu reçois %d crédits%s." % (amount, " et le trophée du tournoi" if uid == champ.user_id else (" et la carte de finaliste" if fin_e is not None and uid == fin_e.user_id else "")))


def _announce(db, t, r, ms, now):
    users = _users(db, [m.p1_id for m in ms] + [m.p2_id for m in ms])
    playing = [m for m in ms if m.p1_id and m.p2_id and m.state != "done"]
    t.announced_round = r
    if not playing:
        return
    _chat(db, "⚽ %s du tournoi : %d match%s ouvert%s, 24 h pour composer ton équipe (onglet Tournoi) !" % (round_name(t.size >> r), len(playing), "s" if len(playing) > 1 else "", "s" if len(playing) > 1 else ""))
    for m in playing:
        for me, other in ((m.p1_id, m.p2_id), (m.p2_id, m.p1_id)):
            if me in users:
                _push(db, me, "Match de tournoi ouvert ⚽", "%s contre %s : tu as jusqu'au %s pour composer ton équipe." % (round_name(t.size >> r), users[other].pseudo if other in users else "?", m.deadline_at.strftime("%d/%m à %Hh%M")))


def _run_rounds(db, t, now):
    for r in range(1, t.rounds + 1):
        ms = db.query(TournamentMatch).filter_by(tournament_id=t.id, round=r).order_by(TournamentMatch.slot).all()
        if now >= ms[0].opens_at and t.announced_round < r:
            _announce(db, t, r, ms, now)
        late_resolved = False
        for m in ms:
            if m.state != "done" and m.p1_id and m.p2_id and now >= m.deadline_at:
                _resolve(db, t, m, now); late_resolved = True
        if any(m.state != "done" for m in ms):
            return
        # un tour réglé très en retard (site arrêté) : les tours suivants repartent de maintenant et gardent leurs 24 h (jamais décalé si le tour s'est fini à l'heure ou en avance)
        if late_resolved and r < t.rounds and now - ms[0].deadline_at > timedelta(minutes=30):
            for k in range(r + 1, t.rounds + 1):
                for m in db.query(TournamentMatch).filter_by(tournament_id=t.id, round=k).all():
                    m.opens_at = now + timedelta(hours=ROUND_HOURS * (k - r - 1)); m.deadline_at = m.opens_at + timedelta(hours=ROUND_HOURS)
    if t.status == "running":
        _finish(db, t, now)


def tick(db: Session, now: datetime = None) -> None:
    """À appeler souvent (toutes les minutes) : ouvre le tournoi du mois, tire au sort, ouvre les tours, règle les forfaits, verse la cagnotte."""
    now = now or now_paris()
    current(db, now)
    for t in db.query(Tournament).filter(Tournament.status.in_(("registration", "running"))).with_for_update().all():
        if t.status == "registration" and now >= reg_close(t.month_key):
            _start(db, t, now)
        if t.status == "running":
            _run_rounds(db, t, now)
    db.commit()


def todo(db: Session, user: User) -> bool:
    """Vrai si ce joueur a un match de tournoi OUVERT dont il n'a pas encore composé l'équipe (point rouge de l'onglet Tournoi)."""
    now = now_paris()
    rows = db.query(TournamentMatch).filter(TournamentMatch.state != "done", TournamentMatch.opens_at <= now, TournamentMatch.deadline_at > now,
                                            (TournamentMatch.p1_id == user.id) | (TournamentMatch.p2_id == user.id)).all()
    return any(m.p1_id and m.p2_id and not (m.team1 if m.p1_id == user.id else m.team2) for m in rows)


def on_user_deleted(db: Session, user_id: str) -> None:
    """Un compte supprimé disparaît des inscriptions ; en cours de tournoi, ses matchs se joueront par forfait."""
    for e in db.query(TournamentEntry).filter_by(user_id=user_id).all():
        t = db.get(Tournament, e.tournament_id)
        if t is not None and t.status == "registration":
            db.delete(e)


# ------------------------------------------------------------------ présentation
def _state(m, now):
    if m.state == "done": return "done"
    if not (m.p1_id and m.p2_id): return "waiting"
    return "open" if now >= m.opens_at else "soon"


def _player(users, uid, seed, avatars=None, cos=None):
    if not uid:
        return None
    u = users.get(uid)
    return {"pseudo": u.pseudo if u else "(compte supprimé)", "seed": seed, "elo": u.elo if u else None,
            "avatar": (avatars or {}).get(uid), "frame": ((cos or {}).get(uid) or (None, None))[1]}


def _match_out(m, users, now, avatars=None, cos=None):
    w = users.get(m.winner_id)
    return {"id": m.id, "round": m.round, "slot": m.slot, "state": _state(m, now), "opens_at": m.opens_at.isoformat(), "deadline_at": m.deadline_at.isoformat(),
            "p1": _player(users, m.p1_id, m.seed1, avatars, cos), "p2": _player(users, m.p2_id, m.seed2, avatars, cos),
            "winner": (w.pseudo if w else ("(compte supprimé)" if m.winner_id else None)), "via": m.via,
            "score": [m.score1, m.score2] if m.score1 is not None else None, "pens": [m.pens1, m.pens2] if m.pens1 is not None else None,
            "submitted": [bool(m.team1), bool(m.team2)], "replay": bool(m.events_json)}


@router.get("/tournament")
def get_tournament(viewer=Depends(optional_user), db: Session = Depends(get_db)):
    from . import avatars, cosmetics
    now = now_paris(); tick(db, now)
    key = seasons.key_of(now); t = db.query(Tournament).filter_by(month_key=key).first()
    nm = seasons.next_key(key); ny, nmo = ym(nm)
    out = {"now": now.isoformat(), "month": key, "label": seasons.label_of(key), "entry_fee": fee(db), "phase": "none",
           "next": {"label": seasons.label_of(nm), "registration_starts": datetime(ny, nmo, 1).isoformat(), "registration_ends": reg_close(nm).isoformat()}}
    if t is None:
        out["me"] = {"joined": False}; return out
    entries = _entries(db, t); users = _users(db, [e.user_id for e in entries]); av, cos = avatars.stamps(db), cosmetics.display_map(db)
    pool = sum(e.paid for e in entries) + t.bonus; n = len(entries); mine = next((e for e in entries if viewer and e.user_id == viewer.id), None)
    out.update({"phase": t.status, "entries": n, "pool": pool, "bonus": t.bonus, "prizes": projected_prizes(pool, n), "registration_ends": reg_close(key).isoformat(),
                "planned_start": (t.start_at or planned_start(key)).isoformat(), "rounds_total": t.rounds, "size": t.size})
    out["players"] = [{"pseudo": users[e.user_id].pseudo, "elo": users[e.user_id].elo, "seed": e.seed, "avatar": av.get(e.user_id), "frame": (cos.get(e.user_id) or (None, None))[1]}
                      for e in sorted([e for e in entries if e.user_id in users], key=lambda e: (e.seed or 10 ** 9, -users[e.user_id].elo, users[e.user_id].pseudo))]
    me = {"joined": mine is not None, "place": mine.place if mine else None, "eliminated": bool(mine and mine.eliminated_round), "match": None}
    if t.status in ("running", "finished"):
        ms = db.query(TournamentMatch).filter_by(tournament_id=t.id).order_by(TournamentMatch.round, TournamentMatch.slot).all()
        users.update(_users(db, [m.p1_id for m in ms] + [m.p2_id for m in ms] + [m.winner_id for m in ms]))
        out["rounds"] = [{"round": r, "name": round_name(t.size >> r), "opens_at": rs[0].opens_at.isoformat(), "deadline_at": rs[0].deadline_at.isoformat(),
                          "matches": [_match_out(m, users, now, av, cos) for m in rs]} for r in range(1, t.rounds + 1) for rs in [[m for m in ms if m.round == r]]]
        if viewer:
            mine_ms = [m for m in ms if viewer.id in (m.p1_id, m.p2_id)]
            cur = next((m for m in mine_ms if m.state != "done" and m.p1_id and m.p2_id), None) or (mine_ms[-1] if mine_ms else None)
            if cur:
                mo = _match_out(cur, users, now, av, cos); mo["me_side"] = 1 if cur.p1_id == viewer.id else 2
                mo["my_team_ready"] = bool(cur.team1 if mo["me_side"] == 1 else cur.team2); mo["round_name"] = round_name(t.size >> cur.round); me["match"] = mo
            played = [m for m in mine_ms if m.state == "done" and m.via != "bye"]
            if played and (cur is None or cur.id != played[-1].id):         # son dernier match terminé (quand le suivant est déjà annoncé)
                lo = _match_out(played[-1], users, now, av, cos); lo["me_side"] = 1 if played[-1].p1_id == viewer.id else 2; lo["round_name"] = round_name(t.size >> played[-1].round); me["last"] = lo
        champ = users.get(t.champion_id)
        out["champion"] = champ.pseudo if champ else None
    out["me"] = me
    return out


@router.get("/tournament/history")
def tournament_history(db: Session = Depends(get_db)):
    rows = db.query(Tournament).filter(Tournament.status.in_(("finished", "cancelled"))).order_by(Tournament.month_key.desc()).limit(12).all(); out = []
    for t in rows:
        entries = _entries(db, t); users = _users(db, [e.user_id for e in entries])
        nm = lambda p: [users[e.user_id].pseudo for e in entries if e.place == p and e.user_id in users]
        out.append({"month": t.month_key, "label": seasons.label_of(t.month_key), "status": t.status, "players": len(entries), "pool": sum(e.paid for e in entries) + t.bonus,
                    "champion": (nm(1) or [None])[0], "finalist": (nm(2) or [None])[0], "semifinalists": nm(3)})
    return out


@router.get("/tournament/matches/{match_id}/recap")
def match_recap(match_id: str, db: Session = Depends(get_db)):
    m = db.get(TournamentMatch, match_id)
    if m is None or m.state != "done" or not m.events_json:
        raise HTTPException(status_code=404, detail="Pas de récit pour ce match (il n'est pas terminé, ou il s'est joué par forfait)")
    t = db.get(Tournament, m.tournament_id); users = _users(db, [m.p1_id, m.p2_id]); u1, u2 = users.get(m.p1_id), users.get(m.p2_id)
    lineups = json.loads(m.lineups_json) if m.lineups_json else None
    return {"duel_id": None, "date": m.decided_at.isoformat(), "challenger": u1.pseudo if u1 else "?", "defender": u2.pseudo if u2 else "?", "score_challenger": m.score1, "score_defender": m.score2,
            "stake": 0, "elo_challenger_before": None, "elo_challenger_after": None, "elo_defender_before": None, "elo_defender_after": None,
            "tactics": {"challenger": lineups["challenger"]["tactic"] if lineups else None, "defender": lineups["defender"]["tactic"] if lineups else None},
            "events": json.loads(m.events_json), "lineups": lineups,
            "tournament": {"round_name": round_name(t.size >> m.round), "pens": [m.pens1, m.pens2] if m.pens1 is not None else None,
                           "winner": users[m.winner_id].pseudo if m.winner_id in users else None, "label": seasons.label_of(t.month_key)}}


@router.post("/tournament/join")
def join(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = now_paris(); tick(db, now); t = current(db, now)
    if t is None or t.status != "registration" or now >= reg_close(t.month_key):
        raise HTTPException(status_code=400, detail="Les inscriptions ont lieu du 1er au %d de chaque mois, à minuit" % REG_LAST_DAY)
    if db.query(TournamentEntry).filter_by(tournament_id=t.id, user_id=user.id).first():
        raise HTTPException(status_code=400, detail="Tu es déjà inscrit à ce tournoi")
    cost = fee(db)
    if user.credits < cost:
        raise HTTPException(status_code=400, detail="Il te faut %d crédits pour t'inscrire (tu en as %d)" % (cost, user.credits))
    user.credits -= cost
    db.add(TournamentEntry(tournament_id=t.id, user_id=user.id, paid=cost)); battlepass.add_points(db, user, "tournoi", 30); db.commit()
    return {"status": "ok", "paid": cost, "credits_total": user.credits, "entries": len(_entries(db, t)), "pool": pool_of(db, t)}


@router.delete("/tournament/join")
def leave(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = now_paris(); t = current(db, now)
    e = db.query(TournamentEntry).filter_by(tournament_id=t.id, user_id=user.id).first() if t else None
    if e is None:
        raise HTTPException(status_code=404, detail="Tu n'es pas inscrit")
    if t.status != "registration" or now >= reg_close(t.month_key):
        raise HTTPException(status_code=400, detail="Les inscriptions sont closes : tu ne peux plus te désinscrire")
    user.credits += e.paid; db.delete(e); db.commit()
    return {"status": "ok", "refunded": e.paid, "credits_total": user.credits}


@router.post("/tournament/matches/{match_id}/team")
def submit_team(match_id: str, payload: TeamPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = now_paris(); tick(db, now)
    m = db.query(TournamentMatch).filter_by(id=match_id).with_for_update().first()
    if m is None or user.id not in (m.p1_id, m.p2_id):
        raise HTTPException(status_code=404, detail="Match introuvable")
    t = db.get(Tournament, m.tournament_id)
    if m.state == "done" or t.status != "running":
        raise HTTPException(status_code=400, detail="Ce match est terminé")
    if not (m.p1_id and m.p2_id) or now < m.opens_at:
        raise HTTPException(status_code=400, detail="Ce match s'ouvre le %s à %s" % (m.opens_at.strftime("%d/%m"), m.opens_at.strftime("%Hh%M")))
    if now >= m.deadline_at:
        raise HTTPException(status_code=400, detail="Le temps est écoulé : le match va être réglé par forfait")
    challenges.check_no_trophy(db, payload.slots)
    try:
        duel_engine.validate_team(db, user, payload.formation, payload.tactic, [{"card_id": s.card_id, "slot_category": s.slot_category} for s in payload.slots], payload.captain_card_id, payload.fan_card_id, payload.equipment_card_ids, payload.mascot_card_id)
    except duel_engine.DuelError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    spec = json.dumps({"formation": payload.formation, "tactic": payload.tactic, "slots": [{"card_id": s.card_id, "slot_category": s.slot_category} for s in payload.slots], "captain_card_id": payload.captain_card_id,
                       "fan_card_id": payload.fan_card_id, "equipment_card_ids": payload.equipment_card_ids, "mascot_card_id": payload.mascot_card_id})
    if user.id == m.p1_id:
        m.team1, m.sub1 = spec, now
    else:
        m.team2, m.sub2 = spec, now
    resolved = False
    if m.team1 and m.team2:
        _resolve(db, t, m, now); resolved = True
        _run_rounds(db, t, now)
    db.commit()
    if not resolved:
        return {"status": "ok", "resolved": False, "recap": None}
    recap = match_recap(m.id, db) if m.events_json else None
    return {"status": "ok", "resolved": True, "recap": recap, "winner": db.get(User, m.winner_id).pseudo if db.get(User, m.winner_id) else None, "pens": [m.pens1, m.pens2] if m.pens1 is not None else None}


# ------------------------------------------------------------------ administration
@router.get("/admin/tournament", dependencies=[Depends(require_admin)])
def admin_tournament(db: Session = Depends(get_db)):
    now = now_paris(); t = db.query(Tournament).filter_by(month_key=seasons.key_of(now)).first()
    base = {"entry_fee": fee(db), "next_bonus": int((db.get(AppSetting, "tournament_next_bonus") or AppSetting(key="", value="0")).value)}
    if t is None:
        return {**base, "tournament": None}
    return {**base, "tournament": {"month": t.month_key, "status": t.status, "entries": len(_entries(db, t)), "pool": pool_of(db, t), "bonus": t.bonus, "rounds": t.rounds, "size": t.size,
                                   "start_at": t.start_at.isoformat() if t.start_at else None}}


@router.post("/admin/tournament-settings", dependencies=[Depends(require_admin)])
def admin_tournament_settings(payload: SettingsRequest, db: Session = Depends(get_db)):
    """Droit d'entrée (pour les prochains inscrits) et bonus du club (ajouté à la cagnotte du tournoi du mois, ou du prochain s'il n'a pas encore commencé)."""
    now = now_paris()
    if payload.entry_fee is not None:
        row = db.get(AppSetting, "tournament_fee")
        if row is None: db.add(AppSetting(key="tournament_fee", value=str(payload.entry_fee)))
        else: row.value = str(payload.entry_fee)
    if payload.bonus is not None:
        t = current(db, now)
        if t is not None and t.status in ("registration", "running"):
            t.bonus = payload.bonus
        else:
            row = db.get(AppSetting, "tournament_next_bonus")
            if row is None: db.add(AppSetting(key="tournament_next_bonus", value=str(payload.bonus)))
            else: row.value = str(payload.bonus)
    db.commit()
    return {"status": "ok", "entry_fee": fee(db)}


@router.post("/admin/tournament-cancel", dependencies=[Depends(require_admin)])
def admin_tournament_cancel(db: Session = Depends(get_db)):
    """Annule le tournoi du mois (en inscription ou en cours) : tous les droits d'entrée sont remboursés."""
    t = db.query(Tournament).filter_by(month_key=seasons.key_of(now_paris())).first()
    if t is None or t.status not in ("registration", "running"):
        raise HTTPException(status_code=404, detail="Aucun tournoi à annuler ce mois-ci")
    _cancel(db, t, "décision du club"); db.commit()
    return {"status": "ok"}
