"""
Test : forme des cartes en 1v1 (barre de fatigue). Chaque match 1v1 fait perdre 1 % de forme à chaque carte alignée des deux équipes ;
la forme multiplie la note (après le niveau, avant le malus hors poste et le capitaine) ; remise à 100 % à minuit (jour de Paris) ;
jamais sous 50 % ; le tournoi et le défi du club jouent à 100 % sans fatiguer. Lancé par tests/run_tests.py.
"""
from datetime import timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import fatigue as FA, duel_engine as DE, game_logic as GL, tournament as TN, card_levels as CL
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); real_today, real_draw = GL.today_paris, DE.draw_goals
card = lambda n, t="commune": db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
CORE = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 500
    for n, _ in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.add(OwnedCard(user_id=u.id, card_id=card("Sacha").id, quantity=1))            # un 2e gardien
    db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("ana", "bob")}
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": s} for n, s in CORE]}
DE.draw_goals = lambda xg: 1
def duel():
    pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["ana"]).json()["id"]
    return c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["bob"]).json()
forms = lambda p: (db.expire_all(), FA.forms_for(db, U(p).id))[1]
col = lambda p: {x["player_name"]: x for x in c.get("/collection", headers=H[p]).json() if x.get("quantity") and x["tier"] == "commune"}

print("1) UN MATCH 1v1 FATIGUE LES DEUX ÉQUIPES")
ok(forms("ana") == {} and col("ana")["Mathis"]["form"] == 100, "au départ : toutes les cartes à 100 %")
r = duel()
ok(all(m["form"] == 100 for side in ("challenger", "defender") for m in r["lineups"][side]["players"]), "1er match : joué à 100 % de forme")
fa, fb = forms("ana"), forms("bob")
ok(set(fa) == {card(n).id for n, _ in CORE} and all(abs(v - 0.99) < 1e-9 for v in fa.values()) and len(fb) == 5, "après le match : les 5 cartes de chaque équipe sont à 99 %")
ok(card("Sacha").id not in fa and col("ana")["Sacha"]["form"] == 100, "une carte qui n'a pas joué reste à 100 %")
for _ in range(4): r = duel()
m = {x["player"]: x for x in r["lineups"]["defender"]["players"]}
ok(m["Hugo"]["form"] == 96 and abs(m["Hugo"]["effective_note"] - 75 * 0.96) < 0.06, "5e match : joué à 96 %% (note 75 -> %.1f)" % m["Hugo"]["effective_note"])
ok(col("ana")["Hugo"]["form"] == 95, "après 5 matchs : forme 95 % dans la collection")

print("2) LA FORME DANS LE CALCUL DE LA NOTE")
lc = card("Lucas")
mem = DE.build_members([(lc, "MC")], lc.id, {lc.id: 5}, {lc.id: 0.9})[0]
ok(abs(mem["effective"] - (75 + 8) * 0.9 * 0.9 * 1.1) < 1e-9 and mem["base_note"] == 83 and mem["form"] == 90, "note 75 + niveau 5 (+8) = 83, × forme 90 %, puis −10 % hors poste, puis +10 % capitaine")
ok(DE.build_members([(lc, "ATT")], None)[0]["effective"] == 75, "sans forme indiquée : 100 %")

print("3) JAMAIS SOUS 50 %, REMISE À 100 % À MINUIT")
ok(FA.form_from_matches(50) == 0.5 and FA.form_from_matches(80) == 0.5 and FA.form_from_matches(10) == 0.9, "50 matchs : 50 % ; 80 matchs : toujours 50 % ; 10 matchs : 90 %")
GL.today_paris = lambda: real_today() + timedelta(days=1)
ok(forms("ana") == {} and col("ana")["Hugo"]["form"] == 100, "le lendemain (minuit à Paris) : toutes les cartes à 100 %")
r = duel(); ok(all(m["form"] == 100 for m in r["lineups"]["defender"]["players"]) and all(abs(v - 0.99) < 1e-9 for v in forms("ana").values()), "1er match du nouveau jour : 100 %, puis 99 %")
GL.today_paris = real_today

