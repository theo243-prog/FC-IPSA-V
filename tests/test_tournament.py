"""
Test : tournoi 1v1 mensuel (inscriptions, tirage, exemptés, tours de 24 h, forfaits, tirs au but, cagnotte, trophée, annulations).
L'horloge est simulée. Lancer comme test_social2.py (voir tests/LISEZMOI.md) :
    rm -f /tmp/fc_test.db && export ADMIN_KEY=k DATABASE_URL=sqlite:////tmp/fc_test.db PYTHONPATH=. && python -m app.seed_data && python tests/test_tournament.py
"""
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import tournament as TN, duel_engine as DE
from app.models import User, Card, Player, OwnedCard, Tier, Duel
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 20, 10, 0)]; TN.now_paris = lambda: NOW[0]
def at(y, mo, d, h=0, mi=0): NOW[0] = datetime(y, mo, d, h, mi)
db = SessionLocal(); real_poisson = DE.poisson_random
card = lambda n, t: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
CORE = [("Lucas", "GB"), ("Hugo", "DEF"), ("Nathan", "MC"), ("Léo", "MC"), ("Enzo", "ATT")]
def mk(p, elo, credits=100):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.elo, u.credits = elo, credits
    for n, _ in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n, "commune").id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
cr = lambda p: U(p).credits
def team(p, tactic="pressing", formation="1-2-1"):
    u = U(p); cat = {"1-2-1": ["GB", "DEF", "MC", "MC", "ATT"]}[formation]; cards = [card(n, "commune") for n, _ in CORE]
    return {"formation": formation, "tactic": tactic, "slots": [{"card_id": cd.id, "slot_category": ct} for cd, ct in zip(cards, cat)]}
def info(H): return c.get("/tournament", headers=H).json()
def chat_events(H): return [m["text"] for m in c.get("/chat", params={"limit": 200}, headers=H).json()["messages"] if m["kind"] == "event"]
ELO = {"t1": 1500, "t2": 1400, "t3": 1300, "t4": 1200, "t5": 1100, "t6": 1000}
H = {p: mk(p, e) for p, e in ELO.items()}; H["t7"] = mk("t7", 900); H["pauvre"] = mk("pauvre", 800, credits=5)
elo0 = {p: U(p).elo for p in H}; duels0 = db.query(Duel).count()

print("1) HORS DES JOURS D'INSCRIPTION")
at(2026, 11, 20, 10); g = info(H["t1"]); ok(g["phase"] == "none" and g["next"]["label"] == "décembre 2026" and g["me"]["joined"] is False, "le 20 : pas de tournoi ce mois-ci, prochain « décembre 2026 »")
ok(c.post("/tournament/join", headers=H["t1"]).status_code == 400, "s'inscrire hors du 1er au 7 : refusé (400)")

