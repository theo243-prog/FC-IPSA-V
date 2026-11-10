"""
Test : succès retravaillés (novembre 2026). 16 nouveaux succès du court au long terme, un niveau de plus pour packs, matchs, victoires,
série et doublons (le titre « maître » reste à l'ancien dernier niveau), crédits par niveau 5 / 10 / 20 / 35 / 60, mesures calculées à
partir du jeu, une seule annonce dans le chat par vérification. Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import profiles as P, cosmetics as C, prono, club, card_levels as CL, chat
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
L = {l["id"]: l for l in P.LADDERS}

print("1) LA LISTE DES SUCCÈS")
new_ids = ["evolution", "niveau_max", "pronos", "scores_exacts", "minijeu", "electeur", "club", "club_difficile", "encheres", "echanges", "tournoi",
           "stars", "completion", "pass", "podiums", "numerotees"]
ok(all(i in L for i in new_ids) and len(P.LADDERS) == 30, "16 nouveaux succès (30 au total)")
ok(P.total_levels() == 108, "108 niveaux au total (47 avant)")
ok(max(L["pronos"]["goals"]) == 5 and max(L["electeur"]["goals"]) == 5 and max(L["pass"]["goals"]) == 5 and max(L["podiums"]["goals"]) == 5, "pronostics, votes, Pass terminés et podiums : palier maximal 5")
ok(L["packs"]["goals"] == [10, 50, 150, 500, 1500] and L["packs"]["master_at"] == 4 and L["doublons"]["goals"] == [10, 50, 200, 1000] and L["doublons"]["master_at"] == 3,
   "packs et doublons : un niveau de plus, le titre maître reste à l'ancien dernier niveau")
ok(P.LEVEL_REWARD == {"Bronze": 5, "Argent": 10, "Or": 20, "Diamant": 35, "Légende": 60}, "crédits par niveau : 5 / 10 / 20 / 35 / 60")
titles = {t[0]: t for t in C._title_catalog()}
ok(all(i + "_max" in titles for i in new_ids) and len({t[1] for t in titles.values()}) == len(titles), "chaque nouveau succès a son titre maître, sans titre en double")
ok(titles["packs_max"][3]({"levels": {"packs": 4}}) and not titles["packs_max"][3]({"levels": {"packs": 3}}), "le titre « Machine à packs » reste au niveau 4 (Diamant)")

print("2) MESURES ET ATTRIBUTION")
t = c.post("/auth/register", json={"pseudo": "ana", "password": "test1234"}).json()["token"]; H = {"Authorization": "Bearer " + t}
u = U("ana")
for k in range(3):
    db.add(prono.PronoBet(upcoming_id="m%d" % k, user_id=u.id, score_us=1, score_them=0, stake=1, status="won", exact=1 if k == 0 else 0, match_label="Match", match_date="2026-11-01"))
for k in range(6):
    db.add(club.ClubMatch(user_id=u.id, day="2026-11-0%d" % (k + 1), level="difficile" if k < 2 else "facile", result="victoire", score_user=2, score_club=1))
hugo = db.query(Card).join(Player).filter(Player.name == "Hugo", Card.tier == Tier.commune).first()
db.add(OwnedCard(user_id=u.id, card_id=hugo.id, quantity=1)); db.flush(); CL.set_level(db, u.id, hugo.id, 5); db.commit()
m = P.metrics(db, U("ana"))
ok(m["pronos"] == 3 and m["exact"] == 1 and m["club_wins"] == 6 and m["club_hard"] == 2 and m["level_sum"] == 5 and m["max_level_cards"] == 1,
   "les mesures comptent ce qui a déjà été fait (3 pronostics, 1 score exact, 6 victoires contre le club dont 2 en Difficile, une carte niveau 5)")
c0 = U("ana").credits
new = P.check(db, U("ana")); got = {(x["id"], x["level"]) for x in new}
ok(("pronos", 2) in got and ("scores_exacts", 1) in got and ("club", 1) in got and ("club_difficile", 1) in got and ("niveau_max", 1) in got and ("evolution", 1) in got,
   "les niveaux atteints sont donnés d'un coup : %s" % sorted(got))
ok(U("ana").credits - c0 == sum(x["reward"] for x in new) and all(x["reward"] in (5, 10, 20, 35, 60) for x in new), "avec leurs crédits (%d)" % (U("ana").credits - c0))
ok(P.check(db, U("ana")) == [], "rien n'est donné deux fois")
b = {x["id"]: x for x in c.get("/badges", headers=H).json()}
ok(b["pronos"]["level"] == 2 and b["pronos"]["next_goal"] == 5 and b["completion"]["unit"] == "% du jeu", "la page des succès montre l'avancement (pronostics : 3 sur 5)")

print("BILAN (succès) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
