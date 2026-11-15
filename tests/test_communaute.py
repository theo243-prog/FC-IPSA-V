"""
Test : cartes de la communauté (propositions des joueurs, tri par l'admin, vote du jour à 20 h, carte de rareté « communaute » donnée à
son auteur, chance réglée carte par carte, fonction en essai cachée). Lancé par tests/run_tests.py.
"""
import os

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import game_logic as GL, card_levels as CL, communaute as CO
from app.models import User, Player, Card, Tier, OwnedCard
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
H = {p: {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]} for p in ("ana", "bob", "cid", "dan")}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
at = lambda t: os.environ.__setitem__("FC_FAKE_NOW", t)
prop = lambda who, name, desc="Une photo du terrain sous la pluie": c.post("/communaute/propose", json={"name": name, "image_desc": desc}, headers=H[who])
review = lambda pid, d, **kw: c.post("/admin/communaute-review", json={"proposal_id": pid, "decision": d, **kw}, headers=A)
vote = lambda who, pid: c.post("/communaute/vote", json={"proposal_id": pid}, headers=H[who])
page = lambda who: c.get("/communaute", headers=H[who]).json()

print("1) ACCÈS (FONCTION EN ESSAI)")
ok(c.get("/communaute", headers=H["ana"]).status_code == 403 and prop("ana", "Essai").status_code == 403, "fermé par défaut : 403")
ok(c.get("/me", headers=H["ana"]).json()["features"].get("communaute") is False, "/me renvoie features.communaute à faux")
ok(c.post("/admin/feature-settings", json={"feature": "communaute", "allowed": ["ana", "bob", "cid"]}, headers=A).status_code == 200, "réservée à ana, bob et cid")
ok(c.get("/communaute", headers=H["ana"]).status_code == 200 and c.get("/communaute", headers=H["dan"]).status_code == 403, "ana y a accès, dan non")

print("2) PROPOSER")
at("2026-11-14T15:00:00")
r = prop("ana", "  Le  but de la tête ")
ok(r.status_code == 200 and r.json()["proposal"]["name"] == "Le but de la tête" and r.json()["proposal"]["status"] == "pending", "proposition enregistrée (espaces nettoyés), en attente")
p1 = r.json()["proposal"]["id"]
ok(prop("bob", "le BUT de la tête").status_code == 400, "nom déjà proposé (sans tenir compte des majuscules) : refusé")
ok(prop("bob", "Lucas").status_code == 400, "nom d'une carte existante : refusé")
ok(prop("bob", "x" * 61).status_code == 400 and prop("bob", "Ok nom", "ab").status_code == 400, "nom trop long ou image pas décrite : refusés")
ids = [prop("ana", "Proposition %d" % i).json()["proposal"]["id"] for i in range(5)]
ok(all(ids), "pas de limite par jour (5 propositions de plus)")
p2 = prop("bob", "Le vestiaire en fête").json()["proposal"]["id"]
p3 = prop("cid", "La panne de bus").json()["proposal"]["id"]
p4 = prop("cid", "Blague limite").json()["proposal"]["id"]
ok(page("bob")["candidates"] == [] and vote("bob", p1).status_code == 404, "une proposition en attente n'est pas dans le vote")

print("3) TRI PAR L'ADMIN")
ok(review(p1, "accept", name="Le but de la tête — Intel").status_code == 200, "acceptée avec un nom corrigé")
ok(review(p2, "accept").status_code == 200 and review(p3, "accept").status_code == 200, "deux autres acceptées")
ok(review(p4, "refuse", reason="trop limite").status_code == 200, "une refusée avec une raison")
ok(review(p4, "accept").status_code == 400 and review(p2, "peut-être").status_code == 400, "une refusée ne revient pas ; décision inconnue refusée")
ok(review(ids[0], "accept", name="La panne de bus").status_code == 400, "nom corrigé déjà pris : refusé")
mine = {p["id"]: p for p in page("cid")["mine"]}
ok(mine[p4]["status"] == "refused" and mine[p4]["reason"] == "trop limite", "l'auteur voit le refus et la raison")
cand = page("bob")["candidates"]
ok([x["id"] for x in cand] == [p1, p2, p3] and cand[0]["author"] == "ana" and "votes" not in cand[0], "le vote montre les acceptées (auteur visible, voix secrètes)")
adm = c.get("/admin/communaute", headers=A).json()
ok(len(adm["pending"]) == 5 and len(adm["accepted"]) == 3 and len(adm["refused"]) == 1, "l'admin voit en attente, acceptées et refusées")
ok(any("proposition %d acceptée" % p1 in x["action"] for x in c.get("/admin/log", headers=A).json()), "le tri figure dans le journal")

