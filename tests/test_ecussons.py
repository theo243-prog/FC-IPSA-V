"""
Test : écussons des clubs adverses (cartes GOLD de collection, poste ECUSSON). Création depuis l'administration (tout ou rien,
noms en double, image), type de carte, rareté gold, pas de note ni de niveau ni de secrète, interdits en 1v1, vendables au
marché, ignorés par les classements de joueurs, journal de l'administration. Lancé par tests/run_tests.py.
"""
from collections import Counter
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import game_logic as GL, card_levels as CL, weekly as WK, admin_tools
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
crest = lambda n: (db.expire_all(), db.query(Player).filter_by(name=n).first())[1]

print("1) CRÉATION DEPUIS L'ADMINISTRATION")
body = {"clubs": [{"name": "AS Saint-Étienne", "photo_url": "asse.webp"}, {"name": "  FC   Nantes ", "photo_url": ""}]}
ok(c.post("/admin/create-crests", json=body).status_code == 403, "sans clé admin : 403")
g0 = db.query(Card).filter_by(tier=Tier.gold).count()
r = c.post("/admin/create-crests", json=body, headers=A)
ok(r.status_code == 200 and [x["name"] for x in r.json()["crests_created"]] == ["AS Saint-Étienne", "FC Nantes"], "deux écussons créés (espaces en trop retirés) : %s" % r.json())
p = crest("AS Saint-Étienne"); n = crest("FC Nantes")
ok(p.poste == "ECUSSON" and GL.card_kind(p) == "ecusson" and p.photo_url == "/photos/asse.webp" and n.photo_url is None, "fiche de poste ECUSSON, image mise au bon format (/photos/asse.webp), image facultative")
ok([cd.tier for cd in p.cards] == [Tier.gold] and db.query(Card).filter_by(tier=Tier.gold).count() == g0 + 2, "une seule carte, en rareté gold")
for bad, why in (([{"name": "Lyon"}, {"name": "as saint-étienne"}], "nom déjà pris (sans tenir compte des majuscules)"),
                 ([{"name": "Lyon"}, {"name": "LYON"}], "nom en double dans la liste"),
                 ([{"name": "Lyon"}, {"name": "Mathis"}], "nom d'un joueur de l'effectif"),
                 ([{"name": "Lyon", "photo_url": "lyon"}], "image sans extension"),
                 ([{"name": "Lyon"}, {"name": "   "}], "nom vide"), ([], "liste vide")):
    r = c.post("/admin/create-crests", json={"clubs": bad}, headers=A)
    ok(r.status_code == 400 and crest("Lyon") is None, "refusé, rien n'est créé : %s (« %s »)" % (why, r.json().get("detail", "")[:60]))
ok(c.post("/admin/set-player-photo", json={"player_name": "FC Nantes", "photo_url": "nantes.png"}, headers=A).status_code == 200 and crest("FC Nantes").photo_url == "/photos/nantes.png", "l'image se change ensuite avec « Photo d'un joueur »")
ok(c.post("/admin/create-player", json={"name": "Faux club", "poste": "ECUSSON"}, headers=A).status_code == 400, "le poste ECUSSON est réservé (pas de création par « Créer un joueur »)")
ok([x["name"] for x in c.get("/admin/players", params={"kind": "ecusson"}, headers=A).json()] == ["AS Saint-Étienne", "FC Nantes"], "la liste de l'administration filtre les écussons")
ok("2 écusson(s) gold ajouté(s) : AS Saint-Étienne, FC Nantes" == admin_tools.summarize("/admin/create-crests", {"clubs": [{"name": "AS Saint-Étienne"}, {"name": "FC Nantes"}]}), "résumé dans le journal de l'administration")

print("2) UNE CARTE DE COLLECTION")
gold = p.cards[0]
ok(GL.get_display_note(p, "gold", gold) is None and not GL.has_secret_card(p), "ni note ni carte secrète")
ok(CL.ineligible_reason(gold) is not None and "écusson" in CL.ineligible_reason(gold), "pas de niveau (« %s »)" % CL.ineligible_reason(gold))
d = c.get("/players/AS Saint-Étienne/detail", params={"tier": "gold"}).json()
ok(d["poste"] == "ECUSSON" and d["photo_url"] == "/photos/asse.webp" and d.get("display_note") is None, "fiche publique : poste ECUSSON, image, pas de note")
t = c.post("/auth/register", json={"pseudo": "ana", "password": "test1234"}).json()["token"]; H = {"Authorization": "Bearer " + t}
u = db.query(User).filter_by(pseudo="ana").first(); u.credits = 100
card = lambda nm, tr="commune": db.query(Card).join(Player).filter(Player.name == nm, Card.tier == Tier(tr)).first()
CORE = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
for nm, _ in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(nm).id, quantity=1))
db.add(OwnedCard(user_id=u.id, card_id=gold.id, quantity=2)); db.commit()
slots = [{"card_id": card(nm).id, "slot_category": s} for nm, s in CORE[:4]] + [{"card_id": gold.id, "slot_category": "ATT"}]
r = c.post("/duel/proposals", json={"formation": "1-2-1", "tactic": "pressing", "stake": 1, "slots": slots}, headers=H)
ok(r.status_code == 400 and "collection" in r.json()["detail"], "interdit sur le terrain en 1v1 (« %s »)" % r.json().get("detail"))
col = {x["id"]: x for x in c.get("/collection", headers=H).json()["cards"]} if isinstance(c.get("/collection", headers=H).json(), dict) else {x["id"]: x for x in c.get("/collection", headers=H).json()}
ok(col[gold.id]["quantity"] == 2 and col[gold.id]["tier"] == "gold" and col[gold.id]["poste"] == "ECUSSON", "visible dans la collection, parmi les gold")
r = c.post("/market/list", json={"card_id": gold.id, "price": 7}, headers=H)
ok(r.status_code == 200, "se met en vente au marché comme une gold")
ok(GL.DUPLICATE_SELL_VALUE["gold"] == 5, "un doublon se revend comme une gold (5 crédits)")

print("3) IGNORÉ PAR LES CLASSEMENTS DE JOUEURS")
players = {pl.name: pl for pl in db.query(Player).all()}
ok([pl.name for pl, _ in WK._ranked(Counter({"AS Saint-Étienne": 9, "Lucas": 1}), players)] == ["Lucas"], "cartes spéciales du vendredi : un écusson ne gagne jamais")
counts = GL.tier_card_counts(db)
ok(counts["gold"] >= 2, "il compte dans les cartes gold des packs (%d gold)" % counts["gold"])
print("BILAN (écussons) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
