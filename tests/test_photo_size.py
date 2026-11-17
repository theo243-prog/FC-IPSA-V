"""
Test : taille de la photo sur une carte (« classique » par défaut, « maxi » = l'image remplit toute la carte), réglée carte par carte par l'admin.
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import Card, Player, Tier, User, OwnedCard
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
H = {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": "ana", "password": "test1234"}).json()["token"]}
card = lambda n, t: (db.expire_all(), db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first())[1]
ana = db.query(User).filter_by(pseudo="ana").first()
for t in ("rare", "commune"):
    db.add(OwnedCard(user_id=ana.id, card_id=card("Lucas", t).id, quantity=1))
db.commit()
def col(n, t):
    return next(x for x in c.get("/collection", headers=H).json() if x.get("player_name") == n and x["tier"] == t)

print("1) PAR DÉFAUT : CLASSIQUE")
ok(card("Lucas", "rare").photo_size is None and col("Lucas", "rare")["photo_size"] == "classique", "une carte sans réglage : « classique »")

print("2) RÉGLAGE ADMIN")
post = lambda **p: c.post("/admin/card-photo-size", json=p, headers=A)
ok(c.post("/admin/card-photo-size", json={"player_name": "Lucas", "tier": "rare", "size": "maxi"}).status_code == 403, "sans clé admin : 403")
ok(post(player_name="Lucas", tier="rare", size="geant").status_code == 400, "taille inconnue : refusée")
ok(post(player_name="Personne", tier="rare", size="maxi").status_code == 404, "joueur inconnu : 404")
ok(post(player_name="Lucas", tier="secrete-x", size="maxi").status_code == 400, "rareté inconnue : refusée")
r = post(player_name="Lucas", tier="rare", size="maxi")
ok(r.status_code == 200 and r.json()["photo_size"] == "maxi" and card("Lucas", "rare").photo_size == "maxi", "Lucas rare passe en « maxi »")
ok(col("Lucas", "rare")["photo_size"] == "maxi" and col("Lucas", "commune")["photo_size"] == "classique", "seulement cette carte : la commune de Lucas reste classique")
r = post(player_name="Lucas", tier="rare", size="classique")
ok(r.status_code == 200 and card("Lucas", "rare").photo_size is None and col("Lucas", "rare")["photo_size"] == "classique", "retour à « classique »")

print(); print("BILAN (taille de la photo) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
