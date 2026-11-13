"""
Homme du match : le vote des joueurs du site après un match officiel du club, et le classement (privé) de la saison des votes.

- OUVERTURE : quand l'administrateur enregistre un résultat avec la case « match officiel : ouvrir le vote », le vote s'ouvre tout de
  suite pour 24 h exactement. On ne peut voter que pour les joueurs présents à CE match (champ « Joueurs présents » du formulaire,
  enregistré dans Match.lineup_json), et seulement les vrais joueurs (ni fans, ni mascotte, ni équipement, ni stade). Il en faut au moins 3.
- BULLETIN : tout compte connecté vote une fois par match en classant 3 joueurs différents (1er = 5 points, 2e = 3, 3e = 1). Il peut le
  modifier tant que le vote est ouvert.
- SECRET : pendant le vote, l'API publique ne montre ni nom classé ni point (seulement les présents, le nombre de votants, l'échéance
  et son propre bulletin). À la fermeture : le podium (3 premiers avec leurs points) et la carte obtenue. Les autres joueurs votés ne
  sont jamais publiés, mais leurs points restent en base (motm_points).
- FERMETURE : par la tâche de fond (toutes les minutes) ET au premier accès après l'échéance. Elle n'est appliquée qu'UNE fois
  (passage atomique du statut « open » à « closing »). Moins de MIN_BULLETINS bulletins : clôturé sans résultat ni carte.
- CARTES : on parcourt le classement complet (joueurs avec au moins 1 point). Chaque joueur qui a déjà sa légendaire gagne +2 de note
  (sans plafond) ; le premier qui n'en a pas reçoit sa légendaire, créée à son nom (une carte de plus dans le jeu) ; on s'arrête là.
  Si tous en ont une, tous gagnent +2.
- HOMME DU MATCH DES STATISTIQUES : si l'administrateur a laissé vide le champ « Homme du match » du match, le 1er du vote le devient.
- SAISON DES VOTES : créée par l'administrateur (nom, début, fin). Chaque vote clôturé avec résultat ajoute les points de TOUS ses
  joueurs votés au classement de la saison en cours. Ce classement n'est visible que par l'administrateur ; il le fige, puis publie
  le podium dans le chat quand il le décide. Aucune récompense automatique.
"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, Match, Player, Tier, User, gen_id
from .common import require_admin, optional_user
from .security import get_current_user
from . import game_logic

router = APIRouter()
VOTE_HOURS = 24
MIN_PLAYERS = 3                       # joueurs présents (vrais joueurs) nécessaires pour ouvrir un vote
MIN_BULLETINS = 3                     # en dessous : vote clôturé sans résultat ni carte
POINTS = (5, 3, 1)                    # 1er, 2e, 3e
LEGEND_BONUS = 2                      # +2 de note pour une légendaire déjà existante
HISTORY = 20


def now() -> datetime:
    """Heure UTC (sans fuseau). Remplacée dans les tests pour simuler l'horloge."""
    return datetime.utcnow()


class MotmVote(Base):
    """Un vote « Homme du match » (un par match réel). Sans clé étrangère : il survit à la suppression du match."""
    __tablename__ = "motm_votes"
    id = Column(String, primary_key=True, default=gen_id)
    match_id = Column(String, nullable=True, index=True)
    match_label = Column(String, nullable=False)
    match_date = Column(String, nullable=False)                 # AAAA-MM-JJ
    players_json = Column(Text, nullable=False)                 # noms des joueurs présents qu'on peut voter
    opens_at = Column(DateTime, nullable=False)
    closes_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="open")     # open / closing / closed / no_result / cancelled
    closed_at = Column(DateTime, nullable=True)
    ballots = Column(Integer, nullable=False, default=0)        # nombre de bulletins à la fermeture
    result_json = Column(Text, nullable=True)                   # podium et cartes (public)
    season_id = Column(String, nullable=True, index=True)       # saison des votes qui a reçu ses points


