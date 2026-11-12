"""
Panthéon (12/11/2026, branche pantheon) : la mémoire du jeu et du club, calculée à partir de ce qui est déjà enregistré (aucune table à part).
EN ESSAI : fonction cachée aux joueurs sauf aux comptes choisis (features « pantheon »), à sortir plus tard avec une grosse mise à jour.

- Palmarès des saisons 1v1 : le podium de chaque saison terminée (season_results), la plus récente d'abord.
- Palmarès des tournois : vainqueur, finaliste et demi-finalistes de chaque tournoi terminé.
- Légendes du club (vrais joueurs) : meilleurs buteurs, passeurs, hommes du match et matchs joués (statistiques des vrais matchs),
  et la plus large victoire du club.
- Records du jeu : plus large victoire 1v1, plus longue série de victoires 1v1, le plus de matchs 1v1, meilleur Elo de fin de saison,
  le plus de packs ouverts, la vente la plus chère au marché, l'enchère du club la plus chère, le plus de victoires contre le club Difficile.
  Les comptes de test ne détiennent jamais un record. Un record sans donnée n'est pas montré.
- Jamais la lanterne rouge (surprise de fin de saison) ni rien de caché (secrètes non débloquées, éditions à venir).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from .models import Card, Duel, Match, Player, User
from .security import get_current_user
from . import features, game_logic, seasons

router = APIRouter()
TOP = 5


def _real_users(db: Session) -> dict:
    return {u.id: u for u in db.query(User).filter(User.is_test == False).all()}       # noqa: E712


def season_podiums(db: Session) -> list:
    rows = db.query(seasons.SeasonResult).order_by(seasons.SeasonResult.season.desc(), seasons.SeasonResult.rank).all()
    out, by = [], {}
    for r in rows:
        if r.season not in by:
            by[r.season] = {"season": r.season, "label": seasons.label_of(r.season), "podium": []}
            out.append(by[r.season])
        by[r.season]["podium"].append({"rank": r.rank, "pseudo": r.pseudo, "elo": r.elo, "matches": r.matches, "wins": r.wins})
    return out


def tournament_winners(db: Session) -> list:
    from .tournament import Tournament, TournamentEntry
    users = {u.id: u.pseudo for u in db.query(User).all()}
    out = []
    for t in db.query(Tournament).filter(Tournament.status == "finished").order_by(Tournament.month_key.desc()).all():
        entries = db.query(TournamentEntry).filter_by(tournament_id=t.id).all()
        nm = lambda p: [users[e.user_id] for e in entries if e.place == p and e.user_id in users]
        out.append({"month": t.month_key, "label": seasons.label_of(t.month_key), "players": len(entries),
                    "champion": (nm(1) or [None])[0], "finalist": (nm(2) or [None])[0], "semifinalists": nm(3)})
    return out


def club_legends(db: Session) -> dict:
    people = [p for p in db.query(Player).all() if game_logic.card_kind(p) == "joueur"]
    top = lambda attr: [{"player": p.name, "count": getattr(p, attr)} for p in sorted(people, key=lambda p: (-getattr(p, attr), p.name.lower())) if getattr(p, attr) > 0][:TOP]
    best = None
    for m in db.query(Match).all():
        diff = m.score_us - m.score_them
        if diff > 0 and (best is None or (diff, m.score_us) > (best.score_us - best.score_them, best.score_us)):
            best = m
    return {"scorers": top("buts"), "assists": top("passes_decisives"), "motm": top("homme_du_match_count"), "matches": top("matches_joues"),
            "biggest_win": {"opponent": best.opponent, "score_us": best.score_us, "score_them": best.score_them, "date": best.date.date().isoformat()} if best else None}


def _record(rid, label, value, holder, detail=None, date=None):
    return {"id": rid, "label": label, "value": value, "holder": holder, "detail": detail, "date": date}


def game_records(db: Session) -> list:
    real = _real_users(db)
    out = []
    duels = [d for d in db.query(Duel).order_by(Duel.created_at, Duel.id).all() if d.challenger_id in real and d.defender_id in real]
    # plus large victoire 1v1
    big = None
    for d in duels:
        diff = abs(d.score_challenger - d.score_defender)
        if diff and (big is None or (diff, max(d.score_challenger, d.score_defender)) > big[0]):
            big = ((diff, max(d.score_challenger, d.score_defender)), d)
    if big:
        d = big[1]; win_c = d.score_challenger > d.score_defender
        w, l = (real[d.challenger_id], real[d.defender_id]) if win_c else (real[d.defender_id], real[d.challenger_id])
        sw, sl = (d.score_challenger, d.score_defender) if win_c else (d.score_defender, d.score_challenger)
        out.append(_record("biggest_1v1", "Plus large victoire en 1v1", "%d-%d" % (sw, sl), w.pseudo, "contre " + l.pseudo, d.created_at.date().isoformat()))
    # plus longue série de victoires et plus de matchs
    run, best_run, played = {}, {}, {}
    for d in duels:
        for uid, mine, theirs in ((d.challenger_id, d.score_challenger, d.score_defender), (d.defender_id, d.score_defender, d.score_challenger)):
            played[uid] = played.get(uid, 0) + 1
            run[uid] = run.get(uid, 0) + 1 if mine > theirs else 0
            if run[uid] > best_run.get(uid, (0, None))[0]:
                best_run[uid] = (run[uid], d.created_at)
    if best_run:
        uid, (n, when) = max(best_run.items(), key=lambda kv: (kv[1][0], -kv[1][1].timestamp()))
        out.append(_record("streak_1v1", "Plus longue série de victoires en 1v1", "%d victoires" % n, real[uid].pseudo, None, when.date().isoformat()))
    if played:
        uid, n = min(played.items(), key=lambda kv: (-kv[1], real[kv[0]].pseudo.lower()))      # égalité : ordre alphabétique
        out.append(_record("matches_1v1", "Le plus de matchs 1v1 joués", "%d matchs" % n, real[uid].pseudo))
    # meilleur Elo de fin de saison
    sr = db.query(seasons.SeasonResult).order_by(seasons.SeasonResult.elo.desc(), seasons.SeasonResult.season).first()
    if sr:
        out.append(_record("season_elo", "Meilleur Elo de fin de saison", "%d" % sr.elo, sr.pseudo, ("saison d'" if seasons.label_of(sr.season)[0] in "aeiouo" else "saison de ") + seasons.label_of(sr.season)))
    # le plus de packs ouverts
    from .profiles import UserCounter
    rows = [r for r in db.query(UserCounter).filter_by(key="open_packs").all() if r.user_id in real and r.value > 0]
    if rows:
        r = min(rows, key=lambda r: (-r.value, real[r.user_id].pseudo.lower()))
        out.append(_record("packs", "Le plus de packs ouverts", "%d packs" % r.value, real[r.user_id].pseudo))
    # la vente la plus chère au marché (annonces, offres d'achat, enchères des joueurs)
    from .offers import Trade
    t = db.query(Trade).order_by(Trade.price.desc(), Trade.created_at).first()
    if t is not None and t.price > 0:
        card = db.get(Card, t.card_id)
        out.append(_record("top_sale", "Vente la plus chère au marché", "%d crédits" % t.price, t.buyer_pseudo,
                           ("%s (%s), vendue par %s" % (card.player.name, t.card_tier, t.seller_pseudo)) if card else "vendue par " + t.seller_pseudo, t.created_at.date().isoformat()))
    # l'enchère du club la plus chère
    from .club_auctions import ClubAuctionLot
    lot = db.query(ClubAuctionLot).filter_by(status="won").order_by(ClubAuctionLot.price.desc()).first()
    if lot is not None and lot.price:
        card = db.get(Card, lot.card_id)
        out.append(_record("top_club_auction", "Enchère du club la plus chère", "%d crédits" % lot.price, lot.winner_pseudo, card.player.name if card else None))
    # le plus de victoires contre le club Difficile
    from . import club
    rk = [r for r in club.ranking(db, limit=50) if r["difficile"] > 0]
    if rk:
        out.append(_record("club_hard", "Le plus de victoires contre le club Difficile", "%d victoires" % rk[0]["difficile"], rk[0]["pseudo"]))
    return out


def build(db: Session) -> dict:
    return {"seasons": season_podiums(db), "tournaments": tournament_winners(db), "club": club_legends(db), "records": game_records(db)}


@router.get("/pantheon")
def get_pantheon(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Le Panthéon : palmarès des saisons et des tournois, légendes du club, records du jeu (fonction en essai : comptes choisis seulement)."""
    features.require(db, user, "pantheon", "Le Panthéon n'est pas encore ouvert")
    return build(db)
