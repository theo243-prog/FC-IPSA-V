"""
Test : cartes numérotées à tirage limité (rareté « numerotee », type « numerotee »). Création d'une série (total fixe, exemplaires
en réserve), attribution dans l'ordre ou d'un numéro précis, refus au-delà du total ou d'un numéro pris, award-first (ordre de
création, exclusions, simulation), jamais dans un pack, non jouable, pas de niveau, ni stats hebdomadaires, ni fusion, ni échange,
vente au marché et enchère (numéro conservé), suppression d'un compte (réserve, ventes annulées), beaucoup de séries d'un coup,
403 sans clé admin. Lancé par tests/run_tests.py.
"""
import time
from collections import Counter
from datetime import timedelta
from urllib.parse import quote

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import numbered as NB, game_logic as GL, card_levels as CL, weekly as WK, auctions as AU, pass_catalog as PC, swaps
from app.models import User, Card, Player, OwnedCard, Tier, Listing
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p, credits=500):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("testadmin", "ana", "bob", "cyr", "dan", "eve")}
copy = lambda s, n: (db.expire_all(), db.query(NB.NumberedCopy).filter_by(series_id=s, number=n).first())[1]
owner = lambda cid: [db.get(User, o.user_id).pseudo for o in db.query(OwnedCard).filter_by(card_id=cid).all() if o.quantity > 0]

print("1) CRÉER UNE SÉRIE")
body = {"title": "Édition Noire", "subject": "Lucas", "total": 5, "description": "Test"}
ok(c.post("/admin/series-create", json=body).status_code == 403 and c.get("/admin/series").status_code == 403, "sans clé admin : 403")
r = c.post("/admin/series-create", json=body, headers=A); se = r.json()["series"]; SID = se["id"]
ok(r.status_code == 200 and se["total"] == 5 and se["attributed"] == 0 and se["reserve"] == 5 and all(x["where"] == "réserve du club" for x in se["copies"]), "5 exemplaires, tous dans la réserve du club")
names = [db.get(Card, x["card_id"]).player.name for x in se["copies"]]
ok(names[0] == "Édition Noire — Lucas · n° 1/5" and names[-1] == "Édition Noire — Lucas · n° 5/5", "noms « Titre — Sujet · n° 1/5 »")
cd1 = db.get(Card, se["copies"][0]["card_id"])
ok(cd1.tier == Tier.numerotee and GL.card_kind(cd1.player) == "numerotee" and not db.query(OwnedCard).filter(OwnedCard.card_id.in_([x["card_id"] for x in se["copies"]])).count(), "rareté et type « numerotee », aucun propriétaire")
ok(cd1.player.photo_url == db.query(Player).filter_by(name="Lucas").first().photo_url, "image par défaut : celle du sujet")
ok(c.post("/admin/series-create", json=body, headers=A).status_code == 400, "même série deux fois : refusée")
ok(c.post("/admin/series-create", json={**body, "subject": "X", "total": 0}, headers=A).status_code == 422, "total à 0 : refusé")
ok("numerotee" in GL.TIER_ORDER and "numerotee" in __import__("app.schema_upgrades", fromlist=["x"]).NEW_TIER_VALUES, "rareté ajoutée à TIER_ORDER et à NEW_TIER_VALUES (PostgreSQL)")

print("2) ATTRIBUER")
r = c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "ana"}, headers=A).json()
ok(r["number"] == 1 and owner(copy(SID, 1).card_id) == ["ana"], "premier exemplaire : n° 1 à ana")
r = c.post("/admin/series-mint", json={"series": "Édition Noire — Lucas", "pseudo": "bob"}, headers=A).json()
ok(r["number"] == 2, "ensuite le n° 2 (série désignée par son nom)")
r = c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "cyr", "number": 5}, headers=A).json()
ok(r["number"] == 5 and copy(SID, 5).status == "attribue", "numéro précis : n° 5 à cyr")
r = c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "dan", "number": 5}, headers=A)
ok(r.status_code == 400 and "déjà attribué" in r.json()["detail"], "n° déjà pris : refusé")
r = c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "dan", "number": 6}, headers=A)
ok(r.status_code == 400 and "n'existe pas" in r.json()["detail"], "au-delà du total : refusé")
c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "dan"}, headers=A); c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "dan"}, headers=A)
r = c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "eve"}, headers=A)
ok(copy(SID, 3).status == copy(SID, 4).status == "attribue" and r.status_code == 400 and "épuisée" in r.json()["detail"], "n° 3 et 4 (les libres), puis série épuisée : il n'en existe jamais d'autre")
pub = c.get("/series/%d" % SID).json()
ok(pub["attributed"] == 5 and [x["holder"] for x in pub["copies"]] == ["ana", "bob", "dan", "dan", "cyr"], "fiche publique de la série : « 5 / 5 », détenteurs avec leur numéro")
ok(c.get("/cards/%s/series" % copy(SID, 2).card_id).json()["number"] == 2 and c.get("/cards/%s/series" % db.query(Card).first().id).status_code == 404, "la série d'une carte (404 pour une carte normale)")

