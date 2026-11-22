"""
Test : divisions de saison 1v1 (Fer < 800, Bronze 800, Argent 1000, Or 1200, Platine 1400, Diamant 1600, Champion 1800, Élite 2000+),
récompense de la première montée du mois (une fois par division et par saison, gardée en redescendant), rattrapage par /me, montée
pendant un match 1v1, meilleure division des saisons passées sur le profil, classement du mois.
Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import divisions as DV, duel_engine as DE, seasons, credit_log as CL
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
def mk(p, elo=1000):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first()
    u.credits = 1000; u.elo = elo
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]

print("1) SEUILS")
cases = {0: "fer", 799: "fer", 800: "bronze", 999: "bronze", 1000: "argent", 1199: "argent", 1200: "or", 1399: "or", 1400: "platine",
         1600: "diamant", 1799: "diamant", 1800: "champion", 1999: "champion", 2000: "elite", 3500: "elite"}
bad = {e: DV.division_of(e)["id"] for e, want in cases.items() if DV.division_of(e)["id"] != want}
ok(not bad, "les 8 divisions tombent aux bons Elo (%s)" % (bad or "fer < 800 … élite ≥ 2000"))
ok(DV.division_of(2600)["next"] is None and DV.division_of(1000)["next"]["id"] == "or", "pas de division au-dessus de l'Élite, ni de plafond d'Elo")
d = c.get("/divisions").json()
ok(len(d["divisions"]) == 8 and "me" not in d and d["divisions"][3]["reward"] == {"credits": 50}, "liste publique : 8 divisions avec leurs récompenses")

print("2) RATTRAPAGE : UN JOUEUR DÉJÀ À 1650")
H = {"dvhaut": mk("dvhaut", 1650)}
u = U("dvhaut"); cr0, rare0, match0 = u.credits, u.pack_state.rare_pack_tokens or 0, u.pack_state.match_pack_tokens or 0
me = c.get("/me", headers=H["dvhaut"]).json()
u = U("dvhaut")
ok(u.credits == cr0 + 300, "Or + Platine + Diamant d'un coup : 50 + 100 + 150 crédits (%d)" % (u.credits - cr0))
ok((u.pack_state.rare_pack_tokens or 0) == rare0 + 1 and (u.pack_state.match_pack_tokens or 0) == match0 + 1, "et un pack rare (Platine) et un pack match (Diamant)")
ok(me["division"]["division"]["id"] == "diamant" and me["division"]["next"]["id"] == "champion" and me["division"]["progress"] == 25, "/me : Diamant, 25 %% vers Champion (%s)" % me["division"]["progress"])
labels = [r.label for r in db.query(CL.CreditLog).filter_by(user_id=u.id).all()]
ok({"Division Or", "Division Platine", "Division Diamant"} <= set(labels), "chaque récompense est dans l'historique des crédits")
c.get("/me", headers=H["dvhaut"]); ok(U("dvhaut").credits == cr0 + 300, "une seule fois : un deuxième /me ne donne rien")
u = U("dvhaut"); u.elo = 1100; db.commit(); c.get("/me", headers=H["dvhaut"])
u = U("dvhaut"); u.elo = 1700; db.commit(); c.get("/me", headers=H["dvhaut"])
ok(U("dvhaut").credits == cr0 + 300, "redescendre en Argent puis remonter : pas de deuxième récompense ce mois-ci")
me = c.get("/me", headers=H["dvhaut"]).json()
ok(me["division"]["season_best"]["id"] == "diamant" and me["division"]["rewarded"] == ["or", "platine", "diamant"], "meilleure division du mois et récompenses prises")
u = U("dvhaut"); u.elo = 1100; db.commit()
ok(c.get("/me", headers=H["dvhaut"]).json()["division"]["division"]["id"] == "argent", "pas de protection : la division suit l'Elo")

print("3) MONTÉE PENDANT UN MATCH 1V1")
H["dva"] = mk("dva", 1790); H["dvb"] = mk("dvb", 1790)
c.get("/me", headers=H["dva"]); c.get("/me", headers=H["dvb"])               # (Or, Platine, Diamant déjà pris par le rattrapage)
goals = iter([2, 0, 2, 0])
DE.draw_goals = lambda xg: next(goals, 0)
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["dva"]).json()["id"]
r = c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["dvb"]).json()
win = "dvb" if r["score_challenger"] > r["score_defender"] else "dva"
lose = "dva" if win == "dvb" else "dvb"
up = r.get("divisions_up", {})
ok(r["score_challenger"] != r["score_defender"] and [x["id"] for x in up.get(win, [])] == ["champion"], "le gagnant passe 1800 : Champion, dans le résultat du match (%s)" % up)
ok(lose not in up, "le perdant ne monte pas")
from app.chat import ChatMessage
ok(db.query(ChatMessage).filter(ChatMessage.text.like("%" + win + " atteint la division Champion%")).count() == 1, "annonce dans le chat à partir de Champion")

print("4) SAISONS PASSÉES ET CLASSEMENT")
uid = U("dvhaut").id
DV.close(db, "2026-10", {uid: 1450}); db.add(DV.DivisionReached(user_id=uid, season="2026-09", division="or")); db.commit()
p = c.get("/users/dvhaut/profile").json()
ok(p["division"]["id"] == "argent" and [(h["season"], h["id"]) for h in p["division_history"]] == [("2026-10", "platine"), ("2026-09", "or")], "profil : division actuelle et meilleure division de chaque saison passée (%s)" % p["division_history"])
s = c.get("/duel/season").json()
row = next((x for x in s["standings"] if x["pseudo"] == win), None)
ok(row is not None and row["division"]["id"] == "champion", "classement du mois : la division à côté de l'Elo")

print("5) SUPPRESSION")
DV.on_user_deleted(db, uid); db.commit()
ok(db.query(DV.DivisionReached).filter_by(user_id=uid).count() == 0, "compte supprimé : ses divisions partent avec lui")

print(); print("BILAN (divisions) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
