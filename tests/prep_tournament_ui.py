"""Prépare le test navigateur du tournoi : 5 joueurs avec une équipe, tous marqués « bienvenue vu ». 4 sont déjà inscrits (le 3 novembre, horloge simulée), alice s'inscrira à la main.
Écrit /tmp/ctx.json. À lancer avec la même base que le serveur de test."""
import json, os
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import User, Card, Player, OwnedCard, Tier
os.environ["FC_FAKE_NOW"] = "2026-11-03T10:00:00"
c = TestClient(app); A = {"X-Admin-Key": "k"}; db = SessionLocal(); tokens = {}
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
ELO = {"alice": 1050, "bob": 1300, "cara": 1200, "dan": 1000, "eve": 1100}
for p, elo in ELO.items():
    tokens[p] = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    c.post("/welcome/seen", headers={"Authorization": "Bearer " + tokens[p]})
    u = db.query(User).filter_by(pseudo=p).first(); u.elo, u.credits = elo, 100
    for n in ("Lucas", "Hugo", "Nathan", "Léo", "Enzo"): db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
db.commit()
for p in ("bob", "cara", "dan", "eve"):
    r = c.post("/tournament/join", headers={"Authorization": "Bearer " + tokens[p]}); assert r.status_code == 200, r.text
json.dump({"tokens": tokens}, open("/tmp/ctx.json", "w")); print("tournoi de démonstration prêt : 4 inscrits")
