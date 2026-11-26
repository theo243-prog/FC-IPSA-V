"""
Test : échange libre (branche echange-libre, 26/11/2026) : toute carte s'échange, dernier exemplaire compris, des deux côtés ; le niveau
suit la carte comme au marché (un doublon part en copie normale, un dernier exemplaire part avec son niveau, on garde son meilleur niveau) ;
GET /swaps/cards/{pseudo} montre toutes ses cartes échangeables (pas les trophées ni les numérotées).
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import card_levels as CL
from app.models import User, Card, OwnedCard, Player, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
H = {p: {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]} for p in ("libra", "librb")}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def qty(p, card_id):
    db.expire_all(); o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=card_id).first(); return o.quantity if o else 0
def setq(p, card_id, q):
    o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=card_id).first()
    if o is None: db.add(OwnedCard(user_id=U(p).id, card_id=card_id, quantity=q))
    else: o.quantity = q
    db.commit()
def lvl(p, card_id): db.expire_all(); return CL.level_of(db, U(p).id, card_id)
rares = db.query(Card).join(Player).filter(Card.tier == Tier.rare, Player.poste.notin_(["TROPHEE", "MOMENT", "NUMEROTEE"])).order_by(Player.name).limit(4).all()
A1, B1, A2, NONE = rares
setq("libra", A1.id, 1); setq("librb", B1.id, 1); setq("libra", A2.id, 3)
CL.set_level(db, U("libra").id, A1.id, 3); CL.set_level(db, U("libra").id, A2.id, 2); db.commit()
tp = Player(name="Trophée échange (test)", poste="TROPHEE"); db.add(tp); db.flush(); tc = Card(player_id=tp.id, tier=Tier.saison, vitesse=0, tir=0); db.add(tc); db.flush()
db.add(OwnedCard(user_id=U("librb").id, card_id=tc.id, quantity=1)); db.commit()

print("1) LES CARTES QU'ON PEUT DEMANDER")
lst = c.get("/swaps/cards/librb", headers=H["libra"]).json(); got = {x["id"] for x in lst}
ok(B1.id in got, "sa carte en 1 exemplaire est proposée")
ok(tc.id not in got, "un trophée de saison n'est jamais proposé")
ok(c.get("/swaps/cards/personne_xyz", headers=H["libra"]).status_code == 404 and c.get("/swaps/cards/librb").status_code == 401, "joueur inconnu : 404 ; sans compte : 401")

print("2) DERNIER EXEMPLAIRE CONTRE DERNIER EXEMPLAIRE, AVEC SON NIVEAU")
r = c.post("/swaps", json={"to": "librb", "give_card_id": A1.id, "want_card_id": B1.id}, headers=H["libra"])
ok(r.status_code == 200, "proposer son seul exemplaire contre son seul exemplaire (%s %s)" % (r.status_code, r.text[:80]))
r = c.post("/swaps/%s/accept" % r.json()["id"], headers=H["librb"])
ok(r.status_code == 200, "accepté (%s)" % r.status_code)
ok((qty("libra", A1.id), qty("libra", B1.id), qty("librb", A1.id), qty("librb", B1.id)) == (0, 1, 1, 0), "les cartes ont changé de main")
ok(lvl("libra", A1.id) == 0 and lvl("librb", A1.id) == 3, "le dernier exemplaire part avec son niveau 3")

print("3) UN DOUBLON PART EN COPIE NORMALE")
r = c.post("/swaps", json={"to": "librb", "give_card_id": A2.id, "want_card_id": A1.id}, headers=H["libra"])
ok(r.status_code == 200, "proposition avec un doublon")
ok(c.post("/swaps/%s/accept" % r.json()["id"], headers=H["librb"]).status_code == 200, "accepté")
ok(qty("libra", A2.id) == 2 and lvl("libra", A2.id) == 2 and lvl("librb", A2.id) == 0, "ana garde sa copie niveau 2, ben reçoit une copie normale")
ok(qty("libra", A1.id) == 1 and lvl("libra", A1.id) == 3 and lvl("librb", A1.id) == 0, "la carte niveau 3 revient avec son niveau")

print("4) REFUS")
r = c.post("/swaps", json={"to": "librb", "give_card_id": A1.id, "want_card_id": tc.id}, headers=H["libra"])
ok(r.status_code == 400, "demander un trophée : refusé")
r = c.post("/swaps", json={"to": "librb", "give_card_id": NONE.id, "want_card_id": A2.id}, headers=H["libra"])
ok(r.status_code == 400 and "pas cette carte" in r.json()["detail"], "donner une carte qu'on n'a plus : refusé")
r = c.post("/swaps", json={"to": "librb", "give_card_id": A1.id, "want_card_id": A2.id}, headers=H["libra"]); sid = r.json()["id"]
setq("libra", A1.id, 0)
r = c.post("/swaps/%s/accept" % sid, headers=H["librb"])
ok(r.status_code == 400 and qty("librb", A2.id) == 1, "carte partie avant l'acceptation : refusé, rien ne bouge")

print(); print("BILAN (échange libre) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
