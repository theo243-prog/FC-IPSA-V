"""
Panthéon (12/11/2026, branche pantheon) : la mémoire du jeu et du club, calculée à partir de ce qui est déjà enregistré (aucune table à part).
EN ESSAI : fonction cachée aux joueurs sauf aux comptes choisis (features « pantheon »), à sortir plus tard avec une grosse mise à jour.

- Palmarès des saisons 1v1 : le podium de chaque saison terminée (season_results), la plus récente d'abord.
- Palmarès des tournois : vainqueur, finaliste et demi-finalistes de chaque tournoi terminé.
- Légendes du club (vrais joueurs) : meilleurs buteurs, passeurs, hommes du match et matchs joués (statistiques des vrais matchs),
  et la plus large victoire du club.
- Records du jeu : plus large victoire 1v1, le plus de buts d'une équipe dans un match, le plus de victoires dans une saison,
  plus longue série de victoires et sans défaite, plus gros retournement (mené de 2 buts ou plus), le plus de matchs 1v1, Elo le plus haut jamais atteint
  (à n'importe quel moment, même en cours de saison), meilleur Elo de fin de saison,
  le plus de packs ouverts, la vente la plus chère au marché, l'enchère du club la plus chère, le plus de victoires contre le club Difficile.
  Les comptes de test ne détiennent jamais un record. Un record sans donnée n'est pas montré.
- Jamais la lanterne rouge (surprise de fin de saison) ni rien de caché (secrètes non débloquées, éditions à venir).
"""
import json

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
    month = lambda d: seasons.key_of(game_logic.today_paris(d.created_at))
    de = lambda lbl: ("d'" if lbl[0] in "aeiou" else "de ") + lbl
    # le plus de buts marqués par une équipe dans un match 1v1
    top = None
    for d in duels:
        for uid, mine, theirs, oid in ((d.challenger_id, d.score_challenger, d.score_defender, d.defender_id), (d.defender_id, d.score_defender, d.score_challenger, d.challenger_id)):
            if mine > 0 and (top is None or mine > top[0]):
                top = (mine, theirs, uid, oid, d.created_at)
    if top:
        out.append(_record("goals_match", "Le plus de buts dans un match 1v1", "%d buts" % top[0], real[top[2]].pseudo, "%d-%d contre %s" % (top[0], top[1], real[top[3]].pseudo), top[4].date().isoformat()))
    # le plus de victoires dans une seule saison
    wins = {}
    for d in duels:
        if d.score_challenger != d.score_defender:
            w = d.challenger_id if d.score_challenger > d.score_defender else d.defender_id
            wins[(w, month(d))] = wins.get((w, month(d)), 0) + 1
    if wins:
        (uid, key), n = min(wins.items(), key=lambda kv: (-kv[1], kv[0][1], real[kv[0][0]].pseudo.lower()))     # égalité : la saison la plus ancienne
        out.append(_record("wins_season", "Le plus de victoires dans une saison", "%d victoires" % n, real[uid].pseudo, "saison " + de(seasons.label_of(key))))
    # la plus longue série sans défaite (victoires et nuls)
    run, best = {}, {}
    for d in duels:
        for uid, mine, theirs in ((d.challenger_id, d.score_challenger, d.score_defender), (d.defender_id, d.score_defender, d.score_challenger)):
            run[uid] = run.get(uid, 0) + 1 if mine >= theirs else 0
            if run[uid] > best.get(uid, (0, None))[0]:
                best[uid] = (run[uid], d.created_at)
    if best:
        uid, (n, when) = max(best.items(), key=lambda kv: (kv[1][0], -kv[1][1].timestamp()))
        out.append(_record("unbeaten_1v1", "Plus longue série sans défaite en 1v1", "%d matchs" % n, real[uid].pseudo, "victoires et nuls", when.date().isoformat()))
    # le plus gros retournement : gagner après avoir été mené d'au moins 2 buts (d'après le récit minute par minute)
    comeback = None
    for d in duels:
        if d.score_challenger == d.score_defender or not d.events_json:
            continue
        try:
            events = json.loads(d.events_json)
        except ValueError:
            continue
        win_c = d.score_challenger > d.score_defender
        worst, at = 0, None                                   # le plus gros retard du futur vainqueur pendant le match
        for ev in events:
            if ev.get("kind") == "goal" and ev.get("score"):
                a, b = ev["score"]
                lag = (b - a) if win_c else (a - b)
                if lag > worst:
                    worst, at = lag, (a, b)
        if worst >= 2 and (comeback is None or worst > comeback[0]):
            w, l = (d.challenger_id, d.defender_id) if win_c else (d.defender_id, d.challenger_id)
            lag_score = "%d-%d" % ((at[0], at[1]) if win_c else (at[1], at[0]))
            final = "%d-%d" % ((d.score_challenger, d.score_defender) if win_c else (d.score_defender, d.score_challenger))
            comeback = (worst, w, l, lag_score, final, d.created_at)
    if comeback:
        out.append(_record("comeback_1v1", "Le plus gros retournement en 1v1", "mené de %d buts" % comeback[0], real[comeback[1]].pseudo,
                           "mené %s, gagne %s contre %s" % (comeback[3], comeback[4], real[comeback[2]].pseudo), comeback[5].date().isoformat()))
    # Elo le plus haut jamais atteint, à n'importe quel moment d'une saison (après un match 1v1)
    peak = None
    for d in duels:
        for uid, elo in ((d.challenger_id, d.elo_challenger_after), (d.defender_id, d.elo_defender_after)):
            if elo is not None and (peak is None or elo > peak[0]):          # (égalité : le premier à l'avoir atteint garde le record)
                peak = (elo, uid, d.created_at, seasons.key_of(game_logic.today_paris(d.created_at)), True)
    best_end = db.query(seasons.SeasonResult).order_by(seasons.SeasonResult.elo.desc(), seasons.SeasonResult.season).first()
    if best_end is not None and (peak is None or best_end.elo > peak[0]) and best_end.user_id in real:   # (matchs effacés par un ménage 1v1 : l'Elo de fin de saison compte aussi)
        peak = (best_end.elo, best_end.user_id, None, best_end.season, False)
    if peak:
        lbl = seasons.label_of(peak[3]); de = "d'" if lbl[0] in "aeiou" else "de "
        out.append(_record("peak_elo", "Elo le plus haut jamais atteint", "%d" % peak[0], real[peak[1]].pseudo,
                           ("en cours de saison " if peak[4] else "à la fin de la saison ") + de + lbl, peak[2].date().isoformat() if peak[2] else None))
    # meilleur Elo de fin de saison
    sr = db.query(seasons.SeasonResult).order_by(seasons.SeasonResult.elo.desc(), seasons.SeasonResult.season).first()
    if sr:
        out.append(_record("season_elo", "Meilleur Elo de fin de saison", "%d" % sr.elo, sr.pseudo, ("saison d'" if seasons.label_of(sr.season)[0] in "aeiouo" else "saison de ") + seasons.label_of(sr.season)))
    # le plus de saisons sur le podium, le plus de titres de champion
    res = [r for r in db.query(seasons.SeasonResult).all() if r.user_id in real]
    for rid, label, rows, unit in (("podiums", "Le plus de saisons sur le podium", res, "podium"), ("titles", "Le plus de titres de champion de saison", [r for r in res if r.rank == 1], "titre")):
        cnt = {}
        for r in rows:
            cnt[r.user_id] = cnt.get(r.user_id, 0) + 1
        if cnt:
            uid, n = min(cnt.items(), key=lambda kv: (-kv[1], real[kv[0]].pseudo.lower()))
            out.append(_record(rid, label, "%d %s%s" % (n, unit, "s" if n > 1 else ""), real[uid].pseudo))
    # la plus grosse collection et la meilleure complétion du jeu (mêmes calculs que le classement)
    from .models import OwnedCard, Tier
    total = db.query(Card).filter(Card.tier.notin_([Tier.saison, Tier.numerotee])).count()
    if total:
        owned = dict(db.query(OwnedCard.user_id, func.count(OwnedCard.card_id)).join(Card, Card.id == OwnedCard.card_id)
                     .filter(OwnedCard.quantity > 0, Card.tier.notin_([Tier.saison, Tier.numerotee])).group_by(OwnedCard.user_id).all())
        owned = {u: n for u, n in owned.items() if u in real and n > 0}
        if owned:
            uid, n = min(owned.items(), key=lambda kv: (-kv[1], real[kv[0]].pseudo.lower()))
            out.append(_record("collection", "La plus grosse collection", "%s %%" % ("%.1f" % (100 * n / total)).replace(".", ","), real[uid].pseudo, "%d cartes sur %d" % (n, total)))
        from . import card_levels
        comp = {u: v for u, v in card_levels.game_completion(db, list(owned)).items() if v > 0}
        if comp:
            uid, v = min(comp.items(), key=lambda kv: (-kv[1], real[kv[0]].pseudo.lower()))
            out.append(_record("completion", "La meilleure complétion du jeu", "%s %%" % ("%.1f" % v).replace(".", ","), real[uid].pseudo, "cartes et niveaux"))
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
