"""
Test : le gel de fatigue du shop (5 matchs 1v1 sans fatigue ; 50 crédits, puis le prix double à chaque achat du jour, sans limite).
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import duel_engine as DE, fatigue, fatigue_gel as G, missions
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
def mk(p, credits=1000):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {"gela": mk("gela"), "gelb": mk("gelb"), "pauvre": mk("pauvre", 40)}
uid = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
DE.draw_goals = lambda xg: 1
def match(creator="gela", player="gelb"):
    pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H[creator]).json()["id"]
    return c.post(f"/duel/proposals/{pid}/play", json=team, headers=H[player]).json()
form = lambda p: (db.expire_all(), fatigue.forms_for(db, uid(p).id).get(card("Lucas").id, 1.0))[1]

print("1) PRIX QUI DOUBLE")
g = c.get("/shop/fatigue-gel", headers=H["gela"]).json()
ok(g["price"] == 50 and g["left"] == 0 and g["matches"] == 5, "au départ : 50 crédits, aucun gel (%s)" % g)
cr0 = uid("gela").credits
prices = [c.post("/shop/fatigue-gel/buy", headers=H["gela"]).json()["paid"] for _ in range(4)]
ok(prices == [50, 100, 200, 400], "4 achats le même jour : 50, 100, 200, 400 crédits (%s), sans limite" % prices)
ok(uid("gela").credits == cr0 - 750, "750 crédits retirés")
g = c.get("/me", headers=H["gela"]).json()["fatigue_gel"]
ok(g["left"] == 20 and g["price"] == 800 and g["bought_today"] == 4, "les matchs s'additionnent : 20 matchs de gel, prochain achat à 800 (%s)" % g)
r = c.post("/shop/fatigue-gel/buy", headers=H["pauvre"])
ok(r.status_code == 400 and "50" in r.json()["detail"], "pas assez de crédits : refus clair")
ok(G.left(db, uid("pauvre").id) == 0 and uid("pauvre").credits == 40, "rien n'est retiré au refus")

print("2) LES MATCHS DE GEL NE FATIGUENT PAS")
r = match()                                     # gela (20 matchs de gel) crée, gelb (sans gel) relève
ok(r.get("gel_to") == ["gela"], "le résultat indique qui joue avec le gel (%s)" % r.get("gel_to"))
ok(form("gela") == 1.0 and form("gelb") < 1.0, "gela n'a rien perdu, gelb a perdu de la forme (%.4f / %.4f)" % (form("gela"), form("gelb")))
ok(G.left(db, uid("gela").id) == 19, "un match de gel consommé (19 restants)")
r = match("gelb", "gela")                       # gela relève cette fois
ok(r.get("gel_to") == ["gela"] and G.left(db, uid("gela").id) == 18 and form("gela") == 1.0, "aussi quand gela relève le défi")

print("3) FIN DU GEL")
db.query(G.UserCounter).filter_by(user_id=uid("gela").id, key=G.LEFT_KEY).first().value = 1; db.commit()
match(); ok(G.left(db, uid("gela").id) == 0 and form("gela") == 1.0, "dernier match de gel : toujours pas de fatigue")
r = match(); ok(r.get("gel_to") == [] and form("gela") < 1.0, "gel épuisé : la fatigue reprend")

print("4) LE PRIX REPART À 50 LE LENDEMAIN")
row = missions._row(db, uid("gela")); row.day = "2000-01-01"; db.commit()
ok(c.get("/shop/fatigue-gel", headers=H["gela"]).json()["price"] == 50, "nouveau jour : le gel recoûte 50 crédits")

print(); print("BILAN (gel de fatigue) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
