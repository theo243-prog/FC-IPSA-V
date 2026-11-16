"""
Test : 5 doublons d'une carte commune s'échangent contre la carte rare de la même personne (doublons consommés, la commune et son niveau restent).
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import card_levels as CL
from app.models import User, Card, OwnedCard, Player, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
H = {p: {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]} for p in ("ana", "bob")}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def card_of(tier, need_rare=True):
    for pl in db.query(Player).all():
        tiers = {cd.tier: cd for cd in db.query(Card).filter_by(player_id=pl.id).all()}
        if Tier.commune in tiers and (Tier.rare in tiers) == need_rare:
            return tiers[Tier.commune], tiers.get(Tier.rare)
    return None, None
def qty(p, card_id):
    db.expire_all(); o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=card_id).first(); return o.quantity if o else 0
def setq(p, card_id, q):
    o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=card_id).first()
    if o is None: o = OwnedCard(user_id=U(p).id, card_id=card_id, quantity=q); db.add(o)
    else: o.quantity = q
    db.commit()
com, rare = card_of(Tier.commune)
url = "/cards/%s/upgrade-rare" % com.id

print("1) CONDITIONS")
ok(c.get(url).status_code == 401, "sans compte : 401")
setq("ana", com.id, 5); setq("ana", rare.id, 0) if qty("ana", rare.id) else None
i = c.get(url, headers=H["ana"]).json()
ok(i["eligible"] and not i["can"] and i["dupes"] == 4 and i["needed"] == 5 and "5 doublons" in i["reason"], "5 exemplaires = 4 doublons : pas encore assez")
ok(c.post(url, headers=H["ana"]).status_code == 400 and qty("ana", com.id) == 5, "échange refusé, rien n'est retiré")
ok(not c.get("/cards/%s/upgrade-rare" % rare.id, headers=H["ana"]).json()["eligible"], "une carte rare ne s'échange pas")
ok(not c.get(url, headers=H["bob"]).json()["eligible"], "une commune qu'on n'a pas : impossible")
lone, _ = card_of(Tier.commune, need_rare=False)
if lone is not None:
    setq("ana", lone.id, 10); ok(not c.get("/cards/%s/upgrade-rare" % lone.id, headers=H["ana"]).json()["eligible"], "personne sans carte rare : impossible")
ok(c.get("/cards/inconnue/upgrade-rare", headers=H["ana"]).status_code == 404, "carte inconnue : 404")

print("2) ÉCHANGE")
setq("ana", com.id, 12); CL.set_level(db, U("ana").id, com.id, 2); db.commit()
r = c.post(url, headers=H["ana"])
ok(r.status_code == 200 and r.json()["rare_card_id"] == rare.id and r.json()["rare_quantity"] == 1, "12 exemplaires : échange réussi, 1 rare reçue")
ok(qty("ana", com.id) == 7 and qty("ana", rare.id) == 1, "5 doublons consommés (12 → 7), la rare est dans la collection")
ok(CL.level_of(db, U("ana").id, com.id) == 2, "la commune garde son niveau")
r = c.post(url, headers=H["ana"]); ok(r.status_code == 200 and qty("ana", com.id) == 2 and qty("ana", rare.id) == 2, "deuxième échange : 7 → 2, la rare passe à 2 exemplaires")
ok(c.post(url, headers=H["ana"]).status_code == 400 and qty("ana", com.id) == 2, "plus assez de doublons : refusé, on garde toujours la commune")

print(); print("BILAN (doublons vers la rare) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
