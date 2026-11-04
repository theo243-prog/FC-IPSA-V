"""
Test : cosmétiques à paliers du shop (5 pistes de 5 paliers, 50 à 500 crédits, achat dans l'ordre, équipement comme les objets du Pass,
remboursement par l'admin, nettoyage à la suppression du compte). Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import shop_catalog as SC, shop_cosmetics as SH, pass_catalog as PC
from app.models import User
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p, credits):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit()
    return {"Authorization": "Bearer " + t}
H = {"riche": mk("riche", 10000), "pauvre": mk("pauvre", 140)}
buy = lambda p, i: c.post("/shop/cosmetics/buy", json={"item_id": i}, headers=H[p])

print("1) LE CATALOGUE")
ok(len(SC.SHOP_ITEMS) == 25 and SC.PRICES == [50, 100, 200, 350, 500] and all(i in PC.ITEMS for i in SC.SHOP_ITEMS), "25 cosmétiques (5 pistes × 5 paliers, 50 → 500 crédits), ajoutés au catalogue des objets du Pass")
ok(SC.SHOP_ITEMS["shop-title-5"]["name"] == "Pigeon du shop", "le dernier titre est « Pigeon du shop »")
ok(SC.SHOP_ITEMS["shop-name_color-5"]["style"].get("holo") and "shopHoloText" in SC.SHOP_ITEMS["shop-name_color-5"]["style"]["css"] and SC.SHOP_ITEMS["shop-banner-5"]["style"].get("holo"), "la dernière couleur de pseudo et la dernière bannière sont holographiques")
ok(not any(set(SC.SHOP_ITEMS) & {it.get("item") for it in [PC.premium_reward(t, l, "2026-11") for t in PC.THEMES for l in range(1, 31)]}), "aucun cosmétique du shop n'est une récompense du Pass")
g = c.get("/shop/cosmetics", headers=H["riche"]).json()
ok([t["kind"] for t in g["tracks"]] == ["title", "frame", "banner", "name_color", "badge"] and g["owned"] == 0 and g["total"] == 25 and g["total_price"] == 6000, "5 pistes (titres, cadres, bannières, couleurs du pseudo, badges), rien de possédé, 6000 crédits pour tout")
ok(all(t["levels"][0]["next"] and not any(l["next"] for l in t["levels"][1:]) for t in g["tracks"]), "seul le palier 1 de chaque piste est achetable au départ")
ok(c.get("/shop/cosmetics").status_code == 401, "il faut être connecté")
sty = c.get("/pass/styles").json()["items"]; ok("shop-banner-5" in sty and sty["shop-banner-5"]["style"]["holo"], "le dessin des cosmétiques du shop est public (pour les afficher chez les autres)")

print("2) ACHATS")
ok(buy("riche", "shop-title-2").status_code == 400 and U("riche").credits == 10000, "palier 2 sans le palier 1 : refusé, rien n'est débité")
ok(buy("riche", "inconnu").status_code == 404, "cosmétique inconnu : 404")
r = buy("riche", "shop-title-1"); ok(r.status_code == 200 and r.json()["credits_total"] == 9950 and U("riche").credits == 9950, "palier 1 acheté : −50 crédits")
ok(buy("riche", "shop-title-1").status_code == 400 and U("riche").credits == 9950, "racheter le même palier : refusé, rien n'est débité")
for lv in range(2, 6): buy("riche", "shop-title-%d" % lv)
ok(U("riche").credits == 10000 - 1200, "les 5 titres achetés dans l'ordre : 1200 crédits au total")
for k in ("frame", "banner", "name_color", "badge"):
    for lv in range(1, 6): buy("riche", SC.shop_item_id(k, lv))
g = c.get("/shop/cosmetics", headers=H["riche"]).json(); ok(g["owned"] == 25 and U("riche").credits == 4000 and not any(l["next"] for t in g["tracks"] for l in t["levels"]), "les 25 achetés : 6000 crédits dépensés, plus rien à acheter")
ok(buy("pauvre", "shop-title-1").status_code == 200 and buy("pauvre", "shop-title-2").status_code == 400 and U("pauvre").credits == 90 and "100" in buy("pauvre", "shop-title-2").json()["detail"], "pas assez de crédits : refusé avec le prix, rien n'est débité")
ok(c.get("/shop/items").status_code == 200 and all(i["item"].startswith("pack_") for i in c.get("/shop/items").json()), "la liste des packs du shop ne change pas")

print("3) ÉQUIPER ET AFFICHER")
inv = {i["id"] for i in c.get("/pass/inventory", headers=H["riche"]).json()["items"]}; ok(set(SC.SHOP_ITEMS) <= inv, "les cosmétiques achetés sont dans l'inventaire")
cat = c.get("/cosmetics", headers=H["riche"]).json()
ok(any(t["id"] == "shop-title-5" and t["unlocked"] and "Boutique" in t["desc"] for t in cat["titles"]) and any(f["id"] == "shop-frame-5" and f["unlocked"] for f in cat["frames"]), "titres et cadres achetés sont proposés dans « Titre et cadre »")
ok(c.post("/cosmetics", json={"title": "shop-title-5", "frame": "shop-frame-5"}, headers=H["riche"]).status_code == 200, "on équipe le titre « Pigeon du shop » et le cadre du Pigeon")
ok(c.post("/pass/equip", json={"banner": "shop-banner-5", "name_color": "shop-name_color-5", "badge": "shop-badge-5"}, headers=H["riche"]).status_code == 200, "on équipe la bannière et le pseudo holographiques, et le badge Pigeon")
p = c.get("/users/riche/profile").json()
ok(p.get("title") == "Pigeon du shop" and p.get("frame") == "shop-frame-5" and p.get("banner") == "shop-banner-5" and p.get("name_color") == "shop-name_color-5" and p.get("badge") == "shop-badge-5", "le profil public affiche le titre, le cadre, la bannière, la couleur et le badge")
ok(c.post("/cosmetics", json={"title": "shop-title-5"}, headers=H["pauvre"]).status_code == 400 and c.post("/pass/equip", json={"banner": "shop-banner-1"}, headers=H["pauvre"]).status_code == 400, "un cosmétique non acheté ne s'équipe pas")

print("4) ADMINISTRATION")
rows = c.get("/admin/shop-cosmetics", headers=A).json(); tot = rows[-1]
ok(c.get("/admin/shop-cosmetics").status_code == 403 and len(rows) == 26 and tot["acheteurs"] == 26 and tot["credits_depenses"] == 6050, "les ventes par palier : 26 achats, 6050 crédits retirés du jeu (403 sans clé)")
ok(c.post("/admin/shop-cosmetics-refund", json={"pseudo": "riche", "item_id": "shop-title-4"}, headers=A).status_code == 400, "rembourser un palier qui n'est pas le plus haut de sa piste : refusé")
ok(c.post("/admin/shop-cosmetics-refund", json={"pseudo": "riche", "item_id": "shop-xx-1"}, headers=A).status_code == 404 and c.post("/admin/shop-cosmetics-refund", json={"pseudo": "personne", "item_id": "shop-title-5"}, headers=A).status_code == 404, "identifiant ou pseudo inconnu : 404")
cr = U("riche").credits; r = c.post("/admin/shop-cosmetics-refund", json={"pseudo": "riche", "item_id": "shop-title-5"}, headers=A)
p = c.get("/users/riche/profile").json()
ok(r.status_code == 200 and U("riche").credits == cr + 500 and p.get("title") is None and p.get("frame") == "shop-frame-5", "remboursement du titre « Pigeon du shop » : +500 crédits, le titre est retiré du profil, le reste ne bouge pas")
r = c.post("/admin/shop-cosmetics-refund", json={"pseudo": "riche", "item_id": "shop-banner-5"}, headers=A); ok(r.status_code == 200 and c.get("/users/riche/profile").json().get("banner") is None, "rembourser la bannière équipée la retire aussi")
ok(buy("riche", "shop-title-5").status_code == 200, "le palier remboursé peut être racheté")
log = c.get("/admin/log", params={"q": "Cosmétique du shop"}, headers=A).json(); ok(any("riche" in x["action"] for x in log), "le remboursement est noté dans le journal de l'administration")

print("5) SUPPRESSION D'UN COMPTE")
c.post("/admin/delete-user", json={"pseudo": "riche"}, headers=A)
ok(db.query(SH.ShopCosmeticPurchase).filter_by(user_id="x").count() == 0 and all(r.item_id for r in db.query(SH.ShopCosmeticPurchase).all()) and db.query(SH.ShopCosmeticPurchase).count() == 1, "supprimer un compte efface ses achats (il ne reste que celui de « pauvre »)")

print("BILAN (cosmétiques du shop) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
