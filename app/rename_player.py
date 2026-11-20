"""
Renommer une personne du club (branche renommer-joueur, 20/11/2026) : POST /admin/rename-player {old_name, new_name}, formulaire
« Renommer un joueur » de l'onglet Cartes de l'administration.

- Toutes ses cartes (commune, rare, épique, légendaire, secrète, spéciale…) sont rattachées à SA fiche (Player) : changer le nom de la fiche
  les renomme toutes. Photo, notes, niveaux, forme, propriétaires : rien ne bouge (tout est lié par identifiant).
- Le nom est aussi recopié en TEXTE ailleurs ; tout est changé dans la même transaction (tout ou rien) :
  * ses cartes gold (fiches MOMENT « Action — Nom », « Action — Nom (12/10) », « …+ ») et match_moments.real_player_name ;
  * les séries numérotées dont il est le sujet (Édition Noire…) : le sujet et les fiches de chaque exemplaire (« Titre — Nom · n° 3/5 ») ;
  * card_usage.player_name (cartes les plus utilisées : tournoi et défi du club) ;
  * les compositions et récits enregistrés des matchs 1v1, de tournoi et du défi du club (clés « player », « scorer », « assist ») :
    ils servent aux cartes spéciales du vendredi, aux stats 1v1 et au Panthéon ;
  * les matchs réels (présents, cartons, épiques créées) ;
  * l'homme du match (présents, bulletins, points, résultat, saison des votes figée).
- Seules les valeurs EXACTEMENT égales à l'ancien nom sont changées (jamais un pseudo de compte, jamais une phrase) : les phrases des récits
  déjà joués (« But de X ! ») et des messages du chat restent telles quelles (historique).
- Refus : ancien nom introuvable, nom vide ou identique, nouveau nom déjà pris par une fiche (sans tenir compte des majuscules, sauf la fiche
  elle-même : on peut corriger une majuscule), ou fiche réservée (moment, exemplaire numéroté, trophée, écusson, carte de la communauté).
  Pas d'annonce ni de notification.
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .common import require_admin
from .models import Player, Card, Match, MatchMoment, Duel, CardUsage

router = APIRouter()
NAME_KEYS = {"player", "scorer", "assist", "created", "player_name"}     # clés JSON qui contiennent un nom de personne du club
RESERVED_POSTES = {"MOMENT", "NUMEROTEE", "TROPHEE", "ECUSSON", "COMMUNAUTE"}   # fiches qui ne sont pas « une personne »


class RenameRequest(BaseModel):
    old_name: str
    new_name: str


def _swap(value, old: str, new: str, list_items: bool):
    """Remplace dans un JSON décodé les valeurs égales à `old` sous NAME_KEYS (et, si list_items, les éléments texte des listes). Renvoie (valeur, nb)."""
    if isinstance(value, dict):
        n, out = 0, {}
        for k, v in value.items():
            if k in NAME_KEYS and v == old:
                out[k], n = new, n + 1
            else:
                out[k], m = _swap(v, old, new, list_items)
                n += m
        return out, n
    if isinstance(value, list):
        n, out = 0, []
        for v in value:
            if list_items and v == old:
                out.append(new); n += 1
            else:
                v2, m = _swap(v, old, new, list_items)
                out.append(v2); n += m
        return out, n
    return value, 0


def _rewrite(rows, attrs, old, new, list_items=False) -> int:
    """Réécrit les colonnes JSON `attrs` de chaque ligne ; renvoie le nombre de lignes changées."""
    changed = 0
    for row in rows:
        touched = False
        for a in attrs:
            raw = getattr(row, a, None)
            # filtre rapide (la plupart des lignes ne le mentionnent pas) ; le nom peut être écrit tel quel ou échappé (é…)
            if not raw or (old not in raw and json.dumps(old)[1:-1] not in raw):
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            data, n = _swap(data, old, new, list_items)
            if n:
                setattr(row, a, json.dumps(data, ensure_ascii=False))
                touched = True
        changed += touched
    return changed


def rename(db: Session, old_name: str, new_name: str) -> dict:
    """Renomme la fiche `old_name` en `new_name` partout (sans commit). Lève HTTPException en cas de refus."""
    old_name, new = " ".join((old_name or "").split()), " ".join((new_name or "").split())
    if not old_name or not new:
        raise HTTPException(status_code=400, detail="Indique l'ancien et le nouveau nom")
    if len(new) > 60:
        raise HTTPException(status_code=400, detail="Le nouveau nom fait plus de 60 caractères")
    if "—" in new or "·" in new:
        raise HTTPException(status_code=400, detail="Le nouveau nom ne peut pas contenir « — » ni « · » (réservés aux cartes gold et numérotées)")
    person = db.query(Player).filter_by(name=old_name).first()
    if person is None:
        raise HTTPException(status_code=404, detail="Joueur introuvable : %s (nom exact)" % old_name)
    if (person.poste or "").upper() in RESERVED_POSTES:
        raise HTTPException(status_code=400, detail="« %s » n'est pas une personne du club (carte gold, numérotée, trophée, écusson ou communauté) : impossible de la renommer ici" % old_name)
    old = person.name
    if new == old:
        raise HTTPException(status_code=400, detail="Le nouveau nom est identique à l'ancien")
    taken = {n.casefold(): pid for pid, n in db.query(Player.id, Player.name).all()}
    if taken.get(new.casefold(), person.id) != person.id:
        raise HTTPException(status_code=400, detail="« %s » est déjà pris par une autre carte" % new)

    report = {"old_name": old, "new_name": new, "cards": db.query(Card).filter_by(player_id=person.id).count()}

    # 1) cartes gold (moments) : « Action — Ancien », éventuellement « (12/10) » et des « + »
    pat = re.compile(r"^(.*) — " + re.escape(old) + r"((?: \(\d\d/\d\d\))?\+*)$")
    moments, new_names = [], {}
    for p in db.query(Player).filter(Player.poste == "MOMENT", Player.name.like("% — " + old + "%")).all():
        m = pat.match(p.name)
        if m:
            moments.append(p); new_names[p.id] = "%s — %s%s" % (m.group(1), new, m.group(2))
    # 2) séries numérotées dont il est le sujet (Édition Noire…) : sujet + fiche de chaque exemplaire
    from . import numbered
    series = db.query(numbered.NumberedSeries).filter_by(subject=old).all()
    copies = []
    for s in series:
        for c in db.query(numbered.NumberedCopy).filter_by(series_id=s.id).all():
            card = db.get(Card, c.card_id)
            if card is not None:
                copies.append(card.player); new_names[card.player.id] = numbered.copy_name(s.title, new, c.number, s.total)
    for pid, nm in new_names.items():                       # aucun nom dérivé ne doit tomber sur une autre fiche
        if taken.get(nm.casefold(), pid) != pid:
            raise HTTPException(status_code=400, detail="Renommage impossible : « %s » existe déjà" % nm)

    person.name = new
    for p in moments + copies:
        p.name = new_names[p.id]
    for s in series:
        s.subject = new
    report["gold_cards"], report["numbered_series"], report["numbered_copies"] = len(moments), len(series), len(copies)
    report["match_moments"] = db.query(MatchMoment).filter_by(real_player_name=old).update({"real_player_name": new}, synchronize_session=False)
    report["card_usage"] = db.query(CardUsage).filter_by(player_name=old).update({"player_name": new}, synchronize_session=False)

    # 3) compositions et récits enregistrés (1v1, tournoi, défi du club)
    from . import tournament, club, motm
    report["duels"] = _rewrite(db.query(Duel).all(), ("lineups_json", "events_json"), old, new)
    report["tournament_matches"] = _rewrite(db.query(tournament.TournamentMatch).all(), ("lineups_json", "events_json"), old, new)
    report["club_matches"] = _rewrite(db.query(club.ClubMatch).all(), ("lineups_json", "events_json"), old, new)
    # 4) matchs réels : listes de noms (présents, cartons, épiques créées)
    report["matches"] = _rewrite(db.query(Match).all(), ("lineup_json", "yellow_json", "red_json", "epics_json"), old, new, list_items=True)
    # 5) homme du match
    report["motm_votes"] = _rewrite(db.query(motm.MotmVote).all(), ("players_json", "result_json"), old, new, list_items=True)
    n = 0
    for col in ("first", "second", "third"):
        n += db.query(motm.MotmBallot).filter(getattr(motm.MotmBallot, col) == old).update({col: new}, synchronize_session=False)
    report["motm_ballots"] = n
    report["motm_points"] = db.query(motm.MotmPoint).filter_by(player_name=old).update({"player_name": new}, synchronize_session=False)
    report["motm_seasons"] = _rewrite(db.query(motm.MotmSeason).all(), ("frozen_json",), old, new)
    return report


@router.post("/admin/rename-player", dependencies=[Depends(require_admin)])
def admin_rename_player(payload: RenameRequest, db: Session = Depends(get_db)):
    report = rename(db, payload.old_name, payload.new_name)
    db.commit()
    return {"status": "ok", **report}