class MotmBallot(Base):
    __tablename__ = "motm_ballots"
    __table_args__ = (UniqueConstraint("vote_id", "user_id", name="uq_motm_ballot"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    vote_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    first = Column(String, nullable=False)
    second = Column(String, nullable=False)
    third = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MotmPoint(Base):
    """Points de CHAQUE joueur voté d'un vote clôturé (podium ou non). Jamais publiés en dehors du podium."""
    __tablename__ = "motm_points"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vote_id = Column(String, nullable=False, index=True)
    player_name = Column(String, nullable=False)
    points = Column(Integer, nullable=False)
    firsts = Column(Integer, nullable=False, default=0)
    seconds = Column(Integer, nullable=False, default=0)
    thirds = Column(Integer, nullable=False, default=0)
    rank = Column(Integer, nullable=False)


class MotmSeason(Base):
    """Saison des votes (privée) : son classement n'est visible que par l'administrateur."""
    __tablename__ = "motm_seasons"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    starts = Column(String, nullable=False)                     # AAAA-MM-JJ (inclus)
    ends = Column(String, nullable=False)                       # AAAA-MM-JJ (inclus)
    status = Column(String, nullable=False, default="open")     # open / closed
    frozen_json = Column(Text, nullable=True)                   # classement figé à la clôture
    published = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


# --------------------------------------------------------------------------- outils ----

def eligible_players(db: Session, names) -> list:
    """Les présents qu'on peut voter : vrais joueurs de l'effectif, sans doublon, dans l'ordre de la liste."""
    out = []
    for n in names or []:
        n = (n or "").strip()
        p = db.query(Player).filter_by(name=n).first() if n else None
        if p is not None and game_logic.card_kind(p) == "joueur" and p.name not in out:
            out.append(p.name)
    return out


def _players(v: MotmVote) -> list:
    return json.loads(v.players_json or "[]")


def _sort_key(r):
    return (-r["points"], -r["firsts"], -r["seconds"], -r["thirds"], r["player"])


def tally(db: Session, v: MotmVote) -> list:
    """Classement complet d'un vote à partir des bulletins (départage : points, 1res places, 2es, 3es, ordre alphabétique)."""
    rows = {}
    for b in db.query(MotmBallot).filter_by(vote_id=v.id).all():
        for i, name in enumerate((b.first, b.second, b.third)):
            r = rows.setdefault(name, {"player": name, "points": 0, "firsts": 0, "seconds": 0, "thirds": 0})
            r["points"] += POINTS[i]
            r[("firsts", "seconds", "thirds")[i]] += 1
    return sorted((r for r in rows.values() if r["points"] > 0), key=_sort_key)


def _legend_note(card: Card) -> int:
    return card.note or game_logic.CARD_NOTE["legendaire"]


def apply_cards(db: Session, ranking: list) -> dict:
    """Règle des cartes : +2 aux légendaires déjà existantes, du 1er au dernier, jusqu'au premier joueur sans légendaire,
    dont la carte est créée. Si tous en ont une, tous gagnent +2."""
    boosted, created = [], None
    for r in ranking:
        player = db.query(Player).filter_by(name=r["player"]).first()
        if player is None:
            continue
        leg = db.query(Card).filter_by(player_id=player.id, tier=Tier.legendaire).first()
        if leg is None and player.unique_card:                          # carte unique d'une autre rareté : pas de légendaire créée, on passe au suivant
            continue
        if leg is None:
            card = Card(player_id=player.id, tier=Tier.legendaire, vitesse=0, tir=0)
            db.add(card); db.flush()
            created = {"player": player.name, "note": game_logic.card_note(player, "legendaire", card)}
            break
        leg.note = _legend_note(leg) + LEGEND_BONUS                     # pas de plafond : 99, 101, 103…
        boosted.append({"player": player.name, "note": leg.note})
    return {"created": created, "boosted": boosted}


def current_season(db: Session, day: str):
    return (db.query(MotmSeason).filter(MotmSeason.status == "open", MotmSeason.starts <= day, MotmSeason.ends >= day)
            .order_by(MotmSeason.starts.desc()).first())


def _admin_note(text: str) -> None:
    """Une ligne dans le journal de l'administration (fermeture automatique sans résultat). Ne lève jamais d'exception."""
    try:
        from .database import SessionLocal
        from .admin_tools import AdminLog
        s = SessionLocal()
        try:
            s.add(AdminLog(method="AUTO", path="/motm/close", status=200, summary=text[:300], payload=None, ip=None)); s.commit()
        finally:
            s.close()
    except Exception:
        pass


def close_vote(db: Session, v: MotmVote, at: datetime = None) -> bool:
    """Ferme un vote ouvert et applique son résultat, UNE seule fois (passage atomique open -> closing). Fait le commit."""
    at = at or now()
    taken = db.query(MotmVote).filter(MotmVote.id == v.id, MotmVote.status == "open").update({"status": "closing"}, synchronize_session=False)
    if taken != 1:
        db.rollback()
        return False
    db.refresh(v)
    from . import chat, push
    n = db.query(MotmBallot).filter_by(vote_id=v.id).count()
    v.ballots, v.closed_at = n, at
    if n < MIN_BULLETINS:
        v.status, v.result_json = "no_result", json.dumps({"reason": "pas assez de votes"}, ensure_ascii=False)
        chat.add_event(db, "🏅 Homme du match (%s) : pas assez de votes (%d bulletin%s), pas de résultat cette fois." % (v.match_label, n, "s" if n > 1 else ""))
        db.commit()
        _admin_note("Homme du match %s : clôturé sans résultat (%d bulletin(s), %d nécessaires)" % (v.match_label, n, MIN_BULLETINS))
        return True
    ranking = tally(db, v)
    for i, r in enumerate(ranking):
        db.add(MotmPoint(vote_id=v.id, player_name=r["player"], points=r["points"], firsts=r["firsts"], seconds=r["seconds"], thirds=r["thirds"], rank=i + 1))
    cards = apply_cards(db, ranking)
    season = current_season(db, at.strftime("%Y-%m-%d"))
    v.season_id = season.id if season else None
    podium = [{"rank": i + 1, "player": r["player"], "points": r["points"]} for i, r in enumerate(ranking[:3])]
    v.result_json = json.dumps({"podium": podium, "created": cards["created"], "boosted": cards["boosted"]}, ensure_ascii=False)
    v.status = "closed"
    match = db.get(Match, v.match_id) if v.match_id else None              # le 1er devient l'homme du match des statistiques si le champ est vide
    if match is not None and match.motm_player_id is None and ranking:
        winner = db.query(Player).filter_by(name=ranking[0]["player"]).first()
        if winner is not None:
            match.motm_player_id = winner.id
            winner.homme_du_match_count = (winner.homme_du_match_count or 0) + 1
    text = "🏅 Homme du match (%s) : %s" % (v.match_label, ", ".join("%s %s (%d pts)" % ("🥇🥈🥉"[p["rank"] - 1], p["player"], p["points"]) for p in podium))
    if cards["created"]:
        text += " · nouvelle carte légendaire : %s" % cards["created"]["player"]
    if cards["boosted"]:
        text += " · légendaire +%d : %s" % (LEGEND_BONUS, ", ".join("%s (%d)" % (b["player"], b["note"]) for b in cards["boosted"]))
    chat.add_event(db, text)
    db.commit()
    body = "%s est l'homme du match !" % podium[0]["player"]
    if cards["created"]:
        body += " Nouvelle légendaire : %s." % cards["created"]["player"]
    if cards["boosted"]:
        body += " Légendaire +%d : %s." % (LEGEND_BONUS, ", ".join(b["player"] for b in cards["boosted"]))
    push.safe(db, push.notify_all, "cards", "Homme du match 🏅 " + v.match_label, body, url="/#actualite", tag="motm")
    return True


def close_due(db: Session, at: datetime = None) -> int:
    """Ferme tous les votes arrivés à échéance (tâche de fond et premier accès)."""
    at = at or now()
    n = 0
    for v in db.query(MotmVote).filter(MotmVote.status == "open", MotmVote.closes_at <= at).all():
        n += 1 if close_vote(db, v, at) else 0
    return n


def tick(db: Session) -> None:
    close_due(db)


def open_vote(db: Session, match: Match, names) -> MotmVote:
    """Ouvre le vote d'un match (sans commit). Refuse s'il y a moins de MIN_PLAYERS vrais joueurs présents."""
    players = eligible_players(db, names)
    if len(players) < MIN_PLAYERS:
        raise HTTPException(status_code=400, detail="Pour ouvrir le vote de l'homme du match, il faut au moins %d joueurs présents (fans, mascotte et équipements exclus) : il y en a %d." % (MIN_PLAYERS, len(players)))
    t = now()
    v = MotmVote(match_id=match.id, match_label="FC IPSA V — " + match.opponent, match_date=match.date.strftime("%Y-%m-%d"),
                 players_json=json.dumps(players, ensure_ascii=False), opens_at=t, closes_at=t + timedelta(hours=VOTE_HOURS), status="open")
    db.add(v)
    from . import chat
    chat.add_event(db, "🏅 Votez pour l'homme du match (%s), 24 h : onglet Actualité !" % v.match_label)
    return v


def notify_opened(db: Session, v: MotmVote) -> None:
    from . import push
    push.safe(db, push.notify_all, "cards", "Votez pour l'homme du match 🏅", v.match_label + " : vous avez 24 h pour voter.", url="/#actualite", tag="motm")


def cancel_for_match(db: Session, match_id: str) -> int:
    """Le match est supprimé : son vote encore ouvert est annulé (sans carte). Un vote déjà clôturé reste acquis. Sans commit."""
    n = 0
    for v in db.query(MotmVote).filter(MotmVote.match_id == match_id, MotmVote.status == "open").all():
        v.status, v.closed_at = "cancelled", now(); n += 1
    return n


def todo(db: Session, user: User) -> bool:
    """Un vote est ouvert et ce compte n'a pas encore voté (point rouge de l'onglet Actualité)."""
    t = now()
    for v in db.query(MotmVote).filter(MotmVote.status == "open", MotmVote.closes_at > t).all():
        if db.query(MotmBallot).filter_by(vote_id=v.id, user_id=user.id).first() is None:
            return True
    return False


def on_user_deleted(db: Session, user_id: str) -> None:
    for b in db.query(MotmBallot).filter_by(user_id=user_id).all():
        v = db.get(MotmVote, b.vote_id)
        if v is not None and v.status == "open":                # un vote encore ouvert perd ce bulletin ; un vote clôturé garde son résultat
            db.delete(b)


# ------------------------------------------------------------------------ vues publiques ----

def _photo(db: Session, name: str):
    p = db.query(Player).filter_by(name=name).first()
    return p.photo_url if p else None


def public_view(db: Session, v: MotmVote, user=None) -> dict:
    """Ce que voit le site. Vote ouvert : AUCUN nom classé ni point. Clôturé : le podium et les cartes seulement."""
    out = {"id": v.id, "match": v.match_label, "date": v.match_date, "status": "closed" if v.status == "closed" else v.status,
           "closes_at": v.closes_at.isoformat(), "players": [{"name": n, "photo_url": _photo(db, n)} for n in _players(v)]}
    if v.status == "open":
        out["voters"] = db.query(MotmBallot).filter_by(vote_id=v.id).count()
        mine = db.query(MotmBallot).filter_by(vote_id=v.id, user_id=user.id).first() if user else None
        out["my_ballot"] = [mine.first, mine.second, mine.third] if mine else None
    else:
        out["voters"] = v.ballots
        res = json.loads(v.result_json or "{}")
        if v.status == "closed":
            out["podium"] = [{**p, "photo_url": _photo(db, p["player"])} for p in res.get("podium", [])]
            out["created"], out["boosted"] = res.get("created"), res.get("boosted", [])
        if user is not None:
            mine = db.query(MotmBallot).filter_by(vote_id=v.id, user_id=user.id).first()
            out["my_ballot"] = [mine.first, mine.second, mine.third] if mine else None
    return out


@router.get("/motm")
def motm_state(user=Depends(optional_user), db: Session = Depends(get_db)):
    close_due(db)                                                         # fermeture à la volée au premier accès après l'échéance
    t = now()
    current = db.query(MotmVote).filter(MotmVote.status == "open").order_by(MotmVote.closes_at).all()
    past = (db.query(MotmVote).filter(MotmVote.status.in_(("closed", "no_result"))).order_by(MotmVote.closed_at.desc()).limit(HISTORY).all())
    return {"now": t.isoformat(), "min_ballots": MIN_BULLETINS, "points": list(POINTS),
            "current": [public_view(db, v, user) for v in current], "history": [public_view(db, v, user) for v in past]}


class BallotRequest(BaseModel):
    first: str
    second: str
    third: str


@router.post("/motm/{vote_id}/vote")
def motm_vote(vote_id: str, payload: BallotRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    close_due(db)
    v = db.get(MotmVote, vote_id)
    if v is None or v.status == "cancelled":
        raise HTTPException(status_code=404, detail="Vote introuvable")
    if v.status != "open" or v.closes_at <= now():
        raise HTTPException(status_code=400, detail="Ce vote est fermé : ton bulletin ne peut plus être modifié.")
    picks = [(payload.first or "").strip(), (payload.second or "").strip(), (payload.third or "").strip()]
    if not all(picks):
        raise HTTPException(status_code=400, detail="Choisis tes 3 joueurs : 1er, 2e et 3e.")
    if len(set(picks)) != 3:
        raise HTTPException(status_code=400, detail="Choisis 3 joueurs différents.")
    allowed = set(_players(v))
    bad = [p for p in picks if p not in allowed]
    if bad:
        raise HTTPException(status_code=400, detail="%s n'était pas présent à ce match." % bad[0])
    b = db.query(MotmBallot).filter_by(vote_id=v.id, user_id=user.id).first()
    if b is None:
        db.add(MotmBallot(vote_id=v.id, user_id=user.id, first=picks[0], second=picks[1], third=picks[2], updated_at=now()))
    else:
        b.first, b.second, b.third, b.updated_at = picks[0], picks[1], picks[2], now()
    db.commit()
    return {"status": "ok", "updated": b is not None, **public_view(db, v, user)}


# --------------------------------------------------------------------------- admin ----

class VoteRef(BaseModel):
    vote_id: str = ""                    # vide : le vote ouvert (s'il n'y en a qu'un)


class ExtendRequest(VoteRef):
    hours: int = Field(ge=1, le=168)


def _vote_for_admin(db: Session, vote_id: str, want_open: bool = True) -> MotmVote:
    vote_id = (vote_id or "").strip()
    if vote_id:
        v = db.get(MotmVote, vote_id)
        if v is None:
            raise HTTPException(status_code=404, detail="Vote introuvable")
        return v
    opened = db.query(MotmVote).filter_by(status="open").all() if want_open else []
    if len(opened) == 1:
        return opened[0]
    raise HTTPException(status_code=400, detail="Indique l'identifiant du vote (« Voir les votes de l'homme du match »)" if opened else "Aucun vote ouvert")


def admin_view(db: Session, v: MotmVote) -> dict:
    """Tout, pour l'administrateur : classement complet (même pendant le vote) et nombre de bulletins."""
    if v.status == "closed":                                              # points conservés à la fermeture
        ranking = [{"player": r.player_name, "points": r.points, "firsts": r.firsts, "seconds": r.seconds, "thirds": r.thirds}
                   for r in db.query(MotmPoint).filter_by(vote_id=v.id).order_by(MotmPoint.rank).all()]
    else:                                                                 # ouvert (ou sans résultat / annulé) : calcul à partir des bulletins
        ranking = tally(db, v)
    return {"id": v.id, "match": v.match_label, "date": v.match_date, "status": v.status, "opens_at": v.opens_at.isoformat(),
            "closes_at": v.closes_at.isoformat(), "ballots": db.query(MotmBallot).filter_by(vote_id=v.id).count(),
            "players": _players(v), "ranking": ranking, "result": json.loads(v.result_json) if v.result_json else None, "season_id": v.season_id}


@router.get("/admin/motm", dependencies=[Depends(require_admin)])
def admin_motm(db: Session = Depends(get_db)):
    close_due(db)
    rows = db.query(MotmVote).order_by(MotmVote.opens_at.desc()).limit(30).all()
    return [admin_view(db, v) for v in rows]


@router.post("/admin/motm-extend", dependencies=[Depends(require_admin)])
def admin_motm_extend(payload: ExtendRequest, db: Session = Depends(get_db)):
    v = _vote_for_admin(db, payload.vote_id)
    if v.status != "open":
        raise HTTPException(status_code=400, detail="Ce vote n'est plus ouvert")
    v.closes_at = v.closes_at + timedelta(hours=payload.hours)
    db.commit()
    return {"status": "ok", "match": v.match_label, "closes_at": v.closes_at.isoformat()}


@router.post("/admin/motm-close", dependencies=[Depends(require_admin)])
def admin_motm_close(payload: VoteRef, db: Session = Depends(get_db)):
    v = _vote_for_admin(db, payload.vote_id)
    if v.status != "open":
        raise HTTPException(status_code=400, detail="Ce vote n'est plus ouvert")
    v.closes_at = min(v.closes_at, now()); db.commit()
    close_vote(db, v)
    db.refresh(v)
    return {"status": "ok", **admin_view(db, v)}


@router.post("/admin/motm-cancel", dependencies=[Depends(require_admin)])
def admin_motm_cancel(payload: VoteRef, db: Session = Depends(get_db)):
    v = _vote_for_admin(db, payload.vote_id)
    if v.status != "open":
        raise HTTPException(status_code=400, detail="Seul un vote encore ouvert peut être annulé (un vote clôturé reste acquis)")
    v.status, v.closed_at = "cancelled", now()
    db.commit()
    return {"status": "ok", "match": v.match_label, "annule": True}


class SeasonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    starts: str
    ends: str


class SeasonRef(BaseModel):
    season_id: str = ""                  # vide : la saison ouverte la plus récente (ou la dernière clôturée pour la publication)


def _day(s: str) -> str:
    try:
        return datetime.fromisoformat((s or "").strip()).strftime("%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Date au format AAAA-MM-JJ")


def season_ranking(db: Session, season: MotmSeason) -> list:
    tot = {}
    vote_ids = [v.id for v in db.query(MotmVote).filter_by(season_id=season.id, status="closed").all()]
    for r in db.query(MotmPoint).filter(MotmPoint.vote_id.in_(vote_ids)).all() if vote_ids else []:
        t = tot.setdefault(r.player_name, {"player": r.player_name, "points": 0, "firsts": 0, "seconds": 0, "thirds": 0, "votes": 0})
        t["points"] += r.points; t["firsts"] += r.firsts; t["seconds"] += r.seconds; t["thirds"] += r.thirds; t["votes"] += 1
    return [{"rank": i + 1, **r} for i, r in enumerate(sorted(tot.values(), key=_sort_key))]


def _season(db: Session, season_id: str, status: str = None) -> MotmSeason:
    if (season_id or "").strip():
        s = db.get(MotmSeason, season_id.strip())
    else:
        q = db.query(MotmSeason)
        if status:
            q = q.filter_by(status=status)
        s = q.order_by(MotmSeason.created_at.desc()).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Saison des votes introuvable")
    return s


def _season_out(db: Session, s: MotmSeason) -> dict:
    ranking = json.loads(s.frozen_json) if s.frozen_json else season_ranking(db, s)
    return {"id": s.id, "name": s.name, "starts": s.starts, "ends": s.ends, "status": s.status, "published": bool(s.published),
            "votes": db.query(MotmVote).filter_by(season_id=s.id, status="closed").count(), "ranking": ranking,
            "podium": ranking[:3]}


@router.post("/admin/motm-season-create", dependencies=[Depends(require_admin)])
def admin_motm_season_create(payload: SeasonCreate, db: Session = Depends(get_db)):
    a, b = _day(payload.starts), _day(payload.ends)
    if b < a:
        raise HTTPException(status_code=400, detail="La fin de la saison doit être après son début")
    for s in db.query(MotmSeason).filter_by(status="open").all():
        if not (b < s.starts or a > s.ends):
            raise HTTPException(status_code=400, detail="Ces dates chevauchent la saison ouverte « %s »" % s.name)
    s = MotmSeason(name=payload.name.strip(), starts=a, ends=b)
    db.add(s); db.commit()
    return {**_season_out(db, s), "status": "ok"}


@router.get("/admin/motm-season", dependencies=[Depends(require_admin)])
def admin_motm_season(season_id: str = "", db: Session = Depends(get_db)):
    close_due(db)
    if not (season_id or "").strip():
        return [_season_out(db, s) for s in db.query(MotmSeason).order_by(MotmSeason.created_at.desc()).all()]
    return _season_out(db, _season(db, season_id))


@router.post("/admin/motm-season-close", dependencies=[Depends(require_admin)])
def admin_motm_season_close(payload: SeasonRef, db: Session = Depends(get_db)):
    close_due(db)
    s = _season(db, payload.season_id, "open")
    if s.status != "open":
        raise HTTPException(status_code=400, detail="Cette saison est déjà clôturée")
    s.frozen_json = json.dumps(season_ranking(db, s), ensure_ascii=False)
    s.status = "closed"
    db.commit()
    out = _season_out(db, s)
    labels = ("homme de la saison", "2e", "3e")
    out["annonce_privee"] = [("%s : %s (%d pts)" % (labels[i], r["player"], r["points"])) for i, r in enumerate(out["podium"])]
    return {**out, "status": "ok"}


@router.post("/admin/motm-season-publish", dependencies=[Depends(require_admin)])
def admin_motm_season_publish(payload: SeasonRef, db: Session = Depends(get_db)):
    s = _season(db, payload.season_id, "closed")
    if s.status != "closed":
        raise HTTPException(status_code=400, detail="Clôture d'abord la saison des votes")
    podium = json.loads(s.frozen_json or "[]")[:3]
    if not podium:
        raise HTTPException(status_code=400, detail="Cette saison n'a aucun point : rien à publier")
    from . import chat
    chat.add_event(db, "🏆 Homme de la saison « %s » : %s" % (s.name, ", ".join("%s %s (%d pts)" % ("🥇🥈🥉"[i], r["player"], r["points"]) for i, r in enumerate(podium))))
    s.published = 1
    db.commit()
    return {"status": "ok", "name": s.name, "podium": podium}
