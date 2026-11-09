"""
Tendances publiques des tactiques : sur le profil d'un joueur, la part de pressing, possession et contre-attaque, et la part des
trois formations, sur ses TREND_WINDOW (20) derniers matchs joués (1v1 et tournoi ; pas le défi du club, ni les forfaits).

- Table tactic_history : une ligne par équipe et par match réellement joué (utilisateur, date, mode, tactique, formation, match d'origine).
  Remplie par duel_engine.play_proposal (les deux équipes) et tournament._resolve (les deux joueurs, pas pour un forfait).
- Reprise de l'historique (une seule fois, verrou job_runs « tactic_trends_backfill ») : les duels (formation et tactique enregistrées ;
  la tactique peut manquer sur les tout premiers duels) et les matchs de tournoi joués (formation et tactique dans lineups_json).
- Confidentialité : seulement des pourcentages, jamais la tactique d'un match précis ni la dernière jouée. Moins de TREND_MIN (5) matchs :
  « pas assez de matchs ». Un défi publié et pas encore joué n'est jamais enregistré ici (sa tactique reste secrète).
"""
import json
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base

TREND_WINDOW = 20        # les 20 derniers matchs joués
TREND_MIN = 5            # en dessous : « pas assez de matchs »
TACTIC_KEYS = ("pressing", "possession", "contre")
FORMATION_KEYS = ("2-1-1", "1-2-1", "1-1-2")
BACKFILL_JOB = "tactic_trends_backfill"


class TacticHistory(Base):
    """La tactique et la formation d'une équipe dans un match joué (1v1 ou tournoi). Sans clé étrangère : nettoyée à la main."""
    __tablename__ = "tactic_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    played_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    mode = Column(String, nullable=False)                 # « 1v1 » ou « tournoi »
    tactic = Column(String, nullable=True)                # vide : ancien duel sans tactique enregistrée
    formation = Column(String, nullable=True)
    ref = Column(String, nullable=True, index=True)       # identifiant du duel ou du match de tournoi


def record(db: Session, mode: str, teams, ref=None, played_at=None) -> None:
    """teams : [(utilisateur, tactique, formation)] des équipes d'un match joué. Sans commit."""
    when = played_at or datetime.utcnow()
    for user_id, tactic, formation in teams:
        if user_id:
            db.add(TacticHistory(user_id=user_id, played_at=when, mode=mode, tactic=tactic or None, formation=formation or None, ref=ref))


def _shares(values, keys) -> dict:
    """Pourcentages entiers qui font 100 (méthode des plus forts restes ; départage dans l'ordre des clés)."""
    n = len(values)
    exact = {k: 100 * sum(1 for v in values if v == k) / n for k in keys}
    out = {k: int(exact[k]) for k in keys}
    rest = 100 - sum(out.values())
    for k in sorted(keys, key=lambda k: (-(exact[k] - out[k]), keys.index(k)))[:rest]:
        out[k] += 1
    return out


def trends(db: Session, user_id: str) -> dict:
    """Les tendances d'un joueur sur ses 20 derniers matchs : seulement des pourcentages, dans un ordre fixe."""
    rows = (db.query(TacticHistory.tactic, TacticHistory.formation).filter_by(user_id=user_id)
            .order_by(TacticHistory.played_at.desc(), TacticHistory.id.desc()).limit(TREND_WINDOW).all())
    tactics = [t for t, _ in rows if t in TACTIC_KEYS]
    formations = [f for _, f in rows if f in FORMATION_KEYS]
    out = {"window": TREND_WINDOW, "min_matches": TREND_MIN, "matches": len(rows),
           "tactics": None, "tactic_matches": len(tactics), "formations": None, "formation_matches": len(formations)}
    if len(tactics) >= TREND_MIN:
        out["tactics"] = _shares(tactics, TACTIC_KEYS)
    if len(formations) >= TREND_MIN:
        out["formations"] = _shares(formations, FORMATION_KEYS)
    out["enough"] = out["tactics"] is not None or out["formations"] is not None
    return out


def backfill(db: Session) -> int:
    """Reprend l'historique (duels et matchs de tournoi joués) une seule fois. Renvoie le nombre de lignes ajoutées."""
    from .models import Duel, JobRun
    from .tournament import TournamentMatch
    if db.get(JobRun, BACKFILL_JOB) is not None:
        return 0
    db.add(JobRun(name=BACKFILL_JOB, last_run_at=datetime.utcnow()))
    db.flush()                                            # (deux démarrages en même temps : le second échoue ici et ne fait rien)
    known = {r for (r,) in db.query(TacticHistory.ref).filter(TacticHistory.ref.isnot(None)).distinct().all()}
    added = 0
    for d in db.query(Duel).all():
        if d.id in known:
            continue
        record(db, "1v1", [(d.challenger_id, d.tactic_challenger, d.formation_challenger), (d.defender_id, d.tactic_defender, d.formation_defender)],
               ref=d.id, played_at=d.created_at)
        added += 2
    for m in db.query(TournamentMatch).filter_by(via="play").all():
        if m.id in known or not m.lineups_json:
            continue
        try:
            lu = json.loads(m.lineups_json)
        except ValueError:
            continue
        a, b = lu.get("challenger") or {}, lu.get("defender") or {}
        record(db, "tournoi", [(m.p1_id, a.get("tactic"), a.get("formation")), (m.p2_id, b.get("tactic"), b.get("formation"))],
               ref=m.id, played_at=m.decided_at or m.opens_at)
        added += 2
    db.query(JobRun).filter_by(name=BACKFILL_JOB).update({"last_report": json.dumps({"added": added})})
    db.commit()
    return added


def run_backfill(session_factory) -> None:
    """Au démarrage : la reprise de l'historique, sans jamais faire tomber le site."""
    db = session_factory()
    try:
        backfill(db)
    except Exception:
        db.rollback()
    finally:
        db.close()


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(TacticHistory).filter_by(user_id=user_id).delete()