print("3) PREMIERS INSCRITS (award-first)")
s2 = c.post("/admin/series-create", json={"title": "Pionniers", "subject": "Club", "total": 10}, headers=A).json()["series"]["id"]
dry = c.post("/admin/series-award-first", json={"series": str(s2), "count": 3, "exclude": ["testadmin"], "dry_run": True}, headers=A).json()
ok(dry["status"] == "dry_run" and [x["pseudo"] for x in dry["plan"]] == ["ana", "bob", "cyr"] and copy(s2, 1).status == "reserve", "simulation : les 3 premiers comptes créés sans testadmin, rien d'attribué")
r = c.post("/admin/series-award-first", json={"series": str(s2), "count": 3, "exclude": ["testadmin"], "dry_run": False}, headers=A).json()
ok(r["status"] == "ok" and owner(copy(s2, 1).card_id) == ["ana"] and owner(copy(s2, 3).card_id) == ["cyr"], "n° 1 à ana, n° 3 à cyr (ordre de création)")
r = c.post("/admin/series-award-first", json={"series": str(s2), "count": 4, "dry_run": True}, headers=A)
ok(r.status_code == 400 and "déjà attribués" in r.json()["detail"], "refusé si un numéro est déjà attribué")
ok(c.post("/admin/series-award-first", json={"series": str(s2), "count": 11, "dry_run": True}, headers=A).status_code == 400, "refusé au-delà du total")

print("4) JAMAIS DANS UN PACK, NON JOUABLE, HORS STATS")
ok(all("numerotee" not in (spec.get("weights") or GL.TIER_WEIGHTS) for spec in GL.PACK_TYPES.values()), "absente des poids de tous les packs")
ok(all(t.get("edition") != "numerotee" for t in PC.THEMES.values()), "aucun pack d'édition du Pass ne tire des numérotées")
lucas = db.query(Player).filter_by(name="Lucas").first()
for t in ("epique", "legendaire", "gold"):                 # pour que les packs épique, légendaire et ultra existent aussi
    db.add(Card(player_id=lucas.id, tier=Tier(t), vitesse=0, tir=0))
db.commit(); drawn = Counter()
for kind in ("classique", "match", "ultra", "rare", "epique", "legendaire"):
    c.post("/admin/grant-packs", json={"pseudo": "eve", "count": 15, "pack_type": kind}, headers=A)
for kind in ("classique", "match", "ultra", "rare", "epique", "legendaire"):
    for _ in range(15):
        r = c.post("/pack/open", json={"pack_type": kind}, headers=H["eve"])
        if r.status_code == 200: drawn.update(x.get("tier") or x.get("card", {}).get("tier") for x in r.json().get("cards_won", []))
ok(sum(drawn.values()) > 100 and drawn["numerotee"] == 0, "aucune numérotée dans %d cartes tirées (tous les types de packs)" % sum(drawn.values()))
ana_num = copy(SID, 1).card_id; mine = lambda nm: db.query(Card).join(Player).filter(Player.name == nm, Card.tier == Tier.commune).first()
CORE = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC")]
for nm, _ in CORE: db.add(OwnedCard(user_id=U("ana").id, card_id=mine(nm).id, quantity=1))
db.commit()
slots = [{"card_id": mine(nm).id, "slot_category": s} for nm, s in CORE] + [{"card_id": ana_num, "slot_category": "ATT"}]
r = c.post("/duel/proposals", json={"formation": "1-2-1", "tactic": "pressing", "stake": 1, "slots": slots}, headers=H["ana"])
ok(r.status_code == 400 and "collection" in r.json()["detail"], "refusée sur le terrain en 1v1 (même contrôle pour le tournoi et le défi du club)")
ok(CL.ineligible_reason(db.get(Card, ana_num)) is not None and GL.get_display_note(db.get(Card, ana_num).player, "numerotee") is None, "pas de niveau, pas de note")
players = {p.name: p for p in db.query(Player).all()}
ok(WK._ranked(Counter({db.get(Card, ana_num).player.name: 9, "Lucas": 1}), players)[0][0].name == "Lucas" and "numerotee" not in __import__("app.club", fromlist=["x"]).NEVER_PLAYED ^ {"numerotee"}, "ignorée des cartes spéciales hebdomadaires ; jamais dans l'équipe du club")
ok(not GL.has_secret_card(db.get(Card, ana_num).player) and db.get(Card, ana_num).player_id != players["Lucas"].id, "pas de fusion des secrètes : fiche distincte du joueur Lucas")
ok(not swaps._tradeable(db.get(Card, ana_num)), "jamais échangeable")
col = c.get("/collection", headers=H["ana"]).json(); col = col["cards"] if isinstance(col, dict) else col
nums = [x for x in col if x["tier"] == "numerotee"]
ok(len(nums) == 2 and all(x["quantity"] == 1 for x in nums), "collection d'ana : seulement ses 2 exemplaires, aucune case « ? » pour les autres")
ok(c.get("/players/" + quote(db.get(Card, ana_num).player.name, safe="") + "/detail", params={"tier": "numerotee"}).json()["poste"] == "NUMEROTEE", "la fiche s'ouvre malgré le « / » du numéro")

