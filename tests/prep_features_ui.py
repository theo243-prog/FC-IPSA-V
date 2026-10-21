"""Prépare le test navigateur des nouveautés : alice (riche, cartes rares, tous les autocollants), bob et carol, un match alice-bob. Écrit /tmp/ctx.json."""
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); db = SessionLocal(); A = {"X-Admin-Key": "k"}; ctx = {"tokens": {}}
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]; H = {}
for p, cr in (("alice", 1000), ("bob", 500), ("carol", 200)):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; c.post("/welcome/seen", headers={"Authorization": "Bearer " + t}); ctx["tokens"][p] = t; H[p] = {"Authorization": "Bearer " + t}
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = cr
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit()
al = db.query(User).filter_by(pseudo="alice").first()
for off in (0, 1):                                              # deux cartes rares différentes, en deux exemplaires
    cd = db.query(Card).filter(Card.tier == Tier.rare).offset(off).first(); o = db.query(OwnedCard).filter_by(user_id=al.id, card_id=cd.id).first()
    if o is None: db.add(OwnedCard(user_id=al.id, card_id=cd.id, quantity=2))
    else: o.quantity = 2
db.commit(); c.post("/admin/unlock-cosmetics", json={"pseudo": "alice", "enabled": True}, headers=A)
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["alice"]).json()["id"]; r = c.post(f"/duel/proposals/{pid}/play", json=team, headers=H["bob"]).json()
ctx["refcode"] = c.get("/referral", headers=H["alice"]).json()["code"]; ctx["duel"] = r.get("result")
json.dump(ctx, open("/tmp/ctx.json", "w")); print("prêt : alice, bob, carol ; match alice-bob :", ctx["duel"], "; code d'alice :", ctx["refcode"])
