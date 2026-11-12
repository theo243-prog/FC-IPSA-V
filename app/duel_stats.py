"""
Mes stats 1v1 (12/11/2026, branche stats-1v1) : le bilan PERSONNEL d'un joueur en 1v1, calculé à partir des matchs enregistrés (table duels).
Visible seulement par le joueur lui-même (route GET /duel/my-stats, compte connecté) : ses adversaires, ses cartes et ses choix ne sont
jamais montrés aux autres. Seulement les matchs 1v1 (ni tournoi, ni défi du club, ni draft).

- Bilan : matchs, victoires, nuls, défaites, buts pour / contre, % de victoires, plus grosse victoire, meilleure série de victoires et série en cours.
- Face à face : le bilan contre chaque adversaire (le plus affronté d'abord).
- Mes cartes : les plus alignées (avec leurs victoires), mes buteurs et mes passeurs (récits des matchs), mes formations et tactiques.
- Période : `scope` = « all » (depuis le début) ou « month » (la saison en cours, mois de Paris). Les anciens matchs sans récit ni composition
  comptent dans le bilan, pas dans les cartes, buteurs et tactiques.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .database import get_db
from .models import Duel, User
from .security import get_current_user
from . import seasons

router = APIRouter()
TOP = 8            # nombre de lignes des listes (cartes, buteurs, passeurs)


def _result(mine: int, theirs: int) -> str:
    return "V" if mine > theirs else ("D" if mine < theirs else "N")


def stats_for(db: Session, user: User, scope: str = "all") -> dict:
    q = db.query(Duel).filter(or_(Duel.challenger_id == user.id, Duel.defender_id == user.id))
    key = None
    if scope == "month":
        key = seasons.current_key(); start, end = seasons.bounds(key)
        q = q.filter(Duel.created_at >= start, Duel.created_at < end)
    duels = q.order_by(Duel.created_at, Duel.id).all()
    tot = {"played": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0}
    opp, cards, scorers, assists, forms, tacts = {}, {}, {}, {}, {}, {}
    best_streak = run = 0
    biggest = None
    results = []
    for d in duels:
        side = "challenger" if d.challenger_id == user.id else "defender"
        mine, theirs = (d.score_challenger, d.score_defender) if side == "challenger" else (d.score_defender, d.score_challenger)
        other = d.defender if side == "challenger" else d.challenger
        r = _result(mine, theirs); results.append(r)
        key_r = {"V": "wins", "N": "draws", "D": "losses"}[r]
        tot["played"] += 1; tot[key_r] += 1; tot["goals_for"] += mine; tot["goals_against"] += theirs
        name = other.pseudo if other is not None else "(compte supprimé)"
        o = opp.setdefault(name, {"pseudo": name, "played": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0})
        o["played"] += 1; o[key_r] += 1; o["goals_for"] += mine; o["goals_against"] += theirs
        run = run + 1 if r == "V" else 0
        best_streak = max(best_streak, run)
        if r == "V" and (biggest is None or (mine - theirs, mine) > (biggest["diff"], biggest["for"])):
            biggest = {"diff": mine - theirs, "for": mine, "against": theirs, "opponent": name, "date": d.created_at.isoformat()}
        formation = d.formation_challenger if side == "challenger" else d.formation_defender
        tactic = d.tactic_challenger if side == "challenger" else d.tactic_defender
        for bucket, k in ((forms, formation), (tacts, tactic)):
            if k:
                b = bucket.setdefault(k, {"played": 0, "wins": 0}); b["played"] += 1; b["wins"] += r == "V"
        try:
            lineup = (json.loads(d.lineups_json) if d.lineups_json else {}).get(side) or {}
        except ValueError:
            lineup = {}
        for p in lineup.get("players") or []:
            c = cards.setdefault((p.get("player"), p.get("tier")), {"player": p.get("player"), "tier": p.get("tier"), "played": 0, "wins": 0})
            c["played"] += 1; c["wins"] += r == "V"
        try:
            events = json.loads(d.events_json) if d.events_json else []
        except ValueError:
            events = []
        for ev in events:
            if ev.get("kind") == "goal" and ev.get("side") == side:
                if ev.get("scorer"):
                    scorers[ev["scorer"]] = scorers.get(ev["scorer"], 0) + 1
                if ev.get("assist"):
                    assists[ev["assist"]] = assists.get(ev["assist"], 0) + 1
    current = None
    if results:
        last = results[-1]; n = 0
        for r in reversed(results):
            if r != last:
                break
            n += 1
        current = {"result": last, "count": n}
    top = lambda m: [{"player": k, "count": v} for k, v in sorted(m.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:TOP]]
    by_use = lambda m: [{"id": k, **v} for k, v in sorted(m.items(), key=lambda kv: (-kv[1]["played"], -kv[1]["wins"], str(kv[0])))]
    return {
        "scope": "month" if key else "all", "season": key, "season_label": seasons.label_of(key) if key else None,
        **tot, "goal_diff": tot["goals_for"] - tot["goals_against"],
        "win_pct": round(100 * tot["wins"] / tot["played"]) if tot["played"] else 0,
        "best_streak": best_streak, "current_streak": current,
        "biggest_win": {k: biggest[k] for k in ("for", "against", "opponent", "date")} if biggest else None,
        "opponents": sorted(opp.values(), key=lambda o: (-o["played"], -o["wins"], o["pseudo"].lower())),
        "top_cards": sorted(cards.values(), key=lambda c: (-c["played"], -c["wins"], (c["player"] or "").lower()))[:TOP],
        "scorers": top(scorers), "assists": top(assists),
        "formations": by_use(forms), "tactics": by_use(tacts),
    }


@router.get("/duel/my-stats")
def my_stats(scope: str = "all", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Mes stats 1v1 (seulement les miennes) : bilan, face à face, cartes, buteurs, formations. scope = all (depuis le début) ou month (saison en cours)."""
    if scope not in ("all", "month"):
        raise HTTPException(status_code=400, detail="Période inconnue (all ou month)")
    return stats_for(db, user, scope)
