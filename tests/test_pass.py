"""
Test : Pass de saison (piste gratuite et Premium, déblocage jour par jour, plafonds, points doublés, objets, packs d'édition, carte exclusive,
objectif du club, étoiles de prestige, rattrapage). L'horloge est simulée. Lancer comme test_tournament.py (voir tests/LISEZMOI.md).
"""
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import battlepass as BP, pass_catalog as P, missions as MI, tournament as TN, prono as PN
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 1, 10, 0)]; BP.now_paris = lambda: NOW[0]; TN.now_paris = lambda: NOW[0]
def at(d, h=10, mo=11, y=2026): NOW[0] = datetime(y, mo, d, h, 0)
db = SessionLocal()
def mk(p, credits=0):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit(); return {"Authorization": "Bearer " + t}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def pts(p, key="2026-11"): db.expire_all(); r = db.query(BP.PassProgress).filter_by(user_id=U(p).id, season=key).first(); return r.points if r else 0
H = {"p1": mk("p1", 1000), "p2": mk("p2", 50), "p3": mk("p3", 400)}
st = lambda who, **kw: c.get("/pass", headers=H[who]).json()
claim = lambda who, track, level, season=None: c.post("/pass/claim", json={"track": track, "level": level, **({"season": season} if season else {})}, headers=H[who])
grant = lambda p, points=0, premium=None: c.post("/admin/pass-grant", json={"pseudo": p, "points": points, **({} if premium is None else {"premium": premium})}, headers=A)
# 4 cartes d'édition Halloween pour tester les packs d'édition limitée
for n in ("Lucas", "Hugo", "Nathan", "Léo"):
    pl = db.query(Player).filter_by(name=n).first(); db.add(Card(player_id=pl.id, tier=Tier.halloween, vitesse=70, tir=70))
db.commit()

print("1) LA PISTE")
g = st("p1"); cur = g["current"]
ok(cur["key"] == "2026-11" and cur["label"] == "novembre 2026" and cur["theme"]["id"] == "halloween" and cur["theme"]["emoji"] == "🎃" and g["price"] == 300 and len(cur["levels"]) == 30, "novembre 2026 : thème Halloween par défaut, 30 niveaux, Premium à 300 crédits")
L = {l["level"]: l for l in cur["levels"]}; kinds = [P.ITEMS[L[n]["premium"]["item"]]["kind"] for n in range(1, 31)]
ok(all(L[n]["premium"]["item"] == ("pass-halloween-son" if n == P.SOUND_LEVEL else "pass-halloween-%d" % n) for n in L) and set(kinds) == set(P.KINDS) and kinds.count("badge") == 5, "chaque niveau Premium donne un objet décoratif (un par jour), de 8 sortes : " + ", ".join(sorted(set(kinds))))
ok(P.SOUND_LEVEL == 18 and kinds[17] == "sound" and kinds.count("sound") == 1 and kinds.count("name_color") == 3, "niveau 18 : le son d'ouverture remplace la couleur de pseudo (il en reste 3 : niveaux 4, 11, 25)")
ok(L[10]["premium"].get("pack") == "rare" and L[15]["premium"].get("credits") == 50 and L[20]["premium"].get("edition_pack") == 2 and L[25]["premium"].get("pass_card") and L[30]["premium"].get("edition_pack") == 3, "bonus Premium : pack rare (10), 50 crédits (15), pack d'édition 2 cartes (20), carte exclusive du Pass (25), pack d'édition 3 cartes (30)")
ok(L[1]["free"]["credits"] == 5 and L[4]["free"]["pack"] == "classique" and L[10]["free"]["item"] == "pass-halloween-f10" and L[2]["free"] is None and L[30]["free"]["item"] == "pass-halloween-f30", "piste gratuite : modeste (crédits, packs classiques, 3 objets sur la saison)")
ok([t["goal"] for t in cur["club"]["tiers"]] == [500, 1000, 1500, 2000, 3000] and cur["club"]["packs"] == 0, "objectif du club : 5 paliers (500 à 3000 packs ouverts), compteur à 0")