print("4) TOURNOI ET DÉFI DU CLUB : 100 %, SANS FATIGUE")
spec = {**team, "captain_card_id": None}
prep = TN._prepare(db, U("ana"), spec)
ok(all("form" in m and m["form"] == 100 for m in prep[0]["members"]), "tournoi : les cartes fatiguées jouent à 100 %")
before = dict(forms("ana")); res = TN.simulate(prep, TN._prepare(db, U("bob"), spec)); db.commit()
ok(forms("ana") == before, "un match de tournoi ne fatigue pas")
from app import club as CLB
CLB.today = lambda: "2026-11-12"
lv = c.get("/club", headers=H["ana"]).json()["levels"][0]["level"]
r = c.post("/club/%s/play" % lv, json=team, headers=H["ana"])
ok(r.status_code == 200 and all(m["form"] == 100 for m in r.json()["lineups"]["challenger"]["players"]) and forms("ana") == before, "défi du club : 100 % de forme et aucune fatigue")
DE.draw_goals = real_draw
print("5) FAN, LOUP ET ÉQUIPEMENT SE FATIGUENT AUSSI")
GL.today_paris = lambda: real_today() + timedelta(days=3)
fanp = Player(name="Fan Fatigue", poste="FAN"); eqp = Player(name="Gourde Test", poste="EQUIPEMENT"); db.add_all([fanp, eqp]); db.flush()
fcard = Card(player_id=fanp.id, tier=Tier.rare, vitesse=0, tir=0); ecard = Card(player_id=eqp.id, tier=Tier.rare, vitesse=0, tir=0); db.add_all([fcard, ecard]); db.flush()
db.add(OwnedCard(user_id=U("ana").id, card_id=fcard.id, quantity=1)); db.add(OwnedCard(user_id=U("ana").id, card_id=ecard.id, quantity=1)); db.commit()
fteam = {**team, "fan_card_id": fcard.id, "equipment_card_ids": [ecard.id]}
for i in range(3):
    DE.draw_goals = lambda xg: 1; pid = c.post("/duel/proposals", json={**fteam, "stake": 1}, headers=H["ana"]).json()["id"]; r = c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["bob"]).json()
fa = forms("ana")
ok(abs(fa.get(fcard.id, 1) - 0.973) < 1e-9 and abs(fa.get(ecard.id, 1) - 0.973) < 1e-9, "après 3 matchs avec un équipement rare (-10 % de fatigue) : le Fan et l'équipement sont à 97,3 %")
ok(r["lineups"]["defender"]["fan"]["form"] == 98 and r["lineups"]["defender"]["equipment"][0]["form"] == 98, "3e match : joué avec un Fan et un équipement à 98 % (affiché dans le récit)")
cf = {x["player_name"]: x for x in c.get("/collection", headers=H["ana"]).json() if x.get("quantity")}
ok(cf["Fan Fatigue"]["form"] == 97 and cf["Gourde Test"]["form"] == 97, "la collection montre leur forme arrondie (barre de fatigue : 97 %)")
mem = [{"slot": "ATT", "effective": 80}, {"slot": "GB", "effective": 80}]
a0 = DE.team_powers(mem, fcard, 1.0, [ecard], None, 0.0)[0]; a1 = DE.team_powers(mem, fcard, 1.0, [ecard], None, 0.0, {fcard.id: 0.5, ecard.id: 0.5})[0]
fb, eb = GL.TIER_FAN_BONUS["rare"], GL.TIER_EQUIPMENT_BONUS["rare"]
ok(abs(a1 / a0 - (1 + (fb + eb) * 0.5) / (1 + fb + eb)) < 1e-9, "le bonus du Fan et de l'équipement est multiplié par leur forme")
GL.today_paris = real_today
print("6) NETTOYAGE")
ok(c.get("/duel/config").json().get("form_loss_per_match") == 0.01, "le site reçoit la règle (1 % par match)")
c.post("/admin/delete-user", json={"pseudo": "bob"}, headers={"X-Admin-Key": "k"}); db.expire_all()
ok(db.query(FA.CardFatigue).filter(~FA.CardFatigue.user_id.in_([u.id for u in db.query(User).all()])).count() == 0, "compte supprimé : la forme de ses cartes aussi")
print("BILAN (forme des cartes) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