print("4) VOTER")
ok(vote("ana", p1).status_code == 400, "pas de voix pour sa propre proposition")
ok(vote("bob", p3).status_code == 200 and vote("bob", p1).status_code == 200, "bob vote, puis change d'avis (une voix par jour)")
ok(vote("cid", p1).status_code == 200 and vote("ana", p2).status_code == 200, "cid et ana votent")
ok(vote("dan", p1).status_code == 403, "dan (sans accès) ne vote pas")
pg = page("bob")
ok(pg["vote_day"] == "2026-11-14" and pg["my_vote"] == p1 and pg["voters"] == 3 and pg["closes_at"] == "2026-11-14T20:00:00", "vote du jour : 3 votants, ferme à 20 h, ma voix gardée")
votes_today = {x["id"]: x["votes_today"] for x in c.get("/admin/communaute", headers=A).json()["accepted"]}
ok(votes_today == {p1: 2, p2: 1, p3: 0}, "l'admin voit les voix du jour")
CO.tick(db)
ok(db.query(Card).filter_by(tier=Tier.communaute).count() == 0, "avant 20 h : rien ne sort")

print("5) RÉSULTAT À 20 H")
at("2026-11-14T20:30:00")
ok(page("bob")["vote_day"] == "2026-11-15", "après 20 h, le vote en cours est celui du lendemain")
CO.tick(db); CO.tick(db); db.expire_all()
cards = db.query(Card).filter_by(tier=Tier.communaute).all()
ok(len(cards) == 1 and cards[0].player.name == "Le but de la tête — Intel", "une seule carte sort : celle qui a le plus de voix (tâche lancée deux fois)")
card = cards[0]
ok(card.player.poste == "COMMUNAUTE" and card.player.proposed_by == "ana" and GL.card_kind(card.player) == "communaute" and card.player.photo_url is None, "fiche COMMUNAUTE, auteur ana, sans image")
own = db.query(OwnedCard).filter_by(user_id=U("ana").id, card_id=card.id).first()
ok(own is not None and own.quantity == 1, "l'auteur la reçoit d'office")
col = {x["id"]: x for x in c.get("/collection", headers=H["ana"]).json()}
ok(col[card.id]["tier"] == "communaute" and col[card.id]["proposed_by"] == "ana", "dans sa collection, avec « proposée par ana »")
pg = page("bob")
ok(pg["last_result"]["name"] == "Le but de la tête — Intel" and pg["last_result"]["votes"] == 2 and [x["id"] for x in pg["candidates"]] == [p2, p3], "résultat d'hier affiché ; les autres restent en lice")
ok(pg["released"][0]["name"] == "Le but de la tête — Intel", "historique des cartes sorties")
notes = c.get("/notifications", headers=H["ana"]).json()["items"]
ok(any("Ta carte est sortie" in n["title"] for n in notes), "l'auteur reçoit une notification")

print("6) ÉGALITÉ, JOUR SANS VOIX")
ok(vote("bob", p3).status_code == 200 and vote("ana", p2).status_code == 200, "vote du 15 : une voix chacune (égalité)")
at("2026-11-15T21:00:00"); CO.tick(db); db.expire_all()
ok(db.query(Player).filter_by(name="Le vestiaire en fête").first() is not None and db.query(Player).filter_by(name="La panne de bus").first() is None, "égalité : la plus ancienne sort")
at("2026-11-16T21:00:00"); CO.tick(db); db.expire_all()
ok(db.query(Card).filter_by(tier=Tier.communaute).count() == 2 and db.get(CO.CommunityRelease, "2026-11-16").proposal_id is None, "jour sans voix : rien ne sort, la proposition reste en stock")

print("7) CARTE DE COLLECTION")
ok(CL.ineligible_reason(card) is not None and "communauté" in CL.ineligible_reason(card), "elle n'évolue pas")
ok(GL.DUPLICATE_SELL_VALUE["communaute"] == 2 and GL.TIER_ORDER.index("communaute") == GL.TIER_ORDER.index("commune") + 1, "doublon à 2 crédits ; entre commune et rare")
from app import duel_engine as DE
try:
    DE.validate_team(db, U("ana"), "1-2-1", "pressing", [card.id] * 5); played = True
except Exception as e:
    played = False
ok(not played, "elle ne joue pas en match")

