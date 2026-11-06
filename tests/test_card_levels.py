"""
Test : niveaux de cartes (1 à 5, +1 de note par niveau). Cartes éligibles, doublons requis (jamais détruits), coûts, limite de 2 par jour,
effet en match (avant le malus hors poste et le capitaine, pour les deux équipes), niveau qui suit la carte (annonce, enchère, offre
d'achat), meilleur niveau chez l'acheteur, doublons vendus / échangés / fusionnés sans toucher au niveau, nettoyage. Lancé par tests/run_tests.py.
"""
from datetime import timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import card_levels as CL, duel_engine as DE, game_logic as GL, auctions as AU
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); real_today, real_draw = GL.today_paris, DE.draw_goals
card = lambda n, t: (db.expire_all(), db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first())[1]
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p, credits=5000):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit(); return {"Authorization": "Bearer " + t}
def give(p, cd, n):
    u = U(p); o = db.query(OwnedCard).filter_by(user_id=u.id, card_id=cd.id).first()
    if o is None: db.add(OwnedCard(user_id=u.id, card_id=cd.id, quantity=n))
    else: o.quantity = n
    db.commit()
def qty(p, cd): db.expire_all(); o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=cd.id).first(); return o.quantity if o else 0
lvl = lambda p, cd: (db.expire_all(), CL.level_of(db, U(p).id, cd.id))[1]
H = {p: mk(p) for p in ("ana", "ben", "cléo", "dan")}

# des cartes de toutes les raretés pour Lucas (la base de test n'a que des communes et des rares), un fan, une édition
lucas = db.query(Player).filter_by(name="Lucas").first()
for t in ("gold", "secrete", "epique", "legendaire", "speciale", "halloween", "ed2"):
    if card("Lucas", t) is None: db.add(Card(player_id=lucas.id, tier=Tier(t), vitesse=0, tir=0))
fan = Player(name="Fan Testeur", poste="FAN"); db.add(fan); db.flush(); db.add(Card(player_id=fan.id, tier=Tier.commune, vitesse=0, tir=0)); db.commit()
LC, LR, LH = card("Lucas", "commune"), card("Lucas", "rare"), card("Lucas", "halloween")

print("1) CARTES ÉLIGIBLES")
ok(all(CL.ineligible_reason(card("Lucas", t)) is None for t in ("commune", "rare", "halloween", "ed2")), "commune, rare et éditions limitées (Halloween, éditions personnalisées) : éligibles")
for t in ("gold", "secrete", "epique", "legendaire", "speciale"):
    give("ana", card("Lucas", t), 30)
    r = c.get("/cards/%s/level" % card("Lucas", t).id, headers=H["ana"]).json(); e = c.post("/cards/%s/evolve" % card("Lucas", t).id, headers=H["ana"])
    ok(not r["eligible"] and "ne peut pas évoluer" in r["reason"] and e.status_code == 400, "%s : refusé avec la raison (« %s »)" % (t, r["reason"][:70]))
fc = db.query(Card).filter_by(player_id=fan.id).first(); give("ana", fc, 30)
ok("Seules les cartes de joueurs" in c.get("/cards/%s/level" % fc.id, headers=H["ana"]).json()["reason"], "carte de fan : refusée")

print("2) DOUBLONS REQUIS ET COÛTS")
ok(CL.DUPES_REQUIRED == {"commune": [5, 10, 20, 50, 100], "rare": [1, 3, 5, 12, 25], "edition": [1, 3, 5, 8, 10]} and CL.COSTS == {"commune": [30, 60, 120, 200, 320], "rare": [45, 90, 180, 300, 480], "edition": [60, 120, 240, 400, 640]}, "paliers et coûts par rareté")
good = True
for t, g in (("commune", "commune"), ("rare", "rare"), ("halloween", "edition")):
    cd = card("Lucas", t)
    for n in range(1, 6):
        need = CL.DUPES_REQUIRED[g][n - 1]; CL.set_level(db, U("ben").id, cd.id, n - 1); db.commit()
        give("ben", cd, need); short = CL.info(db, U("ben"), cd)                    # need - 1 doublons : refusé
        give("ben", cd, need + 1); full = CL.info(db, U("ben"), cd)                 # need doublons : possible
        good &= (not short["can"] and "tu en as %d" % (need - 1) in short["reason"]) and full["can"] and full["cost"] == CL.COSTS[g][n - 1] and full["dupes_needed"] == need
    CL.set_level(db, U("ben").id, cd.id, 0); db.commit()
