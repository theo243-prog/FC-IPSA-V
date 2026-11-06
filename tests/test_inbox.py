"""
Test : encadré « Notifications » du site. Les messages personnels (défi relevé, carte vendue, enchère dépassée, offre acceptée…)
y sont rangés même sans téléphone abonné ; les annonces générales et les rappels de packs n'y vont pas. Lus un par un ou tous
d'un coup, compteur dans /me, nettoyés avec le compte. Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import inbox as IB, push, duel_engine as DE
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
card = lambda n, t="commune": db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
CORE = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 500
    for n, _ in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=2))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("ana", "bob", "cyr")}
notes = lambda p: c.get("/notifications", headers=H[p]).json()

print("1) CE QUI ARRIVE DANS L'ENCADRÉ")
ok(notes("ana") == {"unread": 0, "items": []} and c.get("/me", headers=H["ana"]).json()["notices_unread"] == 0, "au départ : rien")
lid = c.post("/market/list", json={"card_id": card("Hugo").id, "price": 5}, headers=H["ana"]).json()["id"]
c.post("/market/buy/%s" % lid, headers=H["bob"])
n = notes("ana"); ok(n["unread"] == 1 and "vendue" in n["items"][0]["title"].lower() and n["items"][0]["url"] == "/#marche", "carte vendue : le vendeur est prévenu, même sans téléphone abonné (« %s »)" % n["items"][0]["title"])
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(x).id, "slot_category": s} for x, s in CORE]}
DE.draw_goals = lambda xg: 1
pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["ana"]).json()["id"]; c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["bob"])
n = notes("ana"); ok(n["unread"] == 2 and "a joué ton défi" in n["items"][0]["title"], "défi relevé : le créateur est prévenu (« %s »)" % n["items"][0]["title"])


r = c.post("/market/offers", json={"card_id": card("Enzo").id, "price": 3}, headers=H["bob"]).json()
c.post("/market/offers/%s/accept" % r["id"], headers=H["ana"])
ok(any("Offre acceptée" in x["title"] for x in notes("bob")["items"]), "offre d'achat acceptée : l'acheteur est prévenu")
push.notify_all(db, "cards", "Nouvelles cartes", "Pour tout le monde"); push.enqueue(db, U("ana").id, "packs", "Pack prêt", "Ton pack t'attend"); db.commit()
ok(notes("ana")["unread"] == 2, "les annonces générales et les rappels de packs n'y vont pas")
ok(c.get("/me", headers=H["ana"]).json()["notices_unread"] == 2, "/me donne le nombre de notifications non lues")

print("2) LIRE")
first = notes("ana")["items"][0]["id"]
r = c.post("/notifications/read", json={"ids": [first]}, headers=H["ana"]).json(); ok(r["unread"] == 1, "lire une notification : 1 non lue restante")
r = c.post("/notifications/read", json={"ids": []}, headers=H["ana"]).json(); ok(r["unread"] == 0 and all(x["read"] for x in notes("ana")["items"]), "tout marquer comme lu")
ok(c.post("/notifications/read", json={"ids": [first]}, headers=H["bob"]).json()["unread"] == notes("bob")["unread"], "on ne peut pas toucher aux notifications d'un autre")
ok(c.get("/notifications").status_code == 401, "sans compte : 401")
for i in range(70): IB.add(db, U("cyr").id, "market", "Test %d" % i, "x")
db.commit(); c.post("/notifications/read", json={"ids": []}, headers=H["cyr"]); db.expire_all()
ok(db.query(IB.UserNotice).filter_by(user_id=U("cyr").id).count() == IB.KEEP, "au plus %d notifications gardées par joueur" % IB.KEEP)

print("3) NETTOYAGE")
uid = U("cyr").id; c.post("/admin/delete-user", json={"pseudo": "cyr"}, headers=A); db.expire_all()
ok(db.query(IB.UserNotice).filter_by(user_id=uid).count() == 0, "compte supprimé : ses notifications aussi")
print("BILAN (notifications du site) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
