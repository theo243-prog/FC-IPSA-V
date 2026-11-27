"""
Test : le poppers du shop (250 crédits, un achat par jour au plus, gardé en réserve ; il remet une personne à 100 % de forme en 1v1).
Lancé par tests/run_tests.py.
"""
from datetime import timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import fatigue, poppers as P, game_logic, credit_log
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
card = lambda n, t=Tier.commune: db.query(Card).join(Player).filter(Player.name == n, Card.tier == t).first()
def mk(p, credits=1000):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits
    for cd in (card("Lucas"), card("Lucas", Tier.rare), card("Hugo")):
        if cd is not None:
            db.add(OwnedCard(user_id=u.id, card_id=cd.id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {"popa": mk("popa"), "pauvre": mk("popauvre", 100)}
uid = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
forms = lambda p: (db.expire_all(), fatigue.forms_for(db, uid(p).id))[1]

print("1) ACHAT : 250 CRÉDITS, UN PAR JOUR")
g = c.get("/shop/poppers", headers=H["popa"]).json()
ok(g["price"] == 250 and g["left"] == 0 and g["can_buy"], "au départ : 250 crédits, rien en réserve, achat possible (%s)" % g)
cr0 = uid("popa").credits
r = c.post("/shop/poppers/buy", headers=H["popa"])
ok(r.status_code == 200 and r.json()["left"] == 1 and not r.json()["can_buy"] and uid("popa").credits == cr0 - 250, "achat : -250 crédits, 1 en réserve")
r = c.post("/shop/poppers/buy", headers=H["popa"])
ok(r.status_code == 400 and "aujourd'hui" in r.json()["detail"] and uid("popa").credits == cr0 - 250, "2e achat le même jour : refusé, rien retiré (%s)" % r.json().get("detail"))
r = c.post("/shop/poppers/buy", headers=H["pauvre"])
ok(r.status_code == 400 and "250" in r.json()["detail"] and uid("popauvre").credits == 100, "pas assez de crédits : refus clair, rien retiré")
ok(c.get("/shop/poppers", headers=H["pauvre"]).json()["can_buy"], "un achat refusé ne compte pas comme l'achat du jour")
me = c.get("/me", headers=H["popa"]).json()["poppers"]
ok(me["left"] == 1 and me["bought_today"] == 1, "/me renvoie poppers (%s)" % me)
lg = credit_log.CreditLog if hasattr(credit_log, "CreditLog") else None
if lg is not None:
    db.expire_all(); ok(db.query(lg).filter_by(user_id=uid("popa").id, label="Poppers").count() == 1, "historique des crédits : ligne « Poppers »")

print("2) UTILISATION")
r = c.post("/shop/poppers/use", json={"card_id": card("Lucas").id}, headers=H["popa"])
ok(r.status_code == 400 and "100 %" in r.json()["detail"] and P.left(db, uid("popa").id) == 1, "carte déjà à 100 % : refus, le poppers est gardé")
fatigue.record_match(db, uid("popa").id, [card("Lucas").id, card("Hugo").id]); db.commit()
for row in db.query(fatigue.PersonFatigue).filter_by(user_id=uid("popa").id).all():
    row.debt = 1000                                       # 10 % de forme perdue
db.commit()
f = forms("popa")
ok(f.get(card("Lucas").id, 1) < 0.95 and f.get(card("Hugo").id, 1) < 0.95, "Lucas et Hugo sont fatigués (%s)" % sorted(round(v, 3) for v in f.values()))
r = c.post("/shop/poppers/use", json={"card_id": card("Lucas").id}, headers=H["popa"])
f = forms("popa")
ok(r.status_code == 200 and r.json()["player_name"] == "Lucas" and card("Lucas").id not in f, "poppers sur Lucas : 100 % de forme")
if card("Lucas", Tier.rare) is not None:
    ok(card("Lucas", Tier.rare).id not in f, "toutes les cartes de Lucas (la rare aussi) repassent à 100 %")
ok(f.get(card("Hugo").id, 1) < 0.96, "Hugo, lui, reste fatigué")
ok(P.left(db, uid("popa").id) == 0, "le poppers est consommé")
r = c.post("/shop/poppers/use", json={"card_id": card("Hugo").id}, headers=H["popa"])
ok(r.status_code == 400 and "pas de poppers" in r.json()["detail"], "sans poppers en réserve : refus")
other = db.query(Card).join(Player).filter(Player.name == "Nathan", Card.tier == Tier.commune).first()
ok(c.post("/shop/poppers/use", json={"card_id": other.id}, headers=H["popa"]).status_code == 404, "carte qui n'est pas dans sa collection : 404")

print("3) LE LENDEMAIN")
real = game_logic.today_paris
game_logic.today_paris = lambda now_utc=None: real(now_utc) + timedelta(days=1)
r = c.post("/shop/poppers/buy", headers=H["popa"])
ok(r.status_code == 200 and r.json()["left"] == 1, "le lendemain, on peut en racheter un")
game_logic.today_paris = lambda now_utc=None: real(now_utc) + timedelta(days=2)
c.post("/shop/poppers/buy", headers=H["popa"])
ok(P.left(db, uid("popa").id) == 2, "ils s'accumulent dans la réserve (un par jour)")
game_logic.today_paris = real
ok(c.post("/shop/poppers/buy").status_code == 401, "compte connecté obligatoire")

print()
print("RÉSULTAT :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
