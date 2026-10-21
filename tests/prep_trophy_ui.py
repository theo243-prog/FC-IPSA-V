"""Prépare le test navigateur des cartes de tournoi : un joueur « alice » avec un trophée de saison, les cartes de vainqueur et de finaliste du tournoi, et quelques cartes. Écrit /tmp/ctx.json."""
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import seasons as S, game_logic as GL
from app.models import User, Card, Player, Tier, OwnedCard
c = TestClient(app); db = SessionLocal()
tok = c.post("/auth/register", json={"pseudo": "alice", "password": "test1234"}).json()["token"]; c.post("/welcome/seen", headers={"Authorization": "Bearer " + tok})
u = db.query(User).filter_by(pseudo="alice").first()
for key, rank in (("2026-10", 1), ("2026-11", 4), ("2026-11", 5)): GL.get_or_create_owned(db, u, S.get_or_create_trophy(db, key, rank)).quantity = 1
for n in ("Lucas", "Hugo", "Nathan"): db.add(OwnedCard(user_id=u.id, card_id=db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first().id, quantity=1))
db.commit(); json.dump({"tokens": {"alice": tok}}, open("/tmp/ctx.json", "w")); print("cartes de tournoi prêtes")