print("2) INSCRIPTIONS (novembre 2026)")
at(2026, 11, 2, 9); g = info(H["t1"]); ok(g["phase"] == "registration" and g["entry_fee"] == 20 and g["entries"] == 0 and g["registration_ends"].startswith("2026-11-08T00:00"), "le 2 : inscriptions ouvertes, droit d'entrée 20 crédits, fermeture le 8 à minuit")
for p in ("t1", "t2", "t3", "t4", "t5", "t6"): r = c.post("/tournament/join", headers=H[p])
ok(r.status_code == 200 and cr("t1") == 80 and r.json()["entries"] == 6 and r.json()["pool"] == 120, "6 joueurs s'inscrivent : 100 → 80 crédits chacun, cagnotte 120")
ok(c.post("/tournament/join", headers=H["t1"]).status_code == 400 and c.post("/tournament/join", headers=H["pauvre"]).status_code == 400, "refusés : déjà inscrit ; pas assez de crédits (5)")
ok(c.post("/tournament/join").status_code == 401, "sans compte : 401")
ok(c.delete("/tournament/join", headers=H["t6"]).status_code == 200 and cr("t6") == 100 and c.delete("/tournament/join", headers=H["t6"]).status_code == 404, "se désinscrire rend les 20 crédits (et recommencer : 404)")
c.post("/tournament/join", headers=H["t6"])
ok(c.post("/admin/tournament-settings", json={"entry_fee": 30, "bonus": 60}).status_code == 403 and c.post("/admin/tournament-settings", json={"entry_fee": 600}, headers=A).status_code == 422, "réglages : 403 sans clé ; droit d'entrée absurde (600) : 422")
c.post("/admin/tournament-settings", json={"entry_fee": 30, "bonus": 60}, headers=A)
r = c.post("/tournament/join", headers=H["t7"]); ok(r.status_code == 200 and cr("t7") == 70 and r.json()["pool"] == 120 + 30 + 60, "droit d'entrée porté à 30 : le suivant paie 30 ; bonus du club de 60 : cagnotte 210")
c.delete("/tournament/join", headers=H["t7"]); g = info(H["t1"]); ok(g["pool"] == 180 and g["bonus"] == 60 and g["entries"] == 6 and cr("t7") == 100, "il se désinscrit (30 rendus) : cagnotte 180 (6 × 20 + 60), 6 inscrits")
pz = {p["place"]: p["amount"] for p in g["prizes"]}; ok(pz == {1: 91, 2: 45, 3: 22}, f"gains prévus : vainqueur {pz[1]}, finaliste {pz[2]}, chaque demi-finaliste {pz[3]} (50 / 25 / 12,5 %)")
ok([p["pseudo"] for p in g["players"]][:2] == ["t1", "t2"], "la liste des inscrits est classée par Elo")
ok(c.get("/admin/tournament", headers=A).json()["tournament"]["entries"] == 6 and c.get("/admin/tournament").status_code == 403, "l'administrateur voit l'état du tournoi (403 sans clé)")

print("3) LE TIRAGE (le 8 à minuit)")
at(2026, 11, 7, 23, 59); ok(info(H["t1"])["phase"] == "registration", "le 7 à 23h59 : encore en inscription")
at(2026, 11, 8, 0, 30); g = info(H["t1"]); r1 = g["rounds"][0]["matches"]
ok(g["phase"] == "running" and g["rounds_total"] == 3 and g["size"] == 8 and [r["name"] for r in g["rounds"]] == ["Quarts de finale", "Demi-finales", "Finale"], "6 inscrits : tableau de 8, trois tours : quarts, demi-finales, finale")
seeds = [(m["p1"] and m["p1"]["seed"], m["p2"] and m["p2"]["seed"]) for m in r1]
ok(seeds == [(1, None), (4, 5), (2, None), (3, 6)], f"têtes de série par Elo, 1 et 2 n'ont pas d'adversaire (tableau : {seeds})")
ok(r1[0]["state"] == "done" and r1[0]["via"] == "bye" and r1[0]["winner"] == "t1" and r1[2]["winner"] == "t2", "les deux mieux classés passent le 1er tour directement (exemptés)")
r2 = g["rounds"][1]["matches"]; ok(r2[0]["p1"]["pseudo"] == "t1" and r2[0]["p1"]["seed"] == 1 and r2[1]["p1"]["pseudo"] == "t2", "ils sont déjà placés en demi-finale")
ok(g["rounds"][0]["opens_at"].startswith("2026-11-08T12:00") and g["rounds"][0]["deadline_at"].startswith("2026-11-09T12:00") and g["rounds"][1]["deadline_at"].startswith("2026-11-10T12:00") and g["rounds"][2]["deadline_at"].startswith("2026-11-11T12:00"), "tours de 24 h, de midi à midi : finale terminée au plus tard le 11 à midi")
ok(any("Le tournoi de novembre 2026 est lancé : 6 joueurs, cagnotte de 180 crédits" in t for t in chat_events(H["t1"])), "le lancement est annoncé dans le chat")
ok(c.post("/tournament/join", headers=H["t7"]).status_code == 400 and c.delete("/tournament/join", headers=H["t3"]).status_code == 400, "après le tirage : plus d'inscription ni de désinscription")