ok(good, "pour chaque rareté et chaque niveau : exactement le nombre de doublons demandé, le bon coût")
give("ana", LC, 6); cr0 = U("ana").credits
r = c.post("/cards/%s/evolve" % LC.id, headers=H["ana"])
ok(r.status_code == 200 and r.json()["level"] == 1 and U("ana").credits == cr0 - 30 and qty("ana", LC) == 6, "niveau 1 d'une commune : 30 crédits débités, les 5 doublons ne sont PAS détruits (toujours 6 exemplaires)")
i = c.get("/cards/%s/level" % LC.id, headers=H["ana"]).json()
ok(i["level"] == 1 and i["next_level"] == 2 and i["dupes"] == 5 and i["dupes_needed"] == 10 and "tu en as 5" in i["reason"], "niveau 2 : « il te faut 10 doublons… tu en as 5 »")
give("dan", LR, 2); U("dan").credits = 10; db.commit()
ok(c.post("/cards/%s/evolve" % LR.id, headers=H["dan"]).status_code == 400 and "crédits" in c.get("/cards/%s/level" % LR.id, headers=H["dan"]).json()["reason"], "pas assez de crédits : refusé")

print("3) LIMITE DE 2 PAR JOUR, NIVEAU 5 MAXIMUM")
give("ana", LR, 30); give("ana", LH, 30)
ok(c.post("/cards/%s/evolve" % LR.id, headers=H["ana"]).status_code == 200, "2e amélioration du jour : acceptée")
r = c.post("/cards/%s/evolve" % LH.id, headers=H["ana"]); ok(r.status_code == 400 and "aujourd'hui" in r.json()["detail"], "3e amélioration du jour : refusée")
GL.today_paris = lambda: real_today() + timedelta(days=1)
ok(c.post("/cards/%s/evolve" % LH.id, headers=H["ana"]).status_code == 200, "le lendemain : de nouveau possible")
GL.today_paris = real_today
CL.set_level(db, U("ana").id, LH.id, 5); db.commit()
GL.today_paris = lambda: real_today() + timedelta(days=5)
r = c.post("/cards/%s/evolve" % LH.id, headers=H["ana"]); ok(r.status_code == 400 and "maximal" in r.json()["detail"], "niveau 5 : maximum atteint")
GL.today_paris = real_today

print("4) EFFET EN MATCH")
m = DE.build_members([(LC, "MC")], LC.id, {LC.id: 5})[0]                      # Lucas (ATT) au milieu, capitaine, niveau 5
ok(m["base_note"] == 80 and abs(m["effective"] - 80 * 0.9 * 1.1) < 1e-9 and m["level"] == 5, "commune 75 + niveau 5 = 80, puis -10 %% hors poste, puis +10 %% capitaine (%.2f)" % m["effective"])
ok(DE.build_members([(LC, "ATT")], None)[0]["base_note"] == 75, "sans niveau : 75")
CORE = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
for p in ("cléo", "dan"):
    for n, _ in CORE: give(p, card(n, "commune"), 1)
CL.set_level(db, U("cléo").id, card("Hugo", "commune").id, 3); CL.set_level(db, U("dan").id, card("Lucas", "commune").id, 4); db.commit()
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n, "commune").id, "slot_category": s} for n, s in CORE]}
DE.draw_goals = lambda xg: 1
pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["cléo"]).json()["id"]
res = c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["dan"]).json(); DE.draw_goals = real_draw
dm = {m["player"]: m for m in res["lineups"]["defender"]["players"]}; cm = {m["player"]: m for m in res["lineups"]["challenger"]["players"]}
ok(dm["Hugo"]["level"] == 3 and dm["Hugo"]["base_note"] == 78 and cm["Lucas"]["level"] == 4 and cm["Lucas"]["base_note"] == 79 and cm["Hugo"]["level"] == 0, "défi 1v1 : le niveau de chaque joueur compte pour sa propre équipe (créateur Hugo 78, challenger Lucas 79)")
col = {(x["player_name"], x["tier"]): x for x in c.get("/collection", headers=H["dan"]).json() if x.get("quantity")}
ok(col[("Lucas", "commune")]["level"] == 4 and col[("Lucas", "commune")]["display_note"]["value"] == 79 and col[("Lucas", "commune")]["base_note"] == 75, "collection : niveau 4 et note affichée 79 (base 75)")

