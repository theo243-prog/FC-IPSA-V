"""
Test : vendre depuis la collection (« vendre tous les doublons de cette carte », vente directe et enchères d'une carte précise).
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import game_logic as GL, profiles
from app.models import User, Card, Tier, OwnedCard
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
H = {p: {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]} for p in ("ana", "bob")}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
qty = lambda cid: (db.expire_all(), db.query(OwnedCard).filter_by(user_id=U("ana").id, card_id=cid).first().quantity)[1]
com = db.query(Card).filter(Card.tier == Tier.commune).first()
rare = db.query(Card).filter(Card.tier == Tier.rare).first()
for card, n in ((com, 6), (rare, 2)):
    db.add(OwnedCard(user_id=U("ana").id, card_id=card.id, quantity=n))
db.commit()
v = GL.DUPLICATE_SELL_VALUE["commune"]

print("1) VENDRE UN DOUBLON (COMME AVANT)")
before = U("ana").credits
r = c.post("/collection/sell-duplicate", json={"card_id": com.id}, headers=H["ana"])
ok(r.status_code == 200 and r.json()["sold"] == 1 and r.json()["credits_gained"] == v and qty(com.id) == 5, "1 exemplaire vendu au prix prévu")
ok(U("ana").credits == before + v, "crédits ajoutés")

print("2) VENDRE TOUS LES DOUBLONS DE CETTE CARTE")
dupes0 = profiles._counter(db, U("ana").id, "sell_dupes")
r = c.post("/collection/sell-duplicate", json={"card_id": com.id, "all": True}, headers=H["ana"])
ok(r.status_code == 200 and r.json()["sold"] == 4 and r.json()["credits_gained"] == 4 * v, "les 4 doublons vendus d'un coup, au prix prévu chacun")
ok(qty(com.id) == 1, "il reste 1 exemplaire")
db.expire_all()
ok(profiles._counter(db, U("ana").id, "sell_dupes") == dupes0 + 4, "chaque doublon compte pour le succès « Recycleur »")
ok(c.post("/collection/sell-duplicate", json={"card_id": com.id, "all": True}, headers=H["ana"]).status_code == 400, "plus de doublon : refusé")
ok(qty(rare.id) == 2, "les autres cartes ne bougent pas")

print("3) VENTE DIRECTE ET ENCHÈRES D'UNE CARTE PRÉCISE (ROUTES DU MARCHÉ)")
ok(c.post("/market/list", json={"card_id": rare.id, "price": 30}, headers=H["ana"]).status_code == 200 and qty(rare.id) == 1, "mise en vente au marché : la carte est mise de côté")
ok(c.post("/auctions", json={"card_id": rare.id, "start_price": 20, "minutes": 60}, headers=H["ana"]).status_code == 200 and qty(rare.id) == 0, "mise aux enchères : la carte est mise de côté")
ok(c.post("/auctions", json={"card_id": com.id, "start_price": 20, "minutes": 60}, headers=H["ana"]).status_code == 400, "une commune ne va pas aux enchères")

print("4) OFFRE D'ACHAT SUR UNE CARTE QUE J'AI DÉJÀ")
ok(c.post("/market/offers", json={"card_id": com.id, "price": 5}, headers=H["ana"]).status_code == 200, "offre d'achat pour un exemplaire de plus")
db.add(OwnedCard(user_id=U("bob").id, card_id=com.id, quantity=1)); db.commit()
ok(any(o["card"]["id"] == com.id for o in c.get("/market/offers/for-me", headers=H["bob"]).json()), "un autre joueur qui a la carte la voit")
ok(not any(o["card"]["id"] == com.id for o in c.get("/market/offers/for-me", headers=H["ana"]).json()), "jamais sa propre offre dans « offres pour moi »")

print(); print("BILAN (vente depuis la collection) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