print("4) PREMIER TOUR")
m45 = r1[1]["id"]; m36 = r1[3]["id"]; g = info(H["t4"]); mm = g["me"]["match"]
ok(mm["id"] == m45 and mm["state"] == "soon" and mm["round_name"] == "Quarts de finale", "t4 voit son match (contre t5), pas encore ouvert avant midi")
at(2026, 11, 8, 9); r = c.post(f"/tournament/matches/{m45}/team", json=team("t4"), headers=H["t4"]); ok(r.status_code == 400 and "s'ouvre le 08/11" in r.json()["detail"], "composer son équipe avant l'ouverture : refusé « " + r.json()["detail"] + " »")
at(2026, 11, 8, 13); info(H["t1"]); ok(any("Quarts de finale du tournoi : 2 matchs ouverts" in t for t in chat_events(H["t1"])), "à midi le tour est annoncé : 2 matchs à jouer (les exemptés n'en ont pas)")
ok(c.post(f"/tournament/matches/{m45}/team", json=team("t4"), headers=H["t3"]).status_code == 404 and c.post(f"/tournament/matches/{m45}/team", json=team("t4")).status_code == 401, "un autre joueur ne peut pas composer l'équipe de t4 (404) ; sans compte : 401")
bad = team("t4"); bad["slots"][0]["card_id"] = card("Tom", "commune").id; r = c.post(f"/tournament/matches/{m45}/team", json=bad, headers=H["t4"]); ok(r.status_code == 400 and "possèdes pas" in r.json()["detail"], "une carte qu'on n'a pas : refusé « " + r.json()["detail"] + " »")
r = c.post(f"/tournament/matches/{m45}/team", json=team("t4"), headers=H["t4"]); ok(r.status_code == 200 and r.json()["resolved"] is False, "t4 valide son équipe : le match attend t5")
g = info(H["t5"]); ok(g["me"]["match"]["submitted"] == [True, False] and g["me"]["match"]["my_team_ready"] is False and g["me"]["match"]["state"] == "open", "t5 sait que t4 est prêt (sans voir son équipe)")
DE.poisson_random = lambda lam: 1                                       # on force une égalité : tirs au but
r = c.post(f"/tournament/matches/{m45}/team", json=team("t5", "contre"), headers=H["t5"]); DE.poisson_random = real_poisson; res = r.json()
ok(r.status_code == 200 and res["resolved"] and res["recap"]["score_challenger"] == 1 and res["recap"]["score_defender"] == 1 and res["pens"] and res["pens"][0] != res["pens"][1], f"dès que les 2 ont validé, le match se joue : 1–1, départagé aux tirs au but {res['pens'][0]}–{res['pens'][1]}")
rc = res["recap"]; ok(rc["tournament"]["round_name"] == "Quarts de finale" and rc["tournament"]["pens"] == res["pens"] and rc["events"] and rc["lineups"]["challenger"]["pseudo"] == "t4" and rc["duel_id"] is None, "le récit complet est disponible (événements, compositions) et marqué « tournoi »")
winner45 = rc["tournament"]["winner"]; ok(winner45 == ("t4" if res["pens"][0] > res["pens"][1] else "t5"), f"le vainqueur aux tirs au but est {winner45}")
ok(c.get(f"/tournament/matches/{m45}/recap").status_code == 200 and c.get(f"/tournament/matches/{m36}/recap").status_code == 404, "le récit est public ; un match pas joué n'en a pas (404)")
ok({p: U(p).elo for p in H} == elo0 and db.query(Duel).count() == duels0, "AUCUN effet sur l'Elo ni sur l'historique des matchs 1v1")
ok(cr("t4") == 80 and cr("t5") == 80, "ni crédits ni packs gagnés ou perdus (les droits d'entrée sont la mise)")
c.post(f"/tournament/matches/{m36}/team", json=team("t3"), headers=H["t3"])
at(2026, 11, 9, 12, 1); g = info(H["t1"]); m36o = g["rounds"][0]["matches"][3]
ok(m36o["state"] == "done" and m36o["via"] == "forfeit" and m36o["winner"] == "t3" and m36o["score"] is None, "t6 n'a pas composé son équipe à l'heure limite : forfait, t3 est qualifié")
r2 = g["rounds"][1]["matches"]; ok(r2[0]["p2"]["pseudo"] == winner45 and r2[1]["p2"]["pseudo"] == "t3", f"le tableau avance tout seul : demi-finales t1 – {winner45} et t2 – t3")
ok(any("Demi-finales du tournoi : 2 matchs ouverts" in t for t in chat_events(H["t1"])), "les demi-finales sont annoncées dans le chat")
lw = info(H[winner45])["me"]; ok(lw["match"]["round_name"] == "Demi-finales" and lw["last"]["round_name"] == "Quarts de finale" and lw["last"]["winner"] == winner45 and lw["last"]["replay"] is True, f"{winner45} voit sa demi-finale ET son dernier match (quarts, avec récit) ; t3 son dernier match par forfait : {info(H['t3'])['me']['last']['via']}")