print("2) LES POINTS ET LE DÉBLOCAGE JOUR PAR JOUR")
ok(grant("p1", 150).status_code == 200 and st("p1")["current"]["level"] == 1 and st("p1")["current"]["waiting_for_day"] is False, "le 1er : 150 points = niveau 1 (les 50 points en plus ne sont pas perdus)")
grant("p1", 350); g = st("p1")["current"]; ok(g["points"] == 500 and g["level"] == 1 and g["waiting_for_day"] is True, "500 points dès le 1er jour : toujours niveau 1, et le site dit que le niveau suivant attend demain")
r = claim("p1", "free", 2); ok(r.status_code == 400 and "s'ouvre le jour 2" in r.json()["detail"], "réclamer le niveau 2 le jour 1 : refusé « " + r.json()["detail"] + " »")
b = U("p1").credits; r = claim("p1", "free", 1); ok(r.status_code == 200 and r.json()["reward"]["credits"] == 5 and U("p1").credits == b + 5, "niveau 1 gratuit réclamé : +5 crédits")
ok(claim("p1", "free", 1).status_code == 400 and claim("p1", "free", 3).status_code == 400 and claim("p2", "premium", 1).status_code == 400, "refusés : déjà réclamé ; piste gratuite sans récompense ; Premium sans Premium")
at(2); g = st("p1")["current"]; ok(g["level"] == 2 and g["waiting_for_day"] is True, "le 2 : le niveau 2 se débloque, les points restent")
at(5); ok(st("p1")["current"]["level"] == 5, "le 5 : niveau 5 (500 points)")

print("3) LES SOURCES DE POINTS, LES PLAFONDS ET LE DOUBLEMENT")
at(6); u1 = U("p1"); b = pts("p1"); gains = [BP.add_points(db, u1, "duel", 10, 50) for _ in range(7)]; db.commit()
ok(gains == [10, 10, 10, 10, 10, 0, 0] and pts("p1") == b + 50, "matchs 1v1 : 10 points chacun, plafonnés à 50 par jour (les suivants : 0)")
at(7); u1 = U("p1"); ok(BP.add_points(db, u1, "duel", 10, 50) == 10, "le lendemain, le plafond repart à zéro"); db.commit()
at(23); u1 = U("p1"); ok(BP.add_points(db, u1, "swap", 15, 30) == 15, "le 23 : points normaux (15)"); db.commit()
at(24); u1 = U("p1"); ok(BP.add_points(db, u1, "swap", 15, 30) == 30 and st("p1")["current"]["double_points"] is True, "dernière semaine du mois (à partir du 24) : points DOUBLÉS (15 → 30)"); db.commit()
ok(BP.add_points(db, u1, "swap", 15, 30) == 30 and BP.add_points(db, u1, "swap", 15, 30) == 0, "le plafond se compte sur les points de base : 2 échanges comptent, le 3e non"); db.commit()
at(2); u2 = U("p2"); MI.record(db, u2, "play_duel"); MI.record(db, u2, "open_packs", 3); ok(pts("p2") == 10 and db.get(BP.ClubGoal, "2026-11").packs == 3, "un match joué (missions) : +10 points ; 3 packs ouverts : +3 sur la barre du club")
u2 = U("p2"); bf = pts("p2"); at(3)
ok(c.post("/tournament/join", headers=H["p2"]).status_code == 200 and pts("p2") == bf + 30 and True, "s'inscrire au tournoi : +30 points")

