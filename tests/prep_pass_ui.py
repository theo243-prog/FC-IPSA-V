"""Prépare le test navigateur du Pass : 2 joueurs (alice : 400 crédits, 1200 points ; bob : 50 crédits), 4 cartes d'édition Halloween. Horloge simulée : 12 novembre. Écrit /tmp/ctx.json."""
import json, os
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import User, Card, Player, Tier
os.environ["FC_FAKE_NOW"] = "2026-11-12T10:00:00"
c = TestClient(app); A = {"X-Admin-Key": "k"}; db = SessionLocal(); tokens = {}
for p, cr in (("alice", 400), ("bob", 50)):
    tokens[p] = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; c.post("/welcome/seen", headers={"Authorization": "Bearer " + tokens[p]})
    db.query(User).filter_by(pseudo=p).first().credits = cr
for n in ("Lucas", "Hugo", "Nathan", "Léo"):
    db.add(Card(player_id=db.query(Player).filter_by(name=n).first().id, tier=Tier.halloween, vitesse=70, tir=70))
db.commit(); assert c.post("/admin/pass-grant", json={"pseudo": "alice", "points": 1200}, headers=A).status_code == 200
json.dump({"tokens": tokens}, open("/tmp/ctx.json", "w")); print("Pass de démonstration prêt (12 novembre, alice : niveau 12)")