print("5) DEMI-FINALES")
m_a, m_b = r2[0]["id"], r2[1]["id"]; at(2026, 11, 9, 15)
c.post(f"/tournament/matches/{m_b}/team", json=team("t2"), headers=H["t2"]); res = c.post(f"/tournament/matches/{m_b}/team", json=team("t3", "possession"), headers=H["t3"]).json()
ok(res["resolved"] and res["winner"] in ("t2", "t3"), f"t2 – t3 se joue : {res['recap']['score_challenger']}–{res['recap']['score_defender']}" + (f" (tirs au but {res['pens'][0]}–{res['pens'][1]})" if res["pens"] else "") + f", {res['winner']} gagne")
winner_b = res["winner"]; loser_b = "t3" if winner_b == "t2" else "t2"
at(2026, 11, 10, 12, 1); g = info(H["t1"]); ma = g["rounds"][1]["matches"][0]
ok(ma["via"] == "double_forfeit" and ma["winner"] == "t1", "t1 et son adversaire n'ont rien composé : le mieux classé (t1) passe")
fm = g["rounds"][2]["matches"][0]; ok({fm["p1"]["pseudo"], fm["p2"]["pseudo"]} == {"t1", winner_b} and fm["state"] == "open", f"finale : t1 contre {winner_b}, ouverte")
loser_a = winner45 if winner45 != "t1" else "t5"; loser_a = [p for p in (db.query(User).filter_by(pseudo=winner45).first().pseudo,) if p][0]