print("4) LE PREMIUM (300 crédits)")
at(15); grant("p3", 1500)
r = c.post("/pass/premium", headers=H["p2"]); ok(r.status_code == 400 and "300 crédits" in r.json()["detail"], "pas assez de crédits : refusé « " + r.json()["detail"] + " »")
b = U("p3").credits; r = c.post("/pass/premium", headers=H["p3"]); ok(r.status_code == 200 and U("p3").credits == b - 300 and st("p3")["current"]["premium"] is True and c.post("/pass/premium", headers=H["p3"]).status_code == 400, "p3 achète le Premium le 15 : 400 → 100 crédits ; on ne l'achète pas deux fois")
g = st("p3")["current"]; ok(g["level"] == 15 and g["claimable"] >= 15, f"acheté en cours de mois : les {g['claimable']} récompenses déjà débloquées sont immédiatement disponibles (niveaux 1 à 15)")
ev = [m["text"] for m in c.get("/chat", headers=H["p3"]).json()["messages"] if m["kind"] == "event"]; ok(any("p3 a pris le Pass Premium de novembre 2026" in t for t in ev), "l'achat est annoncé dans le chat")
grant("p3", premium=False); ok(claim("p3", "premium", 1).status_code == 400, "(admin) retirer le Premium : réclamer est refusé"); grant("p3", premium=True)
print("5) LES RÉCOMPENSES PREMIUM")
r = claim("p3", "premium", 1); it = r.json()["reward"]["item"]; ok(r.status_code == 200 and it["id"] == "pass-halloween-1" and it["kind"] == "badge" and it["emoji"] == "🎃", "niveau 1 Premium : « " + it["name"] + " » (badge 🎃)")
b = U("p3").pack_state.rare_pack_tokens; claim("p3", "premium", 10); ok(U("p3").pack_state.rare_pack_tokens == b + 1, "niveau 10 : un pack rare")
b = U("p3").credits; claim("p3", "premium", 15); ok(U("p3").credits == b + 50, "niveau 15 : +50 crédits")
at(30); grant("p3", 1500); import random
for n in (2, 3, 4, 5, 6, 7, 8, 9): claim("p3", "premium", n)
r = claim("p3", "premium", 20); cards = r.json()["reward"]["edition_pack"]["cards"]; ok(r.status_code == 200 and len(cards) == 2 and all(x["tier"] == "halloween" for x in cards), "niveau 20 : pack d'édition limitée = 2 cartes Halloween : " + ", ".join(x["player_name"] for x in cards))
r = claim("p3", "premium", 25); pc = r.json()["reward"]["pass_card"]; ok(r.status_code == 200 and pc["trophy"]["rank"] == 6 and pc["trophy"]["theme"]["id"] == "halloween" and pc["trophy"]["theme"]["c2"] == "#FF8A1F" and pc["trophy"]["title"] == "Pass Halloween", "niveau 25 : la carte exclusive « Pass Halloween (novembre 2026) » au style Halloween (orange et violet sombre)")
r = claim("p3", "premium", 30); cards3 = r.json()["reward"]["edition_pack"]["cards"]; allc = {x["id"] for x in cards} | {x["id"] for x in cards3}
ok(r.status_code == 200 and len(cards3) == 3 and len(allc) == 4, "niveau 30 : 3 autres cartes Halloween (en privilégiant celles qu'on n'a pas) : 4 cartes différentes sur les 4 de l'édition")
col = c.get("/collection", headers=H["p3"]).json(); ok(any(x.get("trophy") and x["trophy"]["rank"] == 6 and x["quantity"] == 1 for x in col), "la carte du Pass est dans la collection (en un exemplaire)")
ok(claim("p3", "premium", 20).status_code == 400, "réclamer deux fois : refusé")
print("6) OBJETS ÉQUIPÉS (badge, bannière, couleur du pseudo, fond d'image, cadre, titre)")
for n in range(11, 20): claim("p3", "premium", n)
for n in (21, 22, 23, 24, 26, 27, 28, 29): claim("p3", "premium", n)
inv = c.get("/pass/inventory", headers=H["p3"]).json(); ok(len(inv["items"]) == 30 and {i["kind"] for i in inv["items"]} == set(P.KINDS), f"inventaire de p3 : {len(inv['items'])} objets des 8 sortes")
by = {k: [i["id"] for i in inv["items"] if i["kind"] == k] for k in P.KINDS}
r = c.post("/pass/equip", json={"banner": by["banner"][0], "name_color": by["name_color"][-1], "badge": by["badge"][0], "share_bg": by["share_bg"][0]}, headers=H["p3"]); ok(r.status_code == 200, "équiper bannière, couleur de pseudo, badge et fond d'image")
ok(c.post("/pass/equip", json={"badge": by["banner"][0]}, headers=H["p3"]).status_code == 400 and c.post("/pass/equip", json={"badge": "pass-halloween-f10"}, headers=H["p2"]).status_code == 400 and c.post("/pass/equip", json={"badge": "pass-noel-1"}, headers=H["p3"]).status_code == 400, "refusés : mauvais emplacement, objet qu'on n'a pas, objet d'un autre thème")
r = c.post("/cosmetics", json={"title": by["title"][0], "frame": by["frame"][0]}, headers=H["p3"]); ok(r.status_code == 200 and r.json()["frame"] == by["frame"][0], "cadre et titre du Pass : choisis comme les autres (« %s »)" % r.json().get("title"))
lb = {x["pseudo"]: x for x in c.get("/leaderboard").json()}; pr = c.get("/users/p3/profile").json()
ok(lb["p3"]["badge"] == by["badge"][0] and lb["p3"]["name_color"] == by["name_color"][-1] and lb["p3"]["frame"] == by["frame"][0] and lb["p3"]["title"] == P.ITEMS[by["title"][0]]["name"] and pr["banner"] == by["banner"][0] and pr["badge"] == by["badge"][0], "le classement et le profil public affichent ces objets")
c.post("/chat", json={"text": "salut"}, headers=H["p3"]); m = [x for x in c.get("/chat", headers=H["p3"]).json()["messages"] if x["kind"] == "user"][-1]; ok(m["badge"] == by["badge"][0] and m["name_color"] == by["name_color"][-1], "le chat aussi (badge et couleur de pseudo)")
sty = c.get("/pass/styles").json(); ok(len(sty["items"]) == len(P.ITEMS) and sty["items"][by["frame"][0]]["style"]["css"].startswith("box-shadow") and "halloween" in sty["themes"] and c.get("/me", headers=H["p3"]).json()["pass_todo"] >= 0, f"le dessin des {len(sty['items'])} objets est public (pour afficher ceux des autres) ; /me donne le nombre de récompenses à réclamer")
print("6 bis) SONS D'OUVERTURE DE PACKS")
snd = {t: P.ITEMS[P.sound_id(t)] for t in P.THEMES}
ok(len(snd) == 7 and all(P.premium_reward(t, 18, "2026-11")["item"] == P.sound_id(t) for t in P.THEMES), "un son par thème (7), au niveau 18 de la piste Premium à partir de novembre 2026")
ok(all(s["kind"] == "sound" and s["name"] == "Son d'ouverture " + P.THEMES[t]["name"] and s["style"]["file"] == "sounds/%s.mp3" % t and s["level"] == 18 for t, s in snd.items()), "chacun s'appelle « Son d'ouverture <Thème> » et joue frontend/sounds/<thème>.mp3")
ok(P.premium_reward("automne", 18, "2026-10")["item"] == "pass-automne-18" and P.ITEMS["pass-automne-18"]["kind"] == "name_color" and P.premium_reward("halloween", 17, "2026-11")["item"] == "pass-halloween-17", "octobre 2026 garde sa couleur de pseudo au niveau 18 ; les autres niveaux ne changent pas")
ok(all(i in P.ITEMS and P.ITEMS[i]["kind"] == "name_color" for i in ("pass-halloween-18", "pass-noel-18")), "les anciennes couleurs de pseudo du niveau 18 restent au catalogue (ceux qui les ont réclamées les gardent)")
inv = c.get("/pass/inventory", headers=H["p3"]).json(); me3 = c.get("/me", headers=H["p3"]).json()
ok(inv["loadout"]["sound"] is None and me3["open_sound"] is None and "pass-halloween-son" in [i["id"] for i in inv["items"]], "p3 possède le son Halloween (niveau 18 réclamé) ; par défaut : le hurlement du loup")
r = c.post("/pass/sound", json={"item_id": "pass-halloween-son"}, headers=H["p3"])
inv = c.get("/pass/inventory", headers=H["p3"]).json(); me3 = c.get("/me", headers=H["p3"]).json()
ok(r.status_code == 200 and inv["loadout"]["sound"] == "pass-halloween-son" and me3["open_sound"] == {"id": "pass-halloween-son", "name": "Son d'ouverture Halloween", "file": "sounds/halloween.mp3"}, "p3 choisit le son Halloween : enregistré sur le compte, renvoyé par l'inventaire et par /me")
ok(c.post("/pass/sound", json={"item_id": "pass-noel-son"}, headers=H["p3"]).status_code == 400 and c.post("/pass/sound", json={"item_id": "pass-halloween-son"}, headers=H["p1"]).status_code == 400, "refusés : un son qu'on ne possède pas (Noël pour p3, Halloween pour p1)")
ok(c.post("/pass/sound", json={"item_id": by["badge"][0]}, headers=H["p3"]).status_code == 400 and c.post("/pass/sound", json={"item_id": "inconnu"}, headers=H["p3"]).status_code == 400 and c.post("/pass/sound", json={"item_id": None}).status_code == 401, "refusés : un objet qui n'est pas un son, un objet inconnu ; sans compte : 401")
ok(c.get("/pass/inventory", headers=H["p3"]).json()["loadout"]["sound"] == "pass-halloween-son", "après ces refus, le choix de p3 n'a pas changé")
c.post("/pass/equip", json={"banner": by["banner"][0], "name_color": by["name_color"][-1], "badge": by["badge"][0], "share_bg": by["share_bg"][0]}, headers=H["p3"]); lo = c.get("/pass/inventory", headers=H["p3"]).json()["loadout"]
ok(lo["sound"] == "pass-halloween-son" and lo["badge"] == by["badge"][0] and lo["name_color"] == by["name_color"][-1], "équiper les autres objets ne touche pas au son (et inversement)")
ok(c.post("/pass/sound", json={"item_id": None}, headers=H["p3"]).status_code == 200 and c.get("/me", headers=H["p3"]).json()["open_sound"] is None, "revenir au hurlement du loup (choix vide)")
c.post("/pass/sound", json={"item_id": "pass-halloween-son"}, headers=H["p3"])
r = c.post("/admin/unlock-cosmetics", json={"pseudo": "p1", "enabled": True}, headers=A); inv1 = c.get("/pass/inventory", headers=H["p1"]).json()
ok(r.status_code == 200 and sorted(i["id"] for i in inv1["items"] if i["kind"] == "sound") == sorted(P.sound_id(t) for t in P.THEMES), "« tout débloquer » donne les 7 sons")
ok(c.post("/pass/sound", json={"item_id": "pass-noel-son"}, headers=H["p1"]).status_code == 200 and c.get("/me", headers=H["p1"]).json()["open_sound"]["file"] == "sounds/noel.mp3", "p1 (tout débloqué) peut choisir le son de Noël")
c.post("/admin/unlock-cosmetics", json={"pseudo": "p1", "enabled": False}, headers=A)
ok(c.get("/me", headers=H["p1"]).json()["open_sound"] is None and c.get("/pass/inventory", headers=H["p1"]).json()["loadout"]["sound"] is None, "déblocage retiré : le son qu'il ne possède plus n'est plus joué (retour au hurlement)")
print("7) ÉTOILES DE PRESTIGE")
ok(st("p3")["current"]["completed"] is True and lb["p3"]["stars"] == 1 and st("p3")["stars"] == 1, "le 30, 3000 points et le niveau 30 débloqué : Pass terminé, 1 étoile")
ev = [m["text"] for m in c.get("/chat", headers=H["p3"]).json()["messages"] if m["kind"] == "event"]; ok(any("p3 a terminé le Pass de novembre 2026 ! Étoile de prestige n°1" in t for t in ev), "annoncé dans le chat")
ok(st("p1")["current"]["completed"] is False and st("p1")["current"]["points"] < 3000, "p1 n'a pas fini son Pass : pas d'étoile")
print("8) OBJECTIF DU CLUB")
r = claim("p2", "club", 0); ok(r.status_code == 400 and "pas encore atteint" in r.json()["detail"], "palier 1 (500 packs) pas encore atteint : refusé")
ok(c.post("/admin/pass-club", json={"packs": 500}).status_code == 403 and c.post("/admin/pass-club", json={"packs": 500}, headers=A).status_code == 200, "(admin) 500 packs ajoutés à la barre commune")
b2, b3 = U("p2").credits, U("p3").credits; r2, r3 = claim("p2", "club", 0), claim("p3", "club", 0)
ok(r2.status_code == 200 and r3.status_code == 200 and U("p2").credits == b2 + 10 and U("p3").credits == b3 + 10, "palier 500 : TOUS les joueurs (même sans Premium) reçoivent 10 crédits")
ok(claim("p2", "club", 0).status_code == 400, "réclamer deux fois : refusé")
c.post("/admin/pass-club", json={"packs": 3000}, headers=A); r = claim("p2", "club", 4); ok(r.status_code == 200 and r.json()["reward"]["pack"] == "rare" and r.json()["reward"]["item"]["id"] == "pass-club-stickers", "dernier palier : un pack rare, 30 crédits et les autocollants collectifs")
ok(c.post("/admin/pass-club", json={"goals": [500, 400, 1, 2, 3]}, headers=A).status_code == 422 and c.post("/admin/pass-club", json={"goals": [100, 200, 300, 400, 500]}, headers=A).status_code == 200 and [t["goal"] for t in st("p2")["current"]["club"]["tiers"]] == [100, 200, 300, 400, 500], "(admin) régler les paliers : croissants obligatoires ; nouveaux paliers pris en compte")
c.post("/admin/pass-club", json={"goals": [500, 1000, 1500, 2000, 3000]}, headers=A)