print("5) MARCHÉ ET ENCHÈRES")
r = c.post("/market/list", json={"card_id": ana_num, "price": 30}, headers=H["ana"])
ok(r.status_code == 200 and c.get("/series/%d" % SID).json()["copies"][0]["where"] == "marché", "mise en vente : la série montre « marché »")
ok(c.post("/admin/series-reclaim", json={"series": str(SID), "number": 1}, headers=A).status_code == 400, "un exemplaire en vente ne peut pas être repris")
c.post("/market/buy/%s" % r.json()["id"], headers=H["eve"])
ok(owner(ana_num) == ["eve"] and copy(SID, 1).status == "attribue", "eve l'achète : n° 1 conservé")
hist = c.get("/market/history").json(); hist = hist if isinstance(hist, list) else hist.get("items", [])
ok(any("n° 1/5" in str(h) for h in hist), "l'historique du marché montre le numéro")
aid = c.post("/auctions", json={"card_id": ana_num, "start_price": 10, "minutes": 15}, headers=H["eve"]).json()["id"]
c.post("/auctions/%s/bid" % aid, json={"amount": 10}, headers=H["bob"])
db.expire_all(); a = db.get(AU.Auction, aid); a.ends_at = AU._now() - timedelta(minutes=1); db.commit(); AU.settle_due(db)
ok(owner(ana_num) == ["bob"] and c.get("/cards/%s/series" % ana_num).json()["number"] == 1, "enchère : bob gagne le n° 1")

print("6) SUPPRESSION D'UN COMPTE")
dan_cards = [copy(SID, 3).card_id, copy(SID, 4).card_id]
lid = c.post("/market/list", json={"card_id": dan_cards[0], "price": 9}, headers=H["dan"]).json()["id"]
aid = c.post("/auctions", json={"card_id": dan_cards[1], "start_price": 5, "minutes": 15}, headers=H["dan"]).json()["id"]
c.post("/auctions/%s/bid" % aid, json={"amount": 5}, headers=H["cyr"]); cyr_credits = U("cyr").credits
r = c.post("/admin/delete-user", json={"pseudo": "dan"}, headers=A)
ok(r.status_code == 200 and owner(dan_cards[0]) == ["testadmin"] and owner(dan_cards[1]) == ["testadmin"], "dan supprimé : ses exemplaires (en vente et aux enchères) passent à testadmin")
ok(db.get(Listing, lid) is None and db.get(AU.Auction, aid) is None and U("cyr").credits == cyr_credits + 5, "vente et enchère annulées, le meilleur enchérisseur remboursé")
NB.RESERVE_PSEUDO = "personne-ici"
r = c.post("/admin/delete-user", json={"pseudo": "cyr"}, headers=A)
ok(r.status_code == 400 and "compte de réserve" in r.json()["detail"] and U("cyr") is not None, "compte de réserve absent : suppression refusée, rien n'est effacé")
NB.RESERVE_PSEUDO = "testadmin"
r = c.post("/admin/delete-user", json={"pseudo": "testadmin"}, headers=A)
ok(r.status_code == 400 and U("testadmin") is not None, "le compte de réserve ne peut pas être supprimé tant qu'il détient des exemplaires")
ok(c.post("/admin/series-reclaim", json={"series": str(SID), "number": 3}, headers=A).json()["taken_from"] == ["testadmin"] and copy(SID, 3).status == "reserve", "series-reclaim : le n° 3 revient dans la réserve du club")
ok(c.post("/admin/series-mint", json={"series": str(SID), "pseudo": "eve"}, headers=A).json()["number"] == 3, "… et peut être remis en circulation")