print("5) LE NIVEAU SUIT LA CARTE : ANNONCE")
H["eve"] = mk("eve"); H["fred"] = mk("fred")
give("eve", LR, 1); CL.set_level(db, U("eve").id, LR.id, 3); db.commit()
lid = c.post("/market/list", json={"card_id": LR.id, "price": 10}, headers=H["eve"]).json()["id"]
ls = {l["id"]: l for l in c.get("/market/listings").json()}[lid]
ok(lvl("eve", LR) == 0 and ls["level"] == 3 and ls["card"]["display_note"]["value"] == 88, "seule copie évoluée mise en vente : l'annonce porte le niveau 3 (note 88), le vendeur n'a plus de niveau")
ok(c.delete("/market/listings/%s" % lid, headers=H["eve"]).status_code == 200 and lvl("eve", LR) == 3 and qty("eve", LR) == 1, "annonce annulée : la carte revient avec son niveau 3")
lid = c.post("/market/list", json={"card_id": LR.id, "price": 10}, headers=H["eve"]).json()["id"]
r = c.post("/market/buy/%s" % lid, headers=H["fred"]).json()
ok(r["level"] == 3 and r["level_kept"] and lvl("fred", LR) == 3 and qty("fred", LR) == 1 and qty("eve", LR) == 0, "fred achète : il reçoit la carte au niveau 3")
h = [t for t in c.get("/market/history", headers=H["fred"]).json() if t["buyer"] == "fred"][0]; ok(h["level"] == 3, "historique des ventes : niveau 3")
give("eve", LR, 3); CL.set_level(db, U("eve").id, LR.id, 2); db.commit()
lid = c.post("/market/list", json={"card_id": LR.id, "price": 10, "evolved": False}, headers=H["eve"]).json()["id"]
ok({l["id"]: l for l in c.get("/market/listings").json()}[lid]["level"] == 0 and lvl("eve", LR) == 2, "3 copies, « un doublon normal » : annonce sans niveau, le vendeur garde son niveau 2")
lid2 = c.post("/market/list", json={"card_id": LR.id, "price": 10, "evolved": True}, headers=H["eve"]).json()["id"]
ok({l["id"]: l for l in c.get("/market/listings").json()}[lid2]["level"] == 2 and lvl("eve", LR) == 0 and qty("eve", LR) == 1, "« ma carte évoluée » : l'annonce porte le niveau 2, la copie restante repasse au niveau 0")
CL.set_level(db, U("fred").id, LR.id, 4); db.commit()
r = c.post("/market/buy/%s" % lid2, headers=H["fred"]).json()
ok(not r["level_kept"] and lvl("fred", LR) == 4, "l'acheteur a déjà le niveau 4 : il le garde, le niveau 2 reçu est perdu")

print("6) ENCHÈRES")
give("eve", LH, 1); CL.set_level(db, U("eve").id, LH.id, 2); db.commit()
aid = c.post("/auctions", json={"card_id": LH.id, "start_price": 5, "minutes": 15}, headers=H["eve"]).json()["id"]
au = {a["id"]: a for a in c.get("/auctions").json()["auctions"]}[aid]
ok(au["level"] == 2 and lvl("eve", LH) == 0, "enchère de la copie évoluée : niveau 2 affiché")
ok(c.delete("/auctions/%s" % aid, headers=H["eve"]).status_code == 200 and lvl("eve", LH) == 2, "enchère annulée : la carte revient avec son niveau")
aid = c.post("/auctions", json={"card_id": LH.id, "start_price": 5, "minutes": 15}, headers=H["eve"]).json()["id"]
a = db.get(AU.Auction, aid); a.ends_at = AU._now() - timedelta(minutes=1); db.commit(); AU.settle_due(db)
ok(lvl("eve", LH) == 2 and qty("eve", LH) == 1, "enchère terminée sans enchère : la carte revient avec son niveau")
aid = c.post("/auctions", json={"card_id": LH.id, "start_price": 5, "minutes": 15}, headers=H["eve"]).json()["id"]
ok(c.post("/auctions/%s/bid" % aid, json={"amount": 5}, headers=H["fred"]).status_code == 200, "fred enchérit")
db.expire_all(); a = db.get(AU.Auction, aid); a.ends_at = AU._now() - timedelta(minutes=1); db.commit(); AU.settle_due(db)
ok(lvl("fred", LH) == 2 and qty("fred", LH) == 1 and lvl("eve", LH) == 0, "fred remporte l'enchère : il reçoit la carte au niveau 2")

