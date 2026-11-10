"""
Test : informations sur les cartes. Prix moyen et prix le plus haut des ventes d'une carte (fiche d'une carte de SA collection) ;
complétion du jeu (cartes + niveaux : 100 % = toutes les cartes et toutes celles qui évoluent au niveau 5), sur le profil et le classement.
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import card_levels as CL, offers as OF, club_auctions as CA
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
card = lambda n, t="commune": db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("ana", "bob")}
give = lambda p, k, q=1: (db.add(OwnedCard(user_id=U(p).id, card_id=k.id, quantity=q)), db.commit())

print("1) PRIX MOYEN ET PRIX MAX")
hugo, lucas = card("Hugo"), card("Lucas", "rare")
give("ana", hugo); give("ana", lucas)
r = c.get("/cards/%s/price-stats" % hugo.id, headers=H["ana"]).json()
ok(r["sales"] == 0 and r["avg_price"] is None and r["max_price"] is None, "carte jamais vendue : aucun prix")
for kind, price in (("annonce", 10), ("offre", 25), ("enchère", 40)):
    db.add(OF.Trade(kind=kind, seller_id=U("bob").id, buyer_id=U("ana").id, seller_pseudo="bob", buyer_pseudo="ana", card_id=hugo.id, card_tier="commune", price=price))
db.add(OF.Trade(kind="annonce", seller_id=U("bob").id, buyer_id=U("ana").id, seller_pseudo="bob", buyer_pseudo="ana", card_id=lucas.id, card_tier="rare", price=999))
db.add(CA.ClubAuctionLot(auction_id="x1", batch_id=1, series_id=1, number=2, card_id=hugo.id, base_end=__import__("datetime").datetime(2026, 11, 1), status="won", price=60))
db.add(CA.ClubAuctionLot(auction_id="x2", batch_id=1, series_id=1, number=3, card_id=hugo.id, base_end=__import__("datetime").datetime(2026, 11, 1), status="unsold", price=None))
db.commit()
r = c.get("/cards/%s/price-stats" % hugo.id, headers=H["ana"]).json()
ok(r["sales"] == 4 and r["avg_price"] == 34 and r["max_price"] == 60, "annonces, offres, enchères et enchères du club gagnées : 4 ventes, moyenne 34, max 60 (%s)" % r)
ok(set(r) == {"card_id", "sales", "avg_price", "max_price"}, "ni pseudo ni date : seulement les prix")
ok(c.get("/cards/%s/price-stats" % hugo.id, headers=H["bob"]).status_code == 404, "une carte qui n'est pas dans sa collection : refusé")
ok(c.get("/cards/%s/price-stats" % hugo.id).status_code == 401, "il faut être connecté")

print("2) COMPLÉTION DU JEU")
total = db.query(Card).filter(Card.tier.notin_([Tier.saison, Tier.numerotee])).count()
g = CL.game_completion(db, [U("ana").id, U("bob").id])
ok(abs(g[U("ana").id] - round(100 * (0.5 + 0.5) / total, 1)) < 1e-9 and g[U("bob").id] == 0.0, "commune et rare sans niveau : 0,5 point chacune ; rien : 0 %")
CL.set_level(db, U("ana").id, hugo.id, 5); CL.set_level(db, U("ana").id, lucas.id, 2); db.commit()
gold = db.query(Card).filter(Card.tier == Tier.gold).first()
if gold is not None: give("ana", gold)
g = CL.game_completion(db, [U("ana").id])[U("ana").id]
pts = 1.0 + 0.7 + (1.0 if gold is not None else 0)
ok(abs(g - round(100 * pts / total, 1)) < 1e-9, "niveau 5 = 1 point, niveau 2 = 0,7 point, une carte qui n'évolue pas = 1 point (%.1f %%)" % g)
lb = {x["pseudo"]: x for x in c.get("/leaderboard").json()}
ok(lb["ana"]["game_completion_pct"] == g and lb["ana"]["completion_pct"] >= g, "classement : complétion du jeu à côté de la collection")
pr = c.get("/users/ana/profile").json()
ok(pr["game_completion_pct"] == g, "profil : complétion du jeu")
all_ids = [k.id for k in db.query(Card).filter(Card.tier.notin_([Tier.saison, Tier.numerotee])).all()]
for k in db.query(Card).filter(Card.id.in_(all_ids)).all():
    o = db.query(OwnedCard).filter_by(user_id=U("bob").id, card_id=k.id).first()
    if o is None: db.add(OwnedCard(user_id=U("bob").id, card_id=k.id, quantity=1))
    if CL.group_of(k) is not None and k.player and __import__("app.game_logic", fromlist=["x"]).card_kind(k.player) == "joueur":
        CL.set_level(db, U("bob").id, k.id, 5)
db.commit()
ok(CL.game_completion(db, [U("bob").id])[U("bob").id] == 100.0, "toutes les cartes, toutes celles qui évoluent au niveau 5 : 100 %")

print("BILAN (infos des cartes) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