print("9) LE RATTRAPAGE (7 jours après la fin du mois)")
at(1, mo=12); g = st("p1"); ok(g["current"]["key"] == "2026-12" and g["current"]["theme"]["id"] == "noel" and g["previous"] and g["previous"]["key"] == "2026-11" and g["previous"]["catchup_until"].startswith("2026-12-08"), "le 1er décembre : nouveau Pass (Noël), et le Pass de novembre reste ouvert jusqu'au 8 décembre")
ok(g["previous"]["level"] == g["previous"]["points"] // 100 or g["previous"]["level"] == 30, "pendant le rattrapage, plus de limite par jour : tous les niveaux gagnés sont débloqués (niveau %d)" % g["previous"]["level"])
b = U("p1").credits; r = claim("p1", "free", 4, season="2026-11"); ok(r.status_code == 200 and r.json()["season"] == "2026-11", "récupérer une récompense de novembre le 1er décembre : OK")
ok(c.get("/me", headers=H["p1"]).json()["pass_todo"] >= 1, "le point rouge compte aussi les récompenses du rattrapage")
at(3, mo=12); u1 = U("p1"); BP.add_points(db, u1, "mission", 20, 80); db.commit(); ok(pts("p1", "2026-12") == 20 and pts("p1", "2026-11") == st("p1")["previous"]["points"], "les nouveaux points vont au Pass de décembre, pas à celui de novembre")
grant("p2", 3000); at(4, mo=12)   # (p2 a déjà 3000+ points en novembre)
db.expire_all(); r = db.query(BP.PassProgress).filter_by(user_id=U("p2").id, season="2026-11").first(); r.points = 3000; db.commit(); BP.tick(db)
db.expire_all(); ok(U("p2") and db.query(BP.PassProgress).filter_by(user_id=U("p2").id, season="2026-11").first().completed == 1, "le planificateur attribue l'étoile de novembre à p2 (3000 points) même sans connexion pendant le rattrapage")
at(9, mo=12); r = claim("p1", "free", 7, season="2026-11"); ok(r.status_code == 400 and "terminé" in r.json()["detail"], "le 9 décembre : le Pass de novembre est terminé, plus de récompense (« " + r.json()["detail"] + " »)")
ok(st("p1")["previous"] is None, "il disparaît de l'écran")

print("10) ADMINISTRATION")
ok(c.post("/admin/pass-theme", json={"month": "2026-12", "theme": "hiver"}).status_code == 403 and c.post("/admin/pass-theme", json={"month": "2026-12", "theme": "licorne"}, headers=A).status_code == 422 and c.post("/admin/pass-theme", json={"month": "décembre", "theme": "hiver"}, headers=A).status_code == 422, "thème du mois : 403 sans clé ; thème inconnu ou mois mal écrit : 422")
c.post("/admin/pass-theme", json={"month": "2026-12", "theme": "hiver"}, headers=A); ok(st("p1")["current"]["theme"]["id"] == "hiver" and st("p1")["current"]["levels"][0]["premium"]["item"] == "pass-hiver-1", "le thème de décembre passe à « hiver » : les objets changent")
ad = c.get("/admin/pass", headers=A).json(); ok(ad["theme"] == "hiver" and ad["next_theme"] == "hiver" or ad["next_theme"] in P.THEMES, f"vue d'ensemble admin : thème {ad['theme']}, {ad['players']} joueurs, {ad['premium']} Premium")
ok(any(x["action"] == "Thème du Pass de 2026-12 : hiver" for x in c.get("/admin/log", headers=A).json()), "les actions figurent dans le journal")
uid = U("p3").id; c.post("/admin/delete-user", json={"pseudo": "p3"}, headers=A); db.expire_all(); ok(db.query(BP.PassProgress).filter_by(user_id=uid).count() == 0 and db.query(BP.PassClaim).filter_by(user_id=uid).count() == 0, "supprimer un compte supprime sa progression et ses réclamations")
print("11) ACHETER UN NIVEAU (20 crédits)")
at(10, mo=12); H["p4"] = mk("p4", 100); H["p5"] = mk("p5", 10); H["p6"] = mk("p6", 100); H["p7"] = mk("p7", 100)
buy = lambda who: c.post("/pass/buy-level", headers=H[who])
ok(st("p4")["level_price"] == 20 and buy("p4").status_code == 200, "le Pass annonce le prix d'un niveau : 20 crédits")
db.expire_all(); r = c.get("/pass", headers=H["p4"]).json()["current"]; ok(U("p4").credits == 80 and pts("p4", "2026-12") == 100 and r["level"] == 1, "p4 achète un niveau depuis 0 point : 100 → 80 crédits, 100 points, niveau 1")
r = buy("p4").json(); ok(r["points"] == 200 and r["gained"] == 100 and r["credits"] == 60 and r["reached"] == 2, "un 2e achat : 200 points (+100), 60 crédits")
grant("p4", 50); r = buy("p4").json(); ok(pts("p4", "2026-12") == 300 and r["gained"] == 50 and r["credits"] == 40, "avec 250 points : l'achat donne seulement les 50 qui manquent pour atteindre le niveau 3 (300)")
for _ in range(2): buy("p4")
db.expire_all(); r = st("p4")["current"]; ok(pts("p4", "2026-12") == 500 and r["level"] == 5 and U("p4").credits == 0, "deux achats de plus avec les 40 crédits restants : 500 points (niveau 5), 0 crédit")
ok(buy("p4").status_code == 400 and "Il te faut 20 crédits" in buy("p4").json()["detail"] and pts("p4", "2026-12") == 500, "plus assez de crédits : refusé, rien n'est retiré")
ok(buy("p5").status_code == 400 and U("p5").credits == 10, "p5 (10 crédits) : refusé")
grant("p6", 1500); r = buy("p6").json(); ok(r["points"] == 1600 and r["opens_day"] == 16 and r["unlocked"] == 10, "acheter ne contourne pas le calendrier : 1600 points = niveau 16 qui s'ouvre le jour 16, mais le 10 du mois seuls 10 niveaux sont débloqués")
rr = claim("p6", "free", 13) ; ok(rr.status_code == 400 and "pas encore débloqué" in rr.json()["detail"], "le niveau 13 ne se récupère pas le 10 : « " + rr.json()["detail"] + " »")
at(31, mo=12); grant("p7", 2900); r = buy("p7").json(); st7 = st("p7"); ok(r["points"] == 3000 and r["unlocked"] == 30 and st7["current"]["completed"] and st7["stars"] == 1, "le 31, les 3000 points atteints en achetant le dernier niveau : Pass terminé, 1 étoile")
ok(buy("p7").status_code == 400 and "déjà atteint les 30 niveaux" in buy("p7").json()["detail"] and U("p7").credits == 80, "à 3000 points : « Tu as déjà atteint les 30 niveaux » ; rien n'est retiré")
ok(c.post("/pass/buy-level").status_code == 401, "sans compte : 401")

print(); print("BILAN (Pass de saison) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
