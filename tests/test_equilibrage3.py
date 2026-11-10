"""
Test : équilibrage de novembre 2026. Légendaires à 90 (et -5, une seule fois, sur celles qui ont leur propre note), spéciales jusqu'à 99,
formation d'un défi cachée aux autres joueurs, avantage du terrain du créateur (+1 %), Elo moins punitif (échelle 800, perte plafonnée à 20,
créateur -25 % de perte, victoire x1,25). Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import duel_engine as DE, game_logic as GL
from app.models import User, Card, Player, OwnedCard, Tier, JobRun
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); real_draw, real_xg = DE.draw_goals, DE.expected_goals
card = lambda n, t="commune": db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
CORE = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 500
    for n, _ in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("ana", "bob")}
team = {"formation": "1-1-2", "tactic": "contre", "slots": [{"card_id": card(n).id, "slot_category": s} for n, s in
                                                          (("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "ATT"), ("Lucas", "ATT"))]}

print("1) LÉGENDAIRES À 90, SPÉCIALES JUSQU'À 99")
ok(GL.CARD_NOTE["legendaire"] == 90 and GL.SPECIAL_MAX_NOTE == 99, "légendaire 90 (avant 95), spéciale au plus 99 (avant 90)")
p1, p2 = Player(name="Légende A", poste="ATT"), Player(name="Légende B", poste="ATT"); db.add_all([p1, p2]); db.flush()
la, lb = Card(player_id=p1.id, tier=Tier.legendaire, vitesse=0, tir=0, note=99), Card(player_id=p2.id, tier=Tier.legendaire, vitesse=0, tir=0); db.add_all([la, lb]); db.commit()
db.query(JobRun).filter_by(name="legendaires_90").delete(); db.commit()
n = GL.lower_legendary_notes(db); again = GL.lower_legendary_notes(db); db.expire_all()
ok(n == 1 and again == 0 and la.note == 94 and lb.note is None and GL.card_note(p2, "legendaire", lb) == 90, "légendaire avec sa propre note : -5 une seule fois (99 -> 94) ; sans note propre : 90")
ok(GL.PACK_TYPES["match"]["weights"]["speciale"] == 11, "spéciale plus fréquente dans le pack match (poids 11, avant 8)")

print("2) DÉFI : FORMATION CACHÉE, AVANTAGE DU TERRAIN")
pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["ana"]).json()["id"]
seen_bob = [p for p in c.get("/duel/proposals", headers=H["bob"]).json() if p["id"] == pid][0]
seen_anon = [p for p in c.get("/duel/proposals").json() if p["id"] == pid][0]
seen_ana = [p for p in c.get("/duel/proposals", headers=H["ana"]).json() if p["id"] == pid][0]
ok("formation" not in seen_bob and "formation" not in seen_anon and "tactic" not in seen_bob, "un autre joueur (ou sans compte) ne voit ni la formation ni la tactique du défi")
ok(seen_ana.get("formation") == "1-1-2", "le créateur voit sa formation")
ok(DE.HOME_BONUS == 0.01 and c.get("/duel/config").json()["home_bonus"] == 0.01, "avantage du terrain : +1 %")
calls = []
DE.expected_goals = lambda a, d: (calls.append((a, d)), real_xg(a, d))[1]; DE.draw_goals = lambda xg: 1
r = c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["bob"]).json()
DE.expected_goals, DE.draw_goals = real_xg, real_draw
(att_c, def_d), (att_d, def_c) = calls[0], calls[1]
ok(abs(att_d / att_c - 1.01) < 1e-9 and abs(def_d / def_c - 1.01) < 1e-9, "même équipe, même tactique : le créateur a +1 % en attaque et en défense")
ok(r["lineups"]["defender"]["home_bonus_pct"] == 1 and r["lineups"]["defender"]["referee_bonus_pct"] == 0 and "home_bonus_pct" not in r["lineups"]["challenger"], "le récit l'affiche pour le créateur seulement (sans le compter comme l'arbitre)")
ok(r["lineups"]["defender"]["formation"] == "1-1-2", "après le match, la formation du créateur est dévoilée dans le récit")
from app import tournament as TN
a = TN.simulate(TN._prepare(db, U("ana"), {**team, "captain_card_id": None}), TN._prepare(db, U("bob"), {**team, "captain_card_id": None}))
ok("home_bonus_pct" not in a["lineups"]["defender"], "tournoi : pas d'avantage du terrain")

print("3) ELO MOINS PUNITIF")
ok((DE.ELO_SCALE, DE.ELO_MAX_LOSS, DE.ELO_CREATOR_LOSS_FACTOR, DE.ELO_WIN_BOOST) == (800, 20, 0.75, 1.25), "échelle 800, perte au plus 20, créateur -25 %, victoire x1,25")
ok(DE.elo_update(1000, 1000, 1) == (1020, 984), "à Elo égal : victoire +20, défaite -16")
ok(DE.elo_update(1000, 1000, 0, b_is_creator=True) == (984, 1020), "à Elo égal, le créateur qui gagne prend +20 et le challenger perd -16")
ok(DE.elo_delta(1400, 1000, 0) == -20 and DE.elo_delta(1400, 1000, 0, True) == -15, "favori de 400 points battu : -20 (au lieu de -29), -15 s'il est le créateur du défi")
ok(DE.elo_delta(1000, 1400, 1) == 30 and DE.elo_delta(1400, 1000, 1) == 10, "l'outsider qui gagne : +30 ; le favori qui gagne : +10")
ok(DE.elo_delta(1000, 1000, 0.5) == 0, "nul à Elo égal : 0")
ok(all(DE.elo_delta(a, b, 0, cr) >= -20 for a in range(800, 2001, 100) for b in range(800, 2001, 100) for cr in (False, True)), "jamais plus de 20 points perdus")
ok(U("bob").elo == 1000 + DE.elo_delta(1000, 1000, 0.5) and U("ana").elo == 1000, "le match nul de la section 2 : Elo inchangé pour les deux")

print("BILAN (équilibrage de novembre) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