print("6) LA FINALE ET LA CAGNOTTE")
before = {p: cr(p) for p in ("t1", "t2", "t3", "t4", "t5", "t6")}; at(2026, 11, 10, 14)
c.post(f"/tournament/matches/{fm['id']}/team", json=team("t1"), headers=H["t1"]); res = c.post(f"/tournament/matches/{fm['id']}/team", json=team(winner_b, "contre"), headers=H[winner_b]).json()
champ = res["winner"]; fin = "t1" if champ == winner_b else winner_b
ok(res["resolved"] and champ in ("t1", winner_b), f"la finale t1 – {winner_b} se joue : {champ} gagne")
g = info(H["t1"]); ok(g["phase"] == "finished" and g["champion"] == champ, "le tournoi est terminé : champion « " + champ + " »")
semis_losers = sorted(["t4" if winner45 == "t5" else "t5" if winner45 == "t4" else None, loser_b] if False else [winner_a for winner_a in ()])
delta = {p: cr(p) - before[p] for p in before}
ok(delta[champ] == 91 and delta[fin] == 45 and sorted(v for v in delta.values() if v) == [22, 22, 45, 91], f"cagnotte de 180 versée : vainqueur +{delta[champ]}, finaliste +{delta[fin]}, les deux demi-finalistes battus +22 chacun : {delta}")
ok(sum(delta.values()) == 180, "les 180 crédits sont intégralement redistribués (6 × 20 + 60 de bonus)")
ent = {p: db.query(TN.TournamentEntry).filter_by(user_id=U(p).id).first().place for p in before}; ok(sorted(v for v in ent.values() if v) == [1, 2, 3, 3] and ent[champ] == 1 and ent[fin] == 2, f"places : {ent}")
col = {x["id"]: x for x in c.get("/collection", headers=H[champ]).json()}; troph = [x for x in col.values() if x.get("trophy") and x["trophy"]["rank"] == 4 and x["quantity"] == 1]
ok(len(troph) == 1 and troph[0]["trophy"]["title"] == "Vainqueur du tournoi" and troph[0]["trophy"]["label"] == "novembre 2026", "le vainqueur reçoit le trophée « Vainqueur du tournoi (novembre 2026) »")
colf = c.get("/collection", headers=H[fin]).json(); tf = [x for x in colf if x.get("trophy") and x["trophy"]["rank"] == 5 and x["quantity"] == 1]
ok(len(tf) == 1 and tf[0]["trophy"]["title"] == "Finaliste du tournoi" and tf[0]["trophy"]["label"] == "novembre 2026" and tf[0]["tier"] == "saison" and not any(x.get("trophy") and x["trophy"]["rank"] == 4 and x["quantity"] > 0 for x in colf), "le finaliste reçoit la carte « Finaliste du tournoi (novembre 2026) » (et pas celle du vainqueur)")
ok(not any(x.get("trophy") and x["trophy"]["rank"] == 5 and x["quantity"] > 0 for x in c.get("/collection", headers=H[champ]).json()), "le vainqueur n'a que sa carte de vainqueur")
semi_cards = [p for p in before if p not in (champ, fin) and any(x.get("trophy") and x["trophy"]["rank"] >= 4 and x["quantity"] > 0 for x in c.get("/collection", headers=H[p]).json())]
ok(semi_cards == [], "les demi-finalistes (et les autres) ne reçoivent aucune carte de tournoi")
ok(any(t["id"] == "tournoi" and t["unlocked"] for t in c.get("/cosmetics", headers=H[champ]).json()["titles"]), "le titre « Champion de tournoi » est débloqué")
ev = chat_events(H["t1"]); ok(any(("%s remporte le tournoi de novembre 2026 et gagne 91 crédits + le trophée" % champ) in t and "Finaliste : " + fin in t for t in ev), "le champion est annoncé dans le chat : « " + next(t for t in ev if "remporte le tournoi" in t) + " »")
h = c.get("/tournament/history").json(); ok(h[0]["label"] == "novembre 2026" and h[0]["champion"] == champ and h[0]["finalist"] == fin and h[0]["players"] == 6 and h[0]["pool"] == 180 and len(h[0]["semifinalists"]) == 2, "l'historique des tournois le retient")
ok({p: U(p).elo for p in H} == elo0 and db.query(Duel).count() == duels0, "toujours aucun effet sur l'Elo ni sur l'historique 1v1 après tout le tournoi")

print("7) TIRAGE EN RETARD, 3 JOUEURS (décembre)")
at(2026, 12, 3, 10)
for p in ("t1", "t2", "t3"): c.post("/tournament/join", headers=H[p])
at(2026, 12, 8, 19); g = info(H["t1"]); ok(g["phase"] == "running" and g["rounds_total"] == 2 and g["rounds"][0]["opens_at"].startswith("2026-12-08T19:00"), "tirage à 19h (site arrêté plus tôt) : le tour s'ouvre tout de suite pour que chacun garde ses 24 h")
sm = g["rounds"][0]["matches"]; ok(sm[0]["via"] == "bye" and sm[0]["winner"] == "t1" and [sm[1]["p1"]["pseudo"], sm[1]["p2"]["pseudo"]] == ["t2", "t3"], "3 joueurs : t1 exempté, demi-finale t2 – t3")
pool3 = g["pool"]; ok(pool3 == 90 and {p["place"]: p["amount"] for p in g["prizes"]} == {1: 55, 2: 22, 3: 13}, "à 3 joueurs : 60 % / 25 % / 15 % de 90 → 55 / 22 / 13")
c.post(f"/tournament/matches/{sm[1]['id']}/team", json=team("t2"), headers=H["t2"]); r = c.post(f"/tournament/matches/{sm[1]['id']}/team", json=team("t3"), headers=H["t3"]).json(); w = r["winner"]
at(2026, 12, 9, 19, 1); g = info(H["t1"]); fid = g["rounds"][1]["matches"][0]["id"]; b3 = {p: cr(p) for p in ("t1", "t2", "t3")}; at(2026, 12, 9, 21)
c.post(f"/tournament/matches/{fid}/team", json=team("t1"), headers=H["t1"]); r = c.post(f"/tournament/matches/{fid}/team", json=team(w), headers=H[w]).json(); d3 = {p: cr(p) - b3[p] for p in b3}; ch = r["winner"]
ok(sorted(d3.values()) == [13, 22, 55] and d3[ch] == 55 and sum(d3.values()) == 90, f"cagnotte de 90 : champion {ch} +55, finaliste +22, demi-finaliste battu +13 : {d3}")

