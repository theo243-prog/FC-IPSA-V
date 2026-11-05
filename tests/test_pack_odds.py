"""
Test : chances EFFECTIVES de chaque rareté par carte tirée (calculées à partir des poids, sans tirage au hasard) pour les packs
classique, match et ultra, avec et sans édition limitée en cours ; et la commande d'administration « Ajouter des cartes gold ».
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import game_logic as GL
from app.models import Card, Player, Tier, Match
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
COUNTS = {"commune": 60, "rare": 60, "gold": 120, "speciale": 20, "epique": 20, "legendaire": 10, "halloween": 20, "secrete": 60}     # toutes les raretés en nombre suffisant
real_status = GL.edition_status


def odds(kind, edition, counts=COUNTS):
    GL.edition_status = (lambda db, k, today=None: "active" if (edition and k == "halloween") else "upcoming")
    try:
        spec = GL.PACK_TYPES[kind]
        w = GL.classic_tier_weights(counts, GL.weights_with_editions(None, spec.get("weights") or GL.TIER_WEIGHTS, kind, counts))
    finally:
        GL.edition_status = real_status
    tot = sum(w.values())
    return {t: 100 * v / tot for t, v in w.items()}, w


near = lambda a, b, eps=0.01: abs(a - b) <= eps

print("1) PACK CLASSIQUE")
p, _ = odds("classique", True)
ok(near(p["gold"], 8.0) and near(p["halloween"], 3.5), "avec une édition : gold %.2f %% (8 %%), édition %.2f %% (3,5 %%)" % (p["gold"], p["halloween"]))
ok(near(p["rare"] / p["epique"], 9) and near(p["epique"] / p["legendaire"], 4) and "speciale" not in p, "rare, épique et légendaire gardent leurs rapports (18 / 2 / 0,5) ; pas de spéciale")
ok(near(sum(GL.TIER_WEIGHTS.values()), 100), "les poids de départ font 100 (la commune absorbe la différence)")
q, _ = odds("classique", False)
ok(near(q["gold"], 8.29) and "halloween" not in q and near(q["commune"], 71.21), "sans édition : gold 8,29 %%, commune 71,21 %% (%.2f)" % q["commune"])

print("2) PACK MATCH")
p, _ = odds("match", True)
ok(near(p["gold"], 10.0) and near(p["halloween"], 6.0), "avec une édition : gold %.2f %% (10 %%), édition %.2f %% (6 %%)" % (p["gold"], p["halloween"]))
ok(near(GL.PACK_TYPES["match"]["weights"]["speciale"], 8) and near(p["speciale"], 7.52), "poids de la spéciale inchangé (8) : %.2f %% pendant une édition" % p["speciale"])
ok(near(p["rare"] / p["epique"], 7.5) and near(p["epique"] / p["legendaire"], 4), "rare, épique et légendaire gardent leurs rapports (30 / 4 / 1)")
q, _ = odds("match", False)
ok(near(q["gold"], 10.64) and "halloween" not in q, "sans édition : gold 10,64 %")

print("3) PACK ULTRA (case « gold, édition limitée ou mieux »)")
_, w = odds("ultra", True)
s = GL._slot_weights(w, "edition_min"); t = sum(s.values()); s = {k: 100 * v / t for k, v in s.items()}
ok(set(s) == {"gold", "halloween", "epique", "legendaire"}, "la case tire parmi gold, édition, épique et légendaire")
ok(near(s["halloween"], 25.16, 0.05) and near(s["gold"], 57.51, 0.05), "avec une édition : édition %.2f %%, gold %.2f %%, épique %.2f %%, légendaire %.2f %%" % (s["halloween"], s["gold"], s["epique"], s["legendaire"]))
_, w = odds("ultra", False)
s = GL._slot_weights(w, "edition_min"); t = sum(s.values()); s = {k: 100 * v / t for k, v in s.items()}
ok(near(s["gold"], 76.83, 0.05) and near(s["epique"], 18.54, 0.05), "sans édition : gold %.2f %%, épique %.2f %%, légendaire %.2f %%" % (s["gold"], s["epique"], s["legendaire"]))
ok(GL.PACK_TYPES["ultra"]["slots"] == [(1, "epique_legendaire"), (1, "edition_min"), (2, "rare_plus"), (6, "toutes")] and "1 gold, édition limitée ou mieux" in GL.PACK_TYPES["ultra"]["description"], "structure du pack ultra inchangée, description exacte")

print("4) RÈGLES INCHANGÉES")
ok({k: GL.TIER_REF_COUNT[k] for k in ("gold", "speciale", "epique", "legendaire", "halloween", "noel")} == {"gold": 6, "speciale": 6, "epique": 6, "legendaire": 3, "halloween": 5, "noel": 5}, "réductions par nombre de cartes inchangées")
_, w3 = odds("classique", True, dict(COUNTS, gold=3))
ok(near(w3["gold"] / odds("classique", True)[1]["gold"], 0.5, 0.001), "avec 3 cartes gold seulement (sur 6 de référence), le gold est réduit de moitié")
ok(GL.EDITION_SHARE == {"classique": 0.035, "match": 0.06}, "part de l'édition en cours : 3,5 % / 6 %")
r = c.get("/game/rules").json()
ok(r["edition_share_pct"] == {"classique": 3.5, "match": 6.0}, "les aides du site reçoivent ces parts")

print("5) AJOUTER DES CARTES GOLD SANS MATCH")
g0, m0 = db.query(Card).filter_by(tier=Tier.gold).count(), db.query(Match).count()
ok(c.post("/admin/create-gold", json={"moments": [{"player_name": "Mathis", "action": "Petit pont"}]}).status_code == 403, "clé admin obligatoire")
r = c.post("/admin/create-gold", json={"moments": [{"player_name": "Mathis", "action": "Petit pont"}, {"player_name": "Lucas", "action": "  Reprise   de volée "}]}, headers=A)
ok(r.status_code == 200 and r.json()["gold_cards_created"] == ["Petit pont — Mathis", "Reprise de volée — Lucas"], "deux cartes gold « Action — Joueur » créées : %s" % r.json().get("gold_cards_created"))
db.expire_all()
ok(db.query(Card).filter_by(tier=Tier.gold).count() == g0 + 2 and db.query(Match).count() == m0, "aucun match enregistré")
mp = db.query(Player).filter_by(name="Petit pont — Mathis").first(); ok(mp.poste == "MOMENT" and mp.photo_url == db.query(Player).filter_by(name="Mathis").first().photo_url, "fiche MOMENT avec la photo du joueur")
r = c.post("/admin/create-gold", json={"moments": [{"player_name": "Mathis", "action": "Petit pont"}], "date": "2026-11-08"}, headers=A)
ok(r.json()["gold_cards_created"] == ["Petit pont — Mathis (08/11)"], "même moment une 2e fois : distingué par la date")
g1 = db.query(Card).filter_by(tier=Tier.gold).count()
r = c.post("/admin/create-gold", json={"moments": [{"player_name": "Hugo", "action": "Sauvetage"}, {"player_name": "Personne", "action": "Lob"}]}, headers=A)
db.expire_all(); ok(r.status_code == 404 and db.query(Card).filter_by(tier=Tier.gold).count() == g1, "une ligne fausse (joueur inconnu) : rien n'est créé")
ok(c.post("/admin/create-gold", json={"moments": [{"player_name": "Hugo", "action": " "}]}, headers=A).status_code == 400 and c.post("/admin/create-gold", json={"moments": []}, headers=A).status_code == 400, "action vide ou liste vide : refusé")
db.add(Player(name="Fan Test", poste="FAN")); db.commit()
ok(c.post("/admin/create-gold", json={"moments": [{"player_name": "Fan Test", "action": "Tifo"}]}, headers=A).status_code == 400, "un fan n'a pas de moment gold")
r = c.post("/admin/record-match", json={"date": "2026-11-09", "opponent": "Test", "score_us": 1, "score_them": 0, "moments": [{"player_name": "Hugo", "action": "Sauvetage"}]}, headers=A)
ok(r.status_code == 200 and r.json()["gold_cards_created"] == ["Sauvetage — Hugo"], "l'enregistrement d'un match crée toujours ses cartes gold (même fonction)")
print("BILAN (chances des packs et cartes gold) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