print("8) CHANCES DANS LES PACKS (CARTE PAR CARTE)")
counts = {"commune": 40, "rare": 30, "gold": 20, "epique": 10, "legendaire": 5, "communaute": 4}
base = GL.classic_tier_weights(counts, GL.TIER_WEIGHTS)
w = GL.community_tier_weights(base, counts)
per = lambda t, ww=w: ww[t] / counts[t]
ok(abs(sum(w.values()) - sum(base.values())) < 1e-9, "le total des poids ne change pas")
ok(per("rare") < per("communaute") < per("commune"), "une carte communauté tombe moins qu'une commune précise, plus qu'une rare précise")
ok(abs(w["gold"] / w["commune"] - base["gold"] / base["commune"]) < 1e-9 and abs(w["epique"] / w["rare"] - base["epique"] / base["rare"]) < 1e-9, "les autres raretés gardent leurs rapports")
w8 = GL.community_tier_weights(base, {**counts, "communaute": 8})
ok(abs(w8["communaute"] - 2 * w["communaute"]) < 1e-9, "la part grandit avec le nombre de cartes communauté")
wbig = GL.community_tier_weights(base, {**counts, "communaute": 500})
ok(abs(wbig["communaute"] - base["rare"]) < 1e-9, "plafonnée au poids de la rare")
ok(GL.community_tier_weights(base, {**counts, "communaute": 0}) == base, "sans carte communauté : poids inchangés")
real = GL.tier_card_counts(db)
ok("communaute" in GL.pack_weights(db, real, GL.TIER_WEIGHTS, "classique", U("ana")) and "communaute" not in GL.pack_weights(db, real, GL.TIER_WEIGHTS, "classique", U("dan")), "en essai : dans les packs d'ana (accès), jamais dans ceux de dan")
rules = c.get("/game/rules").json()
ok("communaute" not in rules["packs"]["classique"]["odds"] and "communaute" not in rules["counts"], "aide du site : rien sur les cartes communauté pendant l'essai")

print("9) CACHÉE PENDANT L'ESSAI")
ok(not any(x["tier"] == "communaute" for x in c.get("/collection", headers=H["dan"]).json()), "dan ne voit aucune case communauté")
ok(Tier.communaute in GL.hidden_collection_tiers(db), "pas comptée dans le % de collection pendant l'essai")
ok(c.get("/leaderboard").status_code == 200, "classement calculé")

print("10) RETIRER, SORTIE IMMÉDIATE, SUPPRESSION D'UN COMPTE")
ok(c.post("/communaute/withdraw", json={"proposal_id": p3}, headers=H["bob"]).status_code == 404, "on ne retire pas la proposition d'un autre")
ok(c.post("/communaute/withdraw", json={"proposal_id": ids[1]}, headers=H["ana"]).status_code == 200, "ana retire une proposition en attente")
ok(c.post("/communaute/withdraw", json={"proposal_id": p1}, headers=H["ana"]).status_code == 400, "une proposition sortie ne se retire pas")
ok(c.post("/admin/communaute-release", json={"proposal_id": ids[2]}, headers=A).status_code == 400, "sortie immédiate : seulement une acceptée")
r = c.post("/admin/communaute-release", json={"proposal_id": p3}, headers=A)
ok(r.status_code == 200 and r.json()["author"] == "cid" and db.query(Player).filter_by(name="La panne de bus").first() is not None, "sortie immédiate d'une acceptée, donnée à cid")
at("2026-11-17T10:00:00")
review(ids[3], "accept"); vote("cid", ids[3])
ok(c.post("/admin/delete-user", json={"pseudo": "cid"}, headers=A).status_code == 200, "compte de cid supprimé")
db.expire_all()
ok(db.query(CO.CommunityVote).filter_by(day="2026-11-17").count() == 0 and db.query(CO.CommunityProposal).filter_by(author="cid", status="released").count() == 1, "ses voix partent, la carte sortie reste")

print("10 bis) SUPPRIMER UNE CARTE DE LA COMMUNAUTÉ")
ok(c.post("/admin/delete-player", json={"player_name": "La panne de bus"}, headers=A).status_code == 200, "carte de test supprimée (Supprimer un joueur)")
db.expire_all()
ok(db.query(CO.CommunityProposal).filter_by(id=p3).first() is None, "sa proposition disparaît aussi")
ok(all(x["name"] != "La panne de bus" for x in c.get("/communaute", headers=H["ana"]).json()["released"]), "plus dans l'historique des sorties")
ok(c.post("/communaute/propose", json={"name": "La panne de bus", "image_desc": "Un bus en panne"}, headers=H["ana"]).status_code == 200, "le nom est de nouveau libre")

print("11) OUVERTURE À TOUS")
c.post("/admin/feature-settings", json={"feature": "communaute", "public": True}, headers=A)
ok(GL.community_allowed(db) and Tier.communaute not in GL.hidden_collection_tiers(db), "ouverte à tous : comptée dans la collection")
ok("communaute" in GL.pack_weights(db, GL.tier_card_counts(db), GL.TIER_WEIGHTS, "classique", U("dan")), "dans les packs de tout le monde")
ok(any(x["tier"] == "communaute" for x in c.get("/collection", headers=H["dan"]).json()), "cases visibles chez dan")
ok("communaute" in c.get("/game/rules").json()["packs"]["classique"]["odds"], "chance affichée dans l'aide du site")

os.environ.pop("FC_FAKE_NOW", None)
print(); print("BILAN (cartes de la communauté) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
