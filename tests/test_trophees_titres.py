"""
Test : chaque carte trophée possédée (podium de saison, tournoi, assidus, lanterne rouge) donne un titre à son nom ; podium de saison payé
300 / 200 / 100 crédits ; statistiques de fin de match cohérentes avec la simulation. Lancé par tests/run_tests.py.
"""
import random
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import seasons as S, cosmetics as CO, duel_engine as DE
from app.models import User, Duel
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
H = {}
for p in ("p1", "p2", "p3", "p4", "p5"):
    H[p] = {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]}
KEY = "2026-09"; t = [0]
def duel(a, b, elo_a, elo_b):
    t[0] += 1
    db.add(Duel(challenger_id=U(a).id, defender_id=U(b).id, stake=1, formation_challenger="1-2-1", formation_defender="1-2-1", score_challenger=1, score_defender=0,
                elo_challenger_before=1000, elo_defender_before=1000, elo_challenger_after=elo_a, elo_defender_after=elo_b, created_at=datetime(2026, 9, 10, 12, 0, t[0])))
for _ in range(5): duel("p1", "p5", 1200, 800)
for _ in range(5): duel("p2", "p4", 1100, 950)
for _ in range(5): duel("p3", "p4", 1050, 940)
db.commit()

print("1) PODIUM DE SAISON MIEUX PAYÉ")
before = {p: U(p).credits for p in H}
S.close_season(db, KEY); db.commit()
gain = {p: U(p).credits - before[p] for p in H}
ok(S.PODIUM_CREDITS == {1: 300, 2: 200, 3: 100} and (gain["p1"], gain["p2"], gain["p3"]) == (300, 200, 100), "1er +300, 2e +200, 3e +100 crédits (avant 100 / 60 / 30) : %s" % gain)

print("2) UN TITRE PAR CARTE TROPHÉE")
titles = lambda p: {t["label"]: t for t in c.get("/cosmetics", headers=H[p]).json()["titles"]}
t1 = titles("p1")
ok(t1.get("Vainqueur de saison (septembre 2026)", {}).get("unlocked") and t1["Vainqueur de saison (septembre 2026)"]["trophy"], "le 1er a le titre « Vainqueur de saison (septembre 2026) »")
ok("Joueur le plus assidu de la saison (septembre 2026)" in titles("p4"), "p4 (10 matchs) a le titre de sa carte « Joueur le plus assidu de la saison »")
t5 = titles("p5")
ok("Lanterne rouge de la saison (septembre 2026)" in t5, "la lanterne rouge a son titre (seulement une fois la carte reçue)")
ok(not any("Lanterne rouge" in k for k in t1) and not any("Lanterne rouge" in k for k in titles("p2")), "les autres ne voient jamais le titre de la lanterne rouge, même verrouillé : la surprise reste entière")
ok("Vainqueur de saison (septembre 2026)" not in titles("p2"), "pas de titre pour un trophée qu'on n'a pas")
tid = t1["Vainqueur de saison (septembre 2026)"]["id"]
ok(c.post("/cosmetics", json={"title": tid}, headers=H["p2"]).status_code == 400, "choisir le titre d'un trophée qu'on n'a pas : refusé")
r = c.post("/cosmetics", json={"title": tid}, headers=H["p1"])
ok(r.status_code == 200 and r.json()["title"] == "Vainqueur de saison (septembre 2026)", "le 1er le choisit")
ok(c.get("/users/p1/profile").json().get("title") == "Vainqueur de saison (septembre 2026)", "il s'affiche sur le profil")
ok(CO.display_map(db)[U("p1").id][0] == "Vainqueur de saison (septembre 2026)", "… et dans le classement et le chat")
ok(c.post("/admin/give-trophies", json={"pseudo": "p4", "month": "2026-08", "ranks": [11]}, headers={"X-Admin-Key": "k"}).status_code == 200
   and "Demi-finaliste du tournoi (août 2026)" in titles("p4"), "carte « Demi-finaliste du tournoi » : elle donne aussi son titre")

print("3) STATISTIQUES DE FIN DE MATCH")
def members(note):
    return [{"slot": s, "effective": note, "player": "J%d" % i, "tier": "rare", "poste": s, "base_note": note, "out_of_position": False, "captain": False}
            for i, s in enumerate(("GB", "DEF", "MC", "MC", "ATT"))]
bad = []
for seed in range(400):
    random.seed(seed)
    a = {"pseudo": "A", "formation": "1-2-1", "tactic": random.choice(["pressing", "possession", "contre"]), "members": members(random.choice([75, 85, 90]))}
    b = {"pseudo": "B", "formation": random.choice(["2-1-1", "1-2-1", "1-1-2"]), "tactic": random.choice(["pressing", "possession", "contre"]), "members": members(random.choice([75, 85, 90]))}
    xa, xb = DE.expected_goals(85, 85), DE.expected_goals(80, 88)
    ga, gb = DE.draw_goals(xa), DE.draw_goals(xb)
    ev = DE.build_events(a, b, ga, gb, xa, xb, None)
    st = DE.match_stats(a, b, ev, xa, xb)
    goals = (ga, gb)
    for i in (0, 1):
        if not (st["shots"][i] >= st["on_target"][i] >= goals[i] and st["on_target"][i] - goals[i] == st["saves"][1 - i] and 0 <= st["yellow"][i] <= 3):
            bad.append((seed, i, st, goals))
    if sum(st["possession"]) != 100 or not (30 <= st["possession"][0] <= 70):
        bad.append((seed, "poss", st))
ok(not bad, "400 matchs : tirs ≥ tirs cadrés ≥ buts, tirs cadrés = buts + arrêts du gardien adverse, possession 30-70 % et total 100 %" + (" %s" % bad[:2] if bad else ""))
random.seed(1)
strong = {"pseudo": "A", "formation": "1-2-1", "tactic": "possession", "members": members(90)}
weak = {"pseudo": "B", "formation": "1-2-1", "tactic": "contre", "members": members(75)}
pos = [DE.match_stats(strong, weak, [], 2, 1)["possession"][0] for _ in range(200)]
ok(sum(pos) / len(pos) > 60, "un meilleur milieu qui joue la possession garde le ballon (%.0f %% en moyenne)" % (sum(pos) / len(pos)))
press = {**weak, "tactic": "pressing"}
f = [DE.match_stats(strong, press, [], 2, 1)["fouls"] for _ in range(200)]
ok(sum(x[1] for x in f) > sum(x[0] for x in f), "le pressing fait plus de fautes")

print(); print("BILAN (titres des trophées, podium, statistiques) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
