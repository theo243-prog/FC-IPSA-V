"""
Test : au tournoi, l'équipe validée une fois (pour un match, ou à l'avance) est gardée pour tout le tournoi : à l'heure limite, elle est jouée
si le joueur n'a rien validé pour ce match ; plus de forfait ; modifiable à tout moment. Lancé par tests/run_tests.py.
"""
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import tournament as TN
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 2, 10, 0)]; TN.now_paris = lambda: NOW[0]
def at(y, mo, d, h=0, mi=0): NOW[0] = datetime(y, mo, d, h, mi)
db = SessionLocal()
card = lambda n, t: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
CORE = [("Lucas", "GB"), ("Hugo", "DEF"), ("Nathan", "MC"), ("Léo", "MC"), ("Enzo", "ATT")]
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p, elo):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.elo, u.credits = elo, 100
    for n, _ in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n, "commune").id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
def team(tactic="pressing"):
    return {"formation": "1-2-1", "tactic": tactic, "slots": [{"card_id": card(n, "commune").id, "slot_category": s} for (n, _), s in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
info = lambda p: c.get("/tournament", headers=H[p]).json()
H = {p: mk(p, e) for p, e in (("a1", 1400), ("a2", 1300), ("a3", 1200), ("a4", 1100))}

print("1) ENREGISTRER SON ÉQUIPE À L'AVANCE")
ok(c.post("/tournament/team", json=team(), headers=H["a1"]).status_code == 400, "pas inscrit : refusé")
for p in H: c.post("/tournament/join", headers=H[p])
ok(info("a1")["me"]["team_saved"] is False, "inscrit, pas encore d'équipe enregistrée")
r = c.post("/tournament/team", json=team("contre"), headers=H["a1"])
ok(r.status_code == 200 and info("a1")["me"]["team_saved"] is True, "a1 enregistre son équipe pendant les inscriptions (avant le 1er tour)")
bad = team(); bad["slots"][0]["card_id"] = card("Tom", "commune").id
ok(c.post("/tournament/team", json=bad, headers=H["a2"]).status_code == 400, "une carte qu'on n'a pas : refusée")

print("2) PREMIER TOUR : PLUS DE FORFAIT AVEC UNE ÉQUIPE ENREGISTRÉE")
at(2026, 11, 8, 13); g = info("a1")
mine = g["me"]["match"]; opp = mine["p2"]["pseudo"] if mine["me_side"] == 1 else mine["p1"]["pseudo"]
ok(mine["state"] == "open" and mine["submitted"][mine["me_side"] - 1] is True and mine["my_team_ready"] is False, "a1 n'a rien validé pour ce match, mais son équipe enregistrée compte comme prête")
ok(TN.todo(db, U("a1")) is False and TN.todo(db, U(opp)) is True, "pas de point rouge pour a1 (rien à faire) ; son adversaire, sans équipe, en a un")
other = [p for p in H if p not in ("a1", opp)]
c.post("/tournament/matches/%s/team" % next(m["id"] for m in g["rounds"][0]["matches"] if m["p1"]["pseudo"] in other), json=team(), headers=H[other[0]])
at(2026, 11, 9, 12, 1); g = info("a1")
m1 = next(m for m in g["rounds"][0]["matches"] if "a1" in (m["p1"]["pseudo"], m["p2"]["pseudo"]))
ok(m1["state"] == "done" and m1["via"] == "forfeit" and m1["winner"] == "a1", "heure limite : a1 joue avec son équipe enregistrée, son adversaire sans équipe perd par forfait")
m2 = next(m for m in g["rounds"][0]["matches"] if m["id"] != m1["id"])
ok(m2["state"] == "done" and m2["via"] == "forfeit" and m2["winner"] == other[0], "l'autre match : %s avait validé son équipe, %s n'en a jamais enregistré : forfait (seul cas restant)" % (other[0], other[1]))

print("3) LES TOURS SUIVANTS SANS REVENIR")
fin = g["rounds"][1]["matches"][0]; w2 = m2["winner"]
ok({fin["p1"]["pseudo"], fin["p2"]["pseudo"]} == {"a1", w2} and fin["submitted"] == [True, True], "finale a1 – %s : les deux équipes (validées une fois au tour d'avant) sont déjà prêtes" % w2)
ok(TN.todo(db, U("a1")) is False and TN.todo(db, U(w2)) is False, "personne n'a besoin de revenir")
c.post("/tournament/team", json=team("possession"), headers=H["a1"])
e = db.query(TN.TournamentEntry).filter_by(user_id=U("a1").id).first(); db.refresh(e)
ok('"possession"' in e.team_json, "a1 modifie son équipe du tournoi (tactique) à tout moment")
at(2026, 11, 10, 12, 1); g = info("a1"); f = g["rounds"][1]["matches"][0]
ok(f["state"] == "done" and f["via"] == "play" and f["replay"] and g["phase"] == "finished", "heure limite de la finale : jouée avec les deux équipes enregistrées (vrai match, récit), sans forfait")
rc = c.get("/tournament/matches/%s/recap" % f["id"]).json()
side = "challenger" if rc["challenger"] == "a1" else "defender"
ok(rc["lineups"][side]["tactic"] == "possession", "c'est bien la dernière version de l'équipe de a1 qui a joué (possession)")

print("4) ÉQUIPE DEVENUE INVALIDE")
ok(TN._prepare(db, U("a1"), {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": "inconnue", "slot_category": "GB"}] * 5}) is None, "une équipe enregistrée dont les cartes ne sont plus là ne joue pas (forfait, comme avant)")
ok(c.post("/tournament/team", json=team(), headers=H["a2"]).status_code == 400, "après la fin du tournoi : plus rien à enregistrer")

print(); print("BILAN (équipe du tournoi gardée) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