print("8) ANNULATIONS")
at(2027, 1, 4, 10); b = cr("t1"); c.post("/tournament/join", headers=H["t1"]); at(2027, 1, 8, 1); g = info(H["t1"])
ok(g["phase"] == "cancelled" and cr("t1") == b, "un seul inscrit au tirage : tournoi annulé et droit d'entrée remboursé")
ok(any("Le tournoi de janvier 2027 est annulé" in t for t in chat_events(H["t1"])), "l'annulation est annoncée dans le chat")
at(2027, 2, 2, 10); bb = {p: cr(p) for p in ("t1", "t2", "t3")}
for p in bb: c.post("/tournament/join", headers=H[p])
at(2027, 2, 8, 13); ok(info(H["t1"])["phase"] == "running", "février : 3 inscrits, le tournoi démarre")
ok(c.post("/admin/tournament-cancel").status_code == 403 and c.post("/admin/tournament-cancel", headers=A).status_code == 200 and {p: cr(p) for p in bb} == bb and info(H["t1"])["phase"] == "cancelled", "l'administrateur annule un tournoi en cours : tout le monde est remboursé")
ok(c.post("/admin/tournament-cancel", headers=A).status_code == 404, "annuler quand il n'y en a plus : 404")
at(2027, 3, 3, 10)
for p in ("t1", "t2"): c.post("/tournament/join", headers=H[p])
at(2027, 3, 8, 12, 5); g = info(H["t1"]); ok(g["rounds_total"] == 1 and g["rounds"][0]["name"] == "Finale", "2 joueurs : une seule manche, la finale")
bb = {p: cr(p) for p in ("t1", "t2")}; at(2027, 3, 9, 12, 1); g = info(H["t1"])
ok(g["phase"] == "finished" and g["champion"] == "t1" and cr("t1") - bb["t1"] == 42 and cr("t2") - bb["t2"] == 18, "finale oubliée par les deux : le mieux classé gagne ; cagnotte de 60 (2 × 30) en 70 % / 30 % (+42 / +18)")

