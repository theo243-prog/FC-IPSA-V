"""
Test : packs joueur du shop (4 packs « joueur rare » à 75 crédits et 1 pack « joueur premium » par jour, les mêmes pour tout le monde,
3 cartes dont la carte annoncée garantie, achat sans limite, ouverture dans l'onglet Packs, compte dans l'objectif du club,
remboursement si la carte est supprimée). Lancé par tests/run_tests.py.
"""
from datetime import timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import player_packs as PP, game_logic as GL, battlepass as BP, seasons
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p, credits):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit()
    return {"Authorization": "Bearer " + t}
def player(name): return db.query(Player).filter_by(name=name).first()
def add_card(name, tier):
    card = Card(player_id=player(name).id, tier=Tier(tier), vitesse=80, tir=80); db.add(card); db.commit(); return card
def qty(p, card_id):
    o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=card_id).first(); return o.quantity if o else 0
H = {"riche": mk("riche", 5000), "pauvre": mk("pauvre", 50)}
gb = db.query(Player).filter_by(poste="GB").first(); mil = db.query(Player).filter(Player.poste != "GB").first()
EPIC = add_card(mil.name, "epique"); SPEC_GB = add_card(gb.name, "speciale")
real_today = GL.today_paris

print("1) LES OFFRES DU JOUR")
s = c.get("/shop/player-packs", headers=H["riche"]).json()
rares = [o for o in s["offers"] if o["kind"] == "rare"]; prem = [o for o in s["offers"] if o["kind"] == "premium"]
ok(len(rares) == 4 and all(o["tier"] == "rare" and o["price"] == 75 for o in rares) and len({o["player_name"] for o in rares}) == 4, "4 packs « joueur rare » à 75 crédits, 4 joueurs différents")
ok(all(GL.card_kind(db.get(Card, o["card_id"]).player) == "joueur" for o in s["offers"]), "seulement de vrais joueurs (ni fan, ni mascotte, ni équipement)")
ok(len(prem) == 1 and prem[0]["card_id"] == EPIC.id and prem[0]["price"] == 300, "1 pack premium : l'épique (seule carte possible ; la spéciale du gardien est exclue) à 300 crédits")
s2 = c.get("/shop/player-packs", headers=H["pauvre"]).json()
ok([o["id"] for o in s2["offers"]] == [o["id"] for o in s["offers"]], "les mêmes offres pour tout le monde toute la journée")
cands = PP._premium_candidates(db)
ok(set(cands) == {"epique"} and SPEC_GB.id not in [x.id for v in cands.values() for x in v], "candidats premium : épiques et spéciales de vrais joueurs (pas la spéciale du gardien), éditions en cours")
SPEC = add_card(mil.name, "speciale"); cands = PP._premium_candidates(db)
ok(set(cands) == {"epique", "speciale"} and PP.PREMIUM_PRICES == {"edition": 200, "epique": 300, "speciale": 400} and not any(x.tier == Tier.legendaire for v in cands.values() for x in v), "prix selon la rareté : édition 200, épique 300, spéciale 400 ; jamais de légendaire")

print("2) ACHAT (SANS LIMITE)")
offer = rares[0]
r = c.post("/shop/player-packs/buy", json={"offer_id": offer["id"]}, headers=H["pauvre"])
ok(r.status_code == 400 and "crédits" in r.json()["detail"] and U("pauvre").credits == 50, "pas assez de crédits : refusé, rien n'est retiré")
for _ in range(3):
    r = c.post("/shop/player-packs/buy", json={"offer_id": offer["id"]}, headers=H["riche"])
ok(r.status_code == 200 and U("riche").credits == 5000 - 3 * 75, "3 fois le même pack : 3 × 75 crédits retirés")
me = c.get("/me", headers=H["riche"]).json()
ok(len(me["player_packs"]) == 3 and all(p["card_id"] == offer["card_id"] for p in me["player_packs"]), "/me : 3 packs joueur à ouvrir, avec la carte garantie")
ok(c.post("/shop/player-packs/buy", json={"offer_id": "inconnu"}, headers=H["riche"]).status_code == 400, "offre inconnue : refusée")

print("3) OUVERTURE DANS L'ONGLET PACKS")
key = seasons.key_of(BP.now_paris()); club0 = (db.get(BP.ClubGoal, key).packs if db.get(BP.ClubGoal, key) else 0)
before = qty("riche", offer["card_id"]); pid = me["player_packs"][0]["id"]
r = c.post("/pack/open", json={"pack_type": "joueur", "player_pack_id": pid}, headers=H["riche"]).json()
ids = [x["id"] for x in r["cards_won"]]
ok(len(ids) == 3 and len(set(ids)) == 3 and offer["card_id"] in ids and r["pack_type"] == "joueur" and 1 <= r["credits_won"] <= 5, "3 cartes différentes, dont la rare garantie, et 1 à 5 crédits")
ok(qty("riche", offer["card_id"]) == before + 1 and len(c.get("/me", headers=H["riche"]).json()["player_packs"]) == 2, "la carte garantie est dans la collection ; il reste 2 packs")
db.expire_all(); ok(db.get(BP.ClubGoal, key).packs == club0 + 1, "le pack compte dans l'objectif du club (packs ouverts du mois)")
ok(c.post("/pack/open", json={"pack_type": "joueur", "player_pack_id": pid}, headers=H["riche"]).status_code == 400, "le même pack ne s'ouvre pas deux fois")
ok(c.post("/pack/open", json={"pack_type": "joueur", "player_pack_id": me["player_packs"][1]["id"]}, headers=H["pauvre"]).status_code == 400, "on n'ouvre pas le pack d'un autre joueur")
got = set()
for _ in range(30):
    got |= {x["tier"] for x in c.post("/pack/open", json={"pack_type": "joueur", "player_pack_id": c.post("/shop/player-packs/buy", json={"offer_id": offer["id"]}, headers=H["riche"]).json()["pack_id"]}, headers=H["riche"]).json()["cards_won"]}
ok("commune" in got, "les 2 autres cartes suivent les chances du pack classique (%s)" % sorted(got))

print("4) LE LENDEMAIN")
GL.today_paris = lambda: real_today() + timedelta(days=1)
r = c.post("/shop/player-packs/buy", json={"offer_id": offer["id"]}, headers=H["riche"])
ok(r.status_code == 400 and "minuit" in r.json()["detail"], "l'offre d'hier n'est plus en vente")
s3 = c.get("/shop/player-packs", headers=H["riche"]).json()
ok(len(s3["offers"]) == 5 and s3["day"] != s["day"] and not set(o["id"] for o in s3["offers"]) & set(o["id"] for o in s["offers"]), "de nouvelles offres (4 rares + 1 premium)")
ok(len(s3["owned"]) == 2, "les packs achetés la veille restent à ouvrir")
GL.today_paris = real_today

print("5) CARTE OU COMPTE SUPPRIMÉ")
cr = U("riche").credits; PP.on_cards_deleted(db, [offer["card_id"]]); db.commit()
ok(U("riche").credits == cr + 2 * 75 and c.get("/me", headers=H["riche"]).json()["player_packs"] == [], "carte supprimée : les 2 packs non ouverts sont remboursés (2 × 75)")
c.post("/shop/player-packs/buy", json={"offer_id": prem[0]["id"]}, headers=H["riche"]); PP.on_user_deleted(db, U("riche").id); db.commit()
ok(db.query(PP.OwnedPlayerPack).filter_by(user_id=U("riche").id).count() == 0, "compte supprimé : ses packs joueur sont effacés")

print(); print("BILAN (packs joueur) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
