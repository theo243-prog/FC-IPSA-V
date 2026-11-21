"""
Test : récompenses secrètes de collection (en essai) : Prisme (commune, rare, édition limitée, secrète et Édition Noire d'une personne) et Couronne noire (toute son Édition Noire).
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import collection_bonus as CB, features, cosmetics
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; db.query(User).filter_by(pseudo=p).first().credits = 100; db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("cba", "cbb", "cbc")}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
me = lambda p: c.get("/me", headers=H[p]).json()
def card(name, tier):
    pl = db.query(Player).filter_by(name=name).first()
    cd = db.query(Card).filter_by(player_id=pl.id, tier=Tier(tier)).first()
    if cd is None:
        cd = Card(player_id=pl.id, tier=Tier(tier), vitesse=70, tir=70); db.add(cd); db.commit()
    return cd
def give(p, name, tier, q=1):
    cd = card(name, tier); o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=cd.id).first()
    if o is None: db.add(OwnedCard(user_id=U(p).id, card_id=cd.id, quantity=q))
    else: o.quantity = q
    db.commit()
owns = lambda p, name: db.query(OwnedCard).join(Card).join(Player).filter(OwnedCard.user_id == U(p).id, OwnedCard.quantity > 0, Player.name == name).count() > 0

print("1) PRISME : FERMÉ SANS ACCÈS, PUIS LES 5 CARTES")
for n in ("Lucas", "Hugo"):
    c.post("/admin/series-create", json={"title": "Édition Noire", "subject": n, "total": 5}, headers=A)
for t in ("commune", "rare", "secrete", "epique", "legendaire", "speciale"): give("cba", "Lucas", t)
ok(True, "(cba a commune, rare, secrète, épique, légendaire et spéciale de Lucas)")
features.save(db, "prisme", {"public": False, "allowed": ["cba", "cbb"]}); db.commit()
ok(me("cba")["bonus_unseen"] == [], "sans édition limitée ni Édition Noire : rien (épique, légendaire et spéciale ne comptent pas)")
give("cba", "Lucas", "halloween")
ok(me("cba")["bonus_unseen"] == [], "avec une édition limitée mais sans Édition Noire : rien")
features.save(db, "prisme", {"public": False, "allowed": []}); db.commit()
c.post("/admin/series-mint", json={"series": "Édition Noire — Lucas", "pseudo": "cba", "number": 3}, headers=A)
ok(me("cba")["bonus_unseen"] == [] and not owns("cba", "Prisme — Lucas"), "sans accès à l'essai : rien n'est débloqué (secret)")
features.save(db, "prisme", {"public": False, "allowed": ["cba", "cbb"]}); features.save(db, "couronne_noire", {"public": False, "allowed": ["cba", "cbb"]}); db.commit()
u = me("cba")["bonus_unseen"]
ok(len(u) == 1 and u[0]["kind"] == "prisme" and u[0]["subject"] == "Lucas" and u[0]["card"]["bonus"]["kind"] == "prisme" and u[0]["card"]["tier"] == "saison", "avec l'accès : le Prisme de Lucas est débloqué, à révéler")
ok(owns("cba", "Prisme — Lucas") and u[0]["title"] == "Fan absolu de Lucas", "la carte « Prisme — Lucas » est dans sa collection, avec son titre")
ok(len(me("cba")["bonus_unseen"]) == 1 and db.query(CB.BonusUnlock).filter_by(user_id=U("cba").id).count() == 1, "une seule fois")
ok(c.post("/collection-bonus/seen", json={"ids": [u[0]["id"]]}, headers=H["cba"]).status_code == 200 and me("cba")["bonus_unseen"] == [], "révélation vue : elle ne revient plus")
for t in ("commune", "rare", "secrete"): give("cbb", "Hugo", t)
give("cbb", "Hugo", "noel"); ok(me("cbb")["bonus_unseen"] == [], "4 cartes sur 5 (commune, rare, secrète, Noël) : rien")
c.post("/admin/series-mint", json={"series": "Édition Noire — Hugo", "pseudo": "cbb"}, headers=A)
ok([b["subject"] for b in me("cbb")["bonus_unseen"]] == ["Hugo"], "la 5e (un exemplaire Édition Noire, n'importe lequel) : le Prisme de Hugo")
tids = [t["id"] for t in c.get("/cosmetics", headers=H["cbb"]).json()["titles"] if t.get("label") == "Fan absolu de Hugo"] if c.get("/cosmetics", headers=H["cbb"]).status_code == 200 else [tid for tid, _ in CB.titles(db, U("cbb").id)]
ok(tids and cosmetics.title_label(tids[0], db) == "Fan absolu de Hugo", "le titre « Fan absolu de Hugo » est disponible")

print("2) LA CARTE NE SE VEND PAS, NE S'ÉCHANGE PAS")
pc = db.query(Card).join(Player).filter(Player.name == "Prisme — Lucas").first()
ok(c.post("/market/list", json={"card_id": pc.id, "price": 100}, headers=H["cba"]).status_code == 400, "mise en vente refusée")
col = c.get("/collection", headers=H["cbc"]).json()
ok(not any(x["id"] == pc.id for x in col), "invisible dans la collection de ceux qui ne l'ont pas (pas de case « ? »)")
ok(any(x["id"] == pc.id and x["bonus"]["kind"] == "prisme" for x in c.get("/collection", headers=H["cba"]).json()), "visible chez celui qui l'a")

print("3) COURONNE NOIRE : TOUTE LA SÉRIE")
r = c.post("/admin/series-create", json={"title": "Édition Noire", "subject": "Nathan", "total": 5}, headers=A); ok(r.status_code == 200, "série Édition Noire de Nathan (5 exemplaires)")
for n in (1, 2, 3, 4): c.post("/admin/series-mint", json={"series": "Édition Noire — Nathan", "pseudo": "cba", "number": n}, headers=A)
ok(me("cba")["bonus_unseen"] == [], "4 exemplaires sur 5 : rien")
c.post("/admin/series-mint", json={"series": "Édition Noire — Nathan", "pseudo": "cba", "number": 5}, headers=A)
u = me("cba")["bonus_unseen"]
ok(len(u) == 1 and u[0]["kind"] == "couronne" and u[0]["subject"] == "Nathan" and owns("cba", "Couronne noire — Nathan"), "les 5 : la Couronne noire de Nathan")
ok(u[0]["title"] == "Seigneur noir de Nathan", "titre « Seigneur noir de Nathan »")

print("4) UNIQUE AU MONDE")
r = c.post("/admin/collection-bonus-grant", json={"pseudo": "cbb", "kind": "couronne", "player_name": "Nathan"}, headers=A)
ok(r.status_code == 400, "un autre compte ne peut pas l'avoir (admin refusé aussi)")
from app import numbered
s = db.query(numbered.NumberedSeries).filter_by(subject="Nathan").first()
for cp in db.query(numbered.NumberedCopy).filter_by(series_id=s.id).all():
    db.query(OwnedCard).filter_by(user_id=U("cba").id, card_id=cp.card_id).update({"user_id": U("cbb").id}, synchronize_session=False)
db.commit()
ok(not [b for b in me("cbb")["bonus_unseen"] if b["kind"] == "couronne"] and not owns("cbb", "Couronne noire — Nathan") and owns("cba", "Couronne noire — Nathan"), "cbb rachète toute la série : pas de couronne pour lui, cba garde la sienne")

print("5) ADMIN : DONNER ET REJOUER")
ok(c.post("/admin/collection-bonus-grant", json={"pseudo": "cbc", "kind": "prisme", "player_name": "Lucas"}, headers=A).status_code == 200, "donner le Prisme de Lucas à cbc (sans les conditions)")
ok(len(me("cbc")["bonus_unseen"]) == 1, "sa révélation se joue au prochain /me (même sans accès à l'essai : c'est un don de l'admin)")
c.post("/collection-bonus/seen", json={}, headers=H["cbc"])
ok(c.post("/admin/collection-bonus-replay", json={"pseudo": "cbc"}, headers=A).json()["replays"] == 1 and len(me("cbc")["bonus_unseen"]) == 1, "rejouer les révélations")
ok(c.post("/admin/collection-bonus-grant", json={"pseudo": "cbc", "kind": "arc", "player_name": "Lucas"}, headers=A).status_code == 400 and c.post("/admin/collection-bonus-grant", json={"pseudo": "cbc", "kind": "prisme", "player_name": "Personne"}, headers=A).status_code == 404, "refus : sorte inconnue, joueur introuvable")
ok(len(c.get("/admin/collection-bonus", headers=A).json()) == 4, "l'admin voit qui a quoi")

print("6) RENOMMER LA PERSONNE, SUPPRIMER UN COMPTE")
ok(c.post("/admin/rename-player", json={"old_name": "Lucas", "new_name": "Lucas B"}, headers=A).status_code == 200 and owns("cba", "Prisme — Lucas B"), "renommer Lucas : sa carte devient « Prisme — Lucas B »")
ok(CB.title_label(CB.TITLE_PREFIX + "prisme-" + db.query(Player).filter_by(name="Lucas B").first().id, db) == "Fan absolu de Lucas B", "le titre suit le nouveau nom")
c.post("/auth/register", json={"pseudo": "testadmin", "password": "test1234"})      # (compte de réserve : il reprend les exemplaires numérotés d'un compte supprimé)
ok(c.post("/admin/delete-user", json={"pseudo": "cba"}, headers=A).status_code == 200 and db.query(CB.BonusUnlock).filter_by(kind="couronne").count() == 0, "compte supprimé : la Couronne de Nathan redevient libre")

print(); print("BILAN (Prisme et Couronne noire) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
