"""
Test : son de la semaine au shop (100 crédits, un son par semaine tiré parmi ceux qui ne sont pas des sons de Pass ni le loup, les mêmes
pour tous, rotation sans répéter la semaine d'avant, achat gardé pour toujours et choisi comme un son du Pass). Lancé par tests/run_tests.py.
"""
from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import shop_sounds as SS, pass_catalog as P, game_logic as GL
from app.models import User
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
H = {"riche": mk("riche", 1000), "pauvre": mk("pauvre", 50)}
real_today = GL.today_paris

print("1) LE CATALOGUE")
files = {it["style"]["file"] for it in SS.ITEMS.values()}
ok(len(SS.ITEMS) == 7 and files == {"sounds/%s.mp3" % f for f in ("actrice", "clap", "elephant", "nine", "ph", "siuu", "tronc")}, "7 sons au shop (actrice, clap, éléphant, nine, ph, siuu, tronc)")
ok(not any(f[len("sounds/"):-4] in set(P.THEMES) | {"loup"} for f in files), "jamais un son de Pass de saison (halloween, noël…) ni le hurlement du loup")
ok(all(i in P.ITEMS and P.ITEMS[i]["kind"] == "sound" for i in SS.ITEMS), "ajoutés aux objets du Pass (type « son »)")

print("2) LE SON DE LA SEMAINE")
GL.today_paris = lambda: date(2026, 11, 11)          # un mercredi
s = c.get("/shop/sound", headers=H["riche"]).json()
ok(s["week"] == "2026-11-09" and s["ends"] == "2026-11-16" and s["price"] == 100 and s["sound"]["id"] in SS.ITEMS and not s["sound"]["owned"], "semaine du lundi 9 au dimanche 15 novembre, 100 crédits")
ok(c.get("/shop/sound", headers=H["pauvre"]).json()["sound"]["id"] == s["sound"]["id"], "le même son pour tout le monde")
GL.today_paris = lambda: date(2026, 11, 15)          # dimanche, même semaine
ok(c.get("/shop/sound", headers=H["riche"]).json()["sound"]["id"] == s["sound"]["id"], "le même son toute la semaine")
weeks = []
for k in range(14):
    GL.today_paris = (lambda d: (lambda: d))(date(2026, 11, 9) + timedelta(days=7 * k))
    weeks.append(c.get("/shop/sound", headers=H["riche"]).json()["sound"]["id"])
ok(all(weeks[k] != weeks[k - 1] for k in range(1, 14)), "jamais deux semaines de suite le même son")
ok(len(set(weeks[:7])) == 7 and len(set(weeks[7:14])) == 7, "rotation : les 7 sons passent tous avant qu'un revienne (%s)" % [w[len("shop-son-"):] for w in weeks[:7]])

print("3) ACHAT")
GL.today_paris = lambda: date(2026, 11, 11); cur = s["sound"]["id"]; other = next(i for i in SS.ITEMS if i != cur)
r = c.post("/shop/sound/buy", json={"item_id": cur}, headers=H["pauvre"])
ok(r.status_code == 400 and "crédits" in r.json()["detail"] and U("pauvre").credits == 50, "pas assez de crédits : refusé")
ok(c.post("/shop/sound/buy", json={"item_id": other}, headers=H["riche"]).status_code == 400, "un son qui n'est pas celui de la semaine : refusé")
r = c.post("/shop/sound/buy", json={"item_id": cur}, headers=H["riche"])
ok(r.status_code == 200 and U("riche").credits == 900 and r.json()["sound"]["owned"], "achat : 100 crédits")
ok(c.post("/shop/sound/buy", json={"item_id": cur}, headers=H["riche"]).status_code == 400 and U("riche").credits == 900, "déjà possédé : pas de second achat")

print("4) LE CHOISIR COMME SON D'OUVERTURE")
inv = c.get("/pass/inventory", headers=H["riche"]).json()
ok(any(i["id"] == cur for i in inv["items"]), "il est dans l'inventaire (profil, « Titre et cadre »)")
ok(c.post("/pass/sound", json={"item_id": cur}, headers=H["riche"]).status_code == 200 and c.get("/me", headers=H["riche"]).json()["open_sound"]["file"] == SS.ITEMS[cur]["style"]["file"], "choisi : /me renvoie son fichier pour l'ouverture des packs")
ok(c.post("/pass/sound", json={"item_id": other}, headers=H["riche"]).status_code == 400, "un son du shop qu'on n'a pas acheté : refusé")
SS.on_user_deleted(db, U("riche").id); db.commit()
ok(db.query(SS.ShopSoundPurchase).filter_by(user_id=U("riche").id).count() == 0, "compte supprimé : ses achats sont effacés")
GL.today_paris = real_today

print(); print("BILAN (sons du shop) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
