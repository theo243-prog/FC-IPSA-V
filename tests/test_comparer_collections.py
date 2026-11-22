"""
Test : comparer sa collection avec celle d'un joueur (GET /swaps/compare/{pseudo}) : ses doublons qui me manquent, mes doublons qui lui
manquent, nombres en commun, jamais une carte qu'aucun des deux n'a, échange proposé en un clic avec ces cartes.
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
cards = db.query(Card).join(Player).filter(Card.tier == Tier.commune).order_by(Player.name).limit(8).all()
X, Y, Z, W, V, NOBODY, R2, _ = cards
rare = db.query(Card).filter(Card.tier == Tier.rare).first()
def mk(p, owned):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first()
    for card, q in owned: db.add(OwnedCard(user_id=u.id, card_id=card.id, quantity=q))
    db.commit(); return {"Authorization": "Bearer " + t}
A = mk("cmpa", [(X, 3), (Y, 1), (Z, 2), (rare, 2)])
B = mk("cmpb", [(Y, 1), (W, 2), (V, 1), (Z, 1)])

print("1) CE QUE CHACUN PEUT DONNER")
d = c.get("/swaps/compare/cmpb", headers=A).json()
ids = lambda k: [x["id"] for x in d[k]]
ok(ids("their_doubles_i_lack") == [W.id], "ses doublons qui me manquent : seulement W (%s)" % ids("their_doubles_i_lack"))
ok(set(ids("my_doubles_they_lack")) == {X.id, rare.id}, "mes doublons qui lui manquent : X et la rare (Z, il l'a déjà)")
ok(ids("my_doubles_they_lack")[0] == rare.id, "la rareté la plus haute d'abord")
ok((d["common"], d["only_me"], d["only_them"]) == (2, 2, 2), "en commun 2 (Y, Z), moi seul 2 (X, rare), lui seul 2 (W, V) : %s" % ((d["common"], d["only_me"], d["only_them"]),))
txt = str(d)
ok(NOBODY.id not in txt and R2.id not in txt and V.id not in txt, "une carte qu'aucun n'a, ou que lui seul a sans doublon, n'est jamais envoyée")
ok(d["pseudo"] == "cmpb" and d["max_open"] == 5 and d["open_swaps"] == 0, "pseudo et propositions en attente")
d2 = c.get("/swaps/compare/cmpa", headers=B).json()
ok([x["id"] for x in d2["my_doubles_they_lack"]] == [W.id] and (d2["only_me"], d2["only_them"]) == (2, 2), "dans l'autre sens, les rôles s'inversent")

print("2) ÉCHANGE EN UN CLIC")
r = c.post("/swaps", json={"to": "cmpb", "give_card_id": X.id, "want_card_id": W.id}, headers=A)
ok(r.status_code == 200, "l'échange se propose avec les cartes de la comparaison (%s)" % r.status_code)
ok(c.get("/swaps/compare/cmpb", headers=A).json()["open_swaps"] == 1, "la proposition compte dans « en attente »")

print("3) REFUS")
ok(c.get("/swaps/compare/cmpa", headers=A).status_code == 400, "avec soi-même : refusé")
ok(c.get("/swaps/compare/personne_xyz", headers=A).status_code == 404, "joueur inconnu : 404")
ok(c.get("/swaps/compare/cmpb").status_code == 401, "sans compte : refusé")

print(); print("BILAN (comparer les collections) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