print("7) BEAUCOUP DE SÉRIES D'UN COUP")
t0 = time.time()
for i in range(40):
    NB.create_series(db, "Édition Noire", "Perso %02d" % i, 22)
db.commit(); dt = time.time() - t0
ok(db.query(NB.NumberedCopy).count() >= 40 * 22 and dt < 20, "40 séries de 22 (880 exemplaires) en %.1f s" % dt)
t0 = time.time(); r = c.get("/collection", headers=H["ana"]); dt2 = time.time() - t0
ok(r.status_code == 200 and dt2 < 5, "la collection reste rapide (%.2f s) : les exemplaires non possédés ne sont pas envoyés" % dt2)
lb = c.get("/leaderboard").json()
ok(isinstance(lb, (list, dict)), "le classement des collections ignore les numérotées (pourcentage inchangé)")
print("8) IMAGE D'UNE SÉRIE")
photos = lambda sid: (db.expire_all(), sorted({db.get(Card, cp.card_id).player.photo_url or "" for cp in db.query(NB.NumberedCopy).filter_by(series_id=sid).all()}))[1]
ok(c.post("/admin/series-photo", json={"series": str(SID), "photo_url": "x.webp"}).status_code == 403, "sans clé admin : 403")
r = c.post("/admin/series-photo", json={"series": "Édition Noire — Lucas", "photo_url": "leo-noire.webp"}, headers=A).json()
ok(r["copies"] == 5 and r["photo_url"] == "/photos/leo-noire.webp" and photos(SID) == ["/photos/leo-noire.webp"] and db.get(NB.NumberedSeries, SID).photo_url == "/photos/leo-noire.webp", "une image pour toute la série : ses 5 exemplaires d'un coup")
cd = db.get(Card, copy(SID, 2).card_id)
ok(c.get("/series/%d" % SID).json()["photo_url"] == "/photos/leo-noire.webp" and __import__("app.main", fromlist=["x"]).card_out(cd)["player_photo_url"] == "/photos/leo-noire.webp", "la carte affichée prend la nouvelle image")
ok(c.post("/admin/series-photo", json={"series": str(SID), "photo_url": "leo"}, headers=A).status_code == 400, "nom d'image incomplet : refusé")
c.post("/admin/set-player-photo", json={"player_name": "Lucas", "photo_url": "/photos/lucas.webp"}, headers=A)
r = c.post("/admin/series-photo", json={"series": str(SID), "from_subject": True}, headers=A).json()
ok(r["source"] == "photo de Lucas" and photos(SID) == ["/photos/lucas.webp"], "reprendre la photo actuelle du joueur")
ok(c.post("/admin/series-photo", json={"series": "Pionniers — Club"}, headers=A).status_code == 400, "sujet qui n'est pas une personne, sans image : refusé")
c.post("/admin/set-player-photo", json={"player_name": "Lucas", "photo_url": "/photos/lucas-2.webp"}, headers=A)
dry = c.post("/admin/series-photo-sync", json={"title": "Édition Noire", "dry_run": True}, headers=A).json()
ok(dry["status"] == "dry_run" and [x["after"] for x in dry["changed"] if x["series"] == "Édition Noire — Lucas"] == ["/photos/lucas-2.webp"] and photos(SID) == ["/photos/lucas.webp"], "synchronisation, aperçu : la série de Lucas changerait, rien n'est modifié")
r = c.post("/admin/series-photo-sync", json={"title": "Édition Noire", "dry_run": False}, headers=A).json()
ok(r["status"] == "ok" and photos(SID) == ["/photos/lucas-2.webp"], "synchronisation : la série reprend la nouvelle photo du joueur")
ok(c.post("/admin/series-photo-sync", json={"title": "Édition Noire", "dry_run": True}, headers=A).json()["changed"] == [], "relancer : plus rien à changer")
r = c.post("/admin/series-photo-sync", json={"title": "", "dry_run": True}, headers=A).json()
ok("Pionniers — Club" in r["unchanged_not_a_person"], "titre vide : toutes les séries ; un sujet qui n'est pas une personne n'est pas touché")
c.post("/admin/set-player-photo", json={"player_name": "Lucas", "photo_url": ""}, headers=A)
r = c.post("/admin/series-photo-sync", json={"dry_run": False}, headers=A).json()
ok("Édition Noire — Lucas" in r["unchanged_no_photo"] and photos(SID) == ["/photos/lucas-2.webp"], "un joueur sans photo n'efface pas l'image de sa série")
print("BILAN (cartes numérotées) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
