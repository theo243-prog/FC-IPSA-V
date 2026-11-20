"""
Test : le pack d'édition limitée du Pass Premium est un vrai pack de la réserve (niveaux 20 et 30), ouvert par /pack/open.
Lancé par tests/run_tests.py.
"""
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import battlepass as BP, edition_packs as EP
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 20, 10, 0)]; BP.now_paris = lambda: NOW[0]
db = SessionLocal()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 1000; db.commit(); return {"Authorization": "Bearer " + t}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
H = {"ed1": mk("ed1"), "ed2": mk("ed2"), "ed3": mk("ed3")}
for p in H:
    c.post("/pass/premium", headers=H[p]); c.post("/admin/pass-grant", json={"pseudo": p, "points": 2100}, headers=A)

print("1) SANS CARTE D'ÉDITION : REPLI EN PACK RARE (inchangé)")
b = U("ed3").pack_state.rare_pack_tokens
r = c.post("/pass/claim", json={"track": "premium", "level": 20}, headers=H["ed3"]).json()
ok(r["reward"]["edition_pack"].get("fallback") == "pack rare" and U("ed3").pack_state.rare_pack_tokens == b + 1 and c.get("/me", headers=H["ed3"]).json()["edition_packs"] == [],
   "aucune carte Halloween : 1 pack rare à la place, pas de pack d'édition")

for n in ("Lucas", "Hugo", "Nathan"):
    pl = db.query(Player).filter_by(name=n).first(); db.add(Card(player_id=pl.id, tier=Tier.halloween, vitesse=70, tir=70))
db.commit()

print("2) « RÉCUPÉRER TOUT » ANNONCE LE PACK")
r = c.post("/pass/claim-all", json={}, headers=H["ed1"]).json()
ok(r["summary"]["edition_packs"] == [{"edition": "halloween", "size": 2}] and r["summary"]["edition_cards"] == [], "le récapitulatif annonce un pack d'édition Halloween de 2 cartes (%s)" % r["summary"].get("edition_packs"))
before = {o.card_id for o in db.query(OwnedCard).filter(OwnedCard.user_id == U("ed1").id, OwnedCard.quantity > 0).all()}
hal = {x.id for x in db.query(Card).filter(Card.tier == Tier.halloween).all()}
ok(not (before & hal), "rien n'est ajouté à la collection avant l'ouverture")
packs = c.get("/me", headers=H["ed1"]).json()["edition_packs"]
ok(len(packs) == 1 and packs[0]["season"] == "2026-11", "le pack est dans la réserve (/me)")
r = c.post("/pack/open", json={"pack_type": "edition", "player_pack_id": packs[0]["id"]}, headers=H["ed1"])
ok(r.status_code == 200 and len(r.json()["cards_won"]) == 2 and len({x["id"] for x in r.json()["cards_won"]}) == 2 and all(x["is_new"] for x in r.json()["cards_won"]), "ouverture (identifiant passé comme pour un pack joueur) : 2 cartes Halloween différentes et nouvelles")
ok(c.post("/pack/open", json={"pack_type": "edition", "edition_pack_id": "inconnu"}, headers=H["ed1"]).status_code == 400, "pack inconnu : refusé")

print("3) ÉDITION VIDÉE AVANT L'OUVERTURE")
c.post("/pass/claim", json={"track": "premium", "level": 20}, headers=H["ed2"])
pid = c.get("/me", headers=H["ed2"]).json()["edition_packs"][0]["id"]
r = c.post("/pack/open", json={"pack_type": "edition", "edition_pack_id": pid}, headers=H["ed1"])
ok(r.status_code == 400, "on n'ouvre pas le pack d'un autre joueur")
db.query(OwnedCard).filter(OwnedCard.card_id.in_(list(hal))).delete(synchronize_session=False)
db.query(Card).filter(Card.tier == Tier.halloween).delete(synchronize_session=False); db.commit()
b = U("ed2").pack_state.rare_pack_tokens
r = c.post("/pack/open", json={"pack_type": "edition", "edition_pack_id": pid}, headers=H["ed2"])
ok(r.status_code == 400 and "pack rare" in r.json()["detail"] and U("ed2").pack_state.rare_pack_tokens == b + 1 and c.get("/me", headers=H["ed2"]).json()["edition_packs"] == [], "plus de carte d'édition : le pack devient un pack rare")

print("4) SUPPRESSION D'UN COMPTE")
EP.grant(db, U("ed3"), "noel", 3); db.commit()
ok(c.post("/admin/delete-user", json={"pseudo": "ed3"}, headers=A).status_code == 200 and db.query(EP.OwnedEditionPack).filter_by(user_id=U("ed1").id).count() == 0
   and db.query(EP.OwnedEditionPack).count() == 0, "ses packs d'édition disparaissent avec le compte")

print(); print("BILAN (pack d'édition du Pass) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
