"""Prépare les données du test navigateur (tests/ui_social2.js) : 2 joueurs, des doublons, 2 matchs à venir, un message de chat. Écrit /tmp/ctx.json."""
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import profiles as PR, prono as PN
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; db = SessionLocal(); tokens = {}
for p in ("alice", "bob"):
    tokens[p] = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
for p in tokens:
    c.post("/welcome/seen", headers={"Authorization": "Bearer " + tokens[p]})      # un compte neuf voit d'abord le pop-up de bienvenue : on le marque comme vu
for p in tokens:
    c.post("/admin/grant-credits", json={"pseudo": p, "amount": 100}, headers=A)      # des crédits pour pouvoir miser
card = lambda n, t: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
def own(p, n, t, q):
    u = db.query(User).filter_by(pseudo=p).first(); o = db.query(OwnedCard).filter_by(user_id=u.id, card_id=card(n, t).id).first()
    if o: o.quantity = q
    else: db.add(OwnedCard(user_id=u.id, card_id=card(n, t).id, quantity=q))
for n, t in (("Hugo", "rare"), ("Lucas", "commune")): own("alice", n, t, 2)
for n, t in (("Mathis", "commune"), ("Enzo", "rare")): own("bob", n, t, 2)
ua = db.query(User).filter_by(pseudo="alice").first().id
for bid, lv in [("packs", 1), ("packs", 2), ("collection", 1), ("matchs", 1), ("matchs", 2)]: db.add(PR.UserBadge(user_id=ua, badge_id=bid, level=lv, seen=True))
db.commit()
now = PN.now_paris()
c.post("/admin/add-upcoming-match", json={"date": (now + timedelta(days=3)).strftime("%Y-%m-%d") + " 15:00", "opponent": "Rivaux FC", "location": "Stade municipal"}, headers=A)
c.post("/admin/add-upcoming-match", json={"date": (now - timedelta(days=1)).strftime("%Y-%m-%d") + " 20:00", "opponent": "Passé FC"}, headers=A)
c.post("/chat", json={"text": "Salut Alice !"}, headers={"Authorization": "Bearer " + tokens["bob"]})
json.dump({"tokens": tokens}, open("/tmp/ctx.json", "w")); print("données prêtes")