print("9) SUPPRESSION D'UN COMPTE")
at(2027, 4, 2, 10); c.post("/tournament/join", headers=H["t4"]); c.post("/tournament/join", headers=H["t5"]); c.post("/admin/delete-user", json={"pseudo": "t5"}, headers=A)
ok(info(H["t4"])["entries"] == 1, "un compte supprimé disparaît des inscriptions")
print("10) BEAUCOUP DE JOUEURS (20 inscrits, mai 2027)")
def half(order, s): return order.index(s) // (len(order) // 2)
ok(all(half(TN.bracket_order(P), 1) != half(TN.bracket_order(P), 2) for P in (4, 8, 16, 32, 64)) and TN.bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6], "le tableau place les têtes de série 1 et 2 dans deux moitiés opposées (elles ne se croisent qu'en finale) : 8 → " + str(TN.bracket_order(8)))
ok(all(len({order.index(s) // (len(order) // 4) for s in (1, 2, 3, 4)}) == 4 for order in (TN.bracket_order(16), TN.bracket_order(32))), "les 4 premières têtes de série sont dans 4 quarts différents (16 et 32 places)")
BIG = {}
for i in range(1, 21): BIG["b%02d" % i] = mk("b%02d" % i, 2000 - i * 10)
at(2027, 5, 4, 10)
for p in BIG: c.post("/tournament/join", headers=BIG[p])
at(2027, 5, 8, 0, 10); g = info(BIG["b01"]); r1 = g["rounds"][0]["matches"]
ok(g["entries"] == 20 and g["size"] == 32 and g["rounds_total"] == 5 and [r["name"] for r in g["rounds"]] == ["Seizièmes de finale", "Huitièmes de finale", "Quarts de finale", "Demi-finales", "Finale"], "20 inscrits : tableau de 32, cinq tours : seizièmes, huitièmes, quarts, demi-finales, finale")
ok(sum(1 for m in r1 if m["via"] == "bye") == 12 and sum(1 for m in r1 if m["via"] is None) == 4, "12 exemptés (les 12 mieux classés) et 4 vrais matchs au 1er tour")
real = sorted((m["p1"]["seed"], m["p2"]["seed"]) for m in r1 if m["via"] is None); ok(real == [(13, 20), (14, 19), (15, 18), (16, 17)], f"les vrais matchs opposent les têtes de série 13 à 20 : {real}")
ok(g["rounds"][4]["deadline_at"].startswith("2027-05-13T12:00") and g["rounds"][0]["opens_at"].startswith("2027-05-08T12:00"), "la finale se termine au plus tard le 13 mai à midi : la fin du mois reste libre pour la course à l'Elo")
ok(g["pool"] == 20 * 30 and sum(p["amount"] * (2 if p["place"] == 3 else 1) for p in g["prizes"]) == g["pool"], "la cagnotte (20 × 30 = 600) est répartie en totalité entre vainqueur, finaliste et les 2 demi-finalistes")

print("11) OFFRIR LES CARTES DE TROPHÉE À UN COMPTE DE TEST")
tp = lambda who: {(x["trophy"]["rank"], x["trophy"]["label"]): x["quantity"] for x in c.get("/collection", headers=H[who]).json() if x.get("trophy") and x["quantity"] > 0}
ok(c.post("/admin/give-trophies", json={"pseudo": "t7"}).status_code == 403 and c.post("/admin/give-trophies", json={"pseudo": "inconnu"}, headers=A).status_code == 404, "offrir des trophées : 403 sans clé, 404 pseudo inconnu")
ok(c.post("/admin/give-trophies", json={"pseudo": "t7", "month": "octobre"}, headers=A).status_code == 422 and c.post("/admin/give-trophies", json={"pseudo": "t7", "ranks": [9]}, headers=A).status_code == 422 and c.post("/admin/give-trophies", json={"pseudo": "t7", "ranks": []}, headers=A).status_code == 422, "refusés : mois mal écrit, rang inconnu, liste vide (422)")
r = c.post("/admin/give-trophies", json={"pseudo": "t7", "month": "2026-10"}, headers=A)
ok(r.status_code == 200 and r.json()["cards"] == ["Vainqueur de saison (octobre 2026)", "Deuxième de la saison (octobre 2026)", "Troisième de la saison (octobre 2026)", "Vainqueur du tournoi (octobre 2026)", "Finaliste du tournoi (octobre 2026)"], "les 5 cartes d'octobre 2026 sont offertes : " + ", ".join(r.json()["cards"][:2]) + "…")
ok(tp("t7") == {(k, "octobre 2026"): 1 for k in (1, 2, 3, 4, 5)}, "elles apparaissent dans la collection, en un exemplaire chacune, avec leur rang")
c.post("/admin/give-trophies", json={"pseudo": "t7", "month": "2026-10"}, headers=A); ok(tp("t7") == {(k, "octobre 2026"): 1 for k in (1, 2, 3, 4, 5)}, "les offrir une 2e fois ne crée pas de doublon")
c.post("/admin/give-trophies", json={"pseudo": "t7", "month": "2026-09", "ranks": [4, 5]}, headers=A); ok(tp("t7").get((4, "septembre 2026")) == 1 and tp("t7").get((5, "septembre 2026")) == 1 and (1, "septembre 2026") not in tp("t7"), "on peut choisir un autre mois et seulement certains rangs (4 et 5 de septembre)")
ok(any(x["action"].startswith("Cartes de trophée (rangs 4,5, 2026-09) offertes à t7") for x in c.get("/admin/log", headers=A).json()), "l'action figure dans le journal")

print(); print("BILAN (tournoi mensuel) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