print("7) OFFRE D'ACHAT ACCEPTÉE")
LE = card("Lucas", "ed2"); give("eve", LE, 2); CL.set_level(db, U("eve").id, LE.id, 1); db.commit()
oid = c.post("/market/offers", json={"card_id": LE.id, "price": 5}, headers=H["fred"]).json()["id"]
r = c.post("/market/offers/%s/accept" % oid, headers=H["eve"]).json()
ok(r["level"] == 0 and lvl("eve", LE) == 1 and lvl("fred", LE) == 0, "2 copies : le vendeur donne une copie normale et garde son niveau 1")
oid = c.post("/market/offers", json={"card_id": LE.id, "price": 5}, headers=H["cléo"]).json()["id"]
r = c.post("/market/offers/%s/accept" % oid, headers=H["eve"]).json()
ok(r["level"] == 1 and lvl("cléo", LE) == 1 and lvl("eve", LE) == 0 and qty("eve", LE) == 0, "dernière copie (évoluée) : elle part avec son niveau")

print("8) DOUBLONS VENDUS, ÉCHANGÉS OU FUSIONNÉS : LE NIVEAU RESTE")
H["gus"] = mk("gus"); give("gus", LC, 8); CL.set_level(db, U("gus").id, LC.id, 2); db.commit()
c.post("/collection/sell-duplicates", json={"keep_for_secrets": False}, headers=H["gus"])
ok(qty("gus", LC) == 1 and lvl("gus", LC) == 2, "« vendre mes doublons » : il reste 1 exemplaire, toujours au niveau 2")
give("gus", LC, 3); give("fred", card("Nathan", "commune"), 3)
sid = c.post("/swaps", json={"to": "fred", "give_card_id": LC.id, "want_card_id": card("Nathan", "commune").id}, headers=H["gus"]).json()["id"]
ok(c.post("/swaps/%s/accept" % sid, headers=H["fred"]).status_code == 200 and qty("gus", LC) == 2 and lvl("gus", LC) == 2 and lvl("fred", LC) == 0, "échange d'un doublon : le niveau reste chez gus, fred reçoit une copie normale")
sec = card("Lucas", "secrete"); give("gus", LC, 101); give("gus", sec, 0)
ok(c.post("/collection/unlock-secret", json={"card_id": sec.id}, headers=H["gus"]).status_code == 200 and qty("gus", LC) == 1 and lvl("gus", LC) == 2, "fusion de la secrète avec 100 doublons : il reste 1 exemplaire au niveau 2")

print("9) ADMIN ET NETTOYAGE")
ok(c.post("/admin/set-card-level", json={"pseudo": "gus", "player_name": "Lucas", "tier": "commune", "level": 5}).status_code == 403, "commande admin : clé obligatoire")
ok(c.post("/admin/set-card-level", json={"pseudo": "gus", "player_name": "Lucas", "tier": "commune", "level": 5}, headers=A).status_code == 200 and lvl("gus", LC) == 5, "l'admin fixe le niveau 5 sans paiement")
ok(c.post("/admin/set-card-level", json={"pseudo": "gus", "player_name": "Lucas", "tier": "gold", "level": 1}, headers=A).status_code == 400, "carte gold : refusée même pour l'admin")
c.post("/admin/delete-user", json={"pseudo": "gus"}, headers=A); db.expire_all()
ok(db.query(CL.CardLevel).filter_by(user_id="x").count() == 0 and not [r for r in db.query(CL.CardLevel).all() if db.get(User, r.user_id) is None], "compte supprimé : ses niveaux aussi")
le_id = LE.id; n0 = db.query(CL.CardLevel).filter_by(card_id=le_id).count()
c.post("/admin/delete-card", json={"player_name": "Lucas", "tier": "ed2"}, headers=A); db.expire_all()
ok(n0 >= 1 and db.query(CL.CardLevel).filter_by(card_id=le_id).count() == 0, "carte supprimée : ses niveaux aussi")
print("BILAN (niveaux de cartes) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
