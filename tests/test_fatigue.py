"""
Test : forme des cartes en 1v1 (barre de fatigue). Chaque match 1v1 fait perdre 0,5 % de forme (depuis le 14/11/2026) à chaque carte alignée
des deux équipes ; la forme remonte de 1 % par heure, en continu ; elle multiplie la note (après le niveau, avant le malus hors poste et le
capitaine) ; jamais sous 50 % ; le tournoi et le défi du club jouent à 100 % sans fatiguer. Lancé par tests/run_tests.py.
"""
from datetime import datetime, timedelta
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
CLOCK = [datetime(2026, 11, 20, 10, 0)]; FA._now = lambda: CLOCK[0]            # horloge de la forme (figée, avancée à la main)
def later(h): CLOCK[0] += timedelta(hours=h)
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
ok({card(n).id for n, _ in CORE} <= set(fa) and all(abs(v - 0.995) < 1e-9 for v in fa.values()) and {card(n).id for n, _ in CORE} <= set(fb), "après le match : les 5 cartes de chaque équipe sont à 99,5 %")
ok(abs(fa[card("Mathis", "rare").id] - 0.995) < 1e-9 and card("Mathis", "rare").id not in [s["card_id"] for s in team["slots"]], "forme PAR PERSONNE : la rare de Mathis (pas jouée) est aussi à 99,5 %, comme sa commune")
ok(card("Adrien").id not in fa if card("Adrien") else True, "une personne qui n'a pas joué reste à 100 %")
ok(card("Sacha").id not in fa and col("ana")["Sacha"]["form"] == 100, "une carte qui n'a pas joué reste à 100 %")
for _ in range(4): r = duel()
m = {x["player"]: x for x in r["lineups"]["defender"]["players"]}
ok(m["Hugo"]["form"] == 98 and abs(m["Hugo"]["effective_note"] - 75 * 0.98) < 0.06, "5e match : joué à 98 %% (note 75 -> %.1f)" % m["Hugo"]["effective_note"])
ok(col("ana")["Hugo"]["form"] == 97.5 and col("ana")["Hugo"]["form_full_in"] == 150, "après 5 matchs : forme 97,5 % dans la collection (au dixième près), pleine forme dans 2 h 30")

print("2) LA FORME DANS LE CALCUL DE LA NOTE")
lc = card("Lucas")
mem = DE.build_members([(lc, "MC")], lc.id, {lc.id: 5}, {lc.id: 0.9})[0]
ok(abs(mem["effective"] - (75 + 8) * 0.9 * 0.9 * 1.1) < 1e-9 and mem["base_note"] == 83 and mem["form"] == 90, "note 75 + niveau 5 (+8) = 83, × forme 90 %, puis −10 % hors poste, puis +10 % capitaine")
ok(DE.build_members([(lc, "ATT")], None)[0]["effective"] == 75, "sans forme indiquée : 100 %")

print("3) RÉCUPÉRATION DE 1 % PAR HEURE, JAMAIS SOUS 50 %")
ok(FA.form_from_matches(100) == 0.5 and FA.form_from_matches(160) == 0.5 and FA.form_from_matches(10) == 0.95, "100 matchs d'affilée : 50 % ; 160 : toujours 50 % ; 10 matchs : 95 %")
later(1); ok(abs(forms("ana")[card("Hugo").id] - 0.985) < 1e-9 and col("ana")["Hugo"]["form_full_in"] == 90, "1 h plus tard : +1 % (97,5 % -> 98,5 %), pleine forme dans 1 h 30")
later(0.5); r = duel(); m = {x["player"]: x for x in r["lineups"]["defender"]["players"]}
ok(m["Hugo"]["form"] == 99 and abs(forms("ana")[card("Hugo").id] - 0.985) < 1e-9, "30 min plus tard : un match joué à 99 %, qui repasse à 98,5 % (la récupération compte AVANT le nouveau match)")
later(1.5); ok(forms("ana") == {} and col("ana")["Hugo"]["form"] == 100 and "form_full_in" not in col("ana")["Hugo"], "1 h 30 plus tard : pleine forme, sans attendre minuit")
GL.today_paris = lambda: real_today() + timedelta(days=1); later(0.01)
ok(forms("ana") == {}, "minuit ne change plus rien : seule l'heure compte")
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
GL.today_paris = lambda: real_today() + timedelta(days=3); later(100)                 # (tout le monde est reposé)
fanp = Player(name="Fan Fatigue", poste="FAN"); eqp = Player(name="Gourde Test", poste="EQUIPEMENT"); db.add_all([fanp, eqp]); db.flush()
fcard = Card(player_id=fanp.id, tier=Tier.rare, vitesse=0, tir=0); ecard = Card(player_id=eqp.id, tier=Tier.rare, vitesse=0, tir=0); db.add_all([fcard, ecard]); db.flush()
db.add(OwnedCard(user_id=U("ana").id, card_id=fcard.id, quantity=1)); db.add(OwnedCard(user_id=U("ana").id, card_id=ecard.id, quantity=1)); db.commit()
fteam = {**team, "fan_card_id": fcard.id, "equipment_card_ids": [ecard.id]}
for i in range(3):
    DE.draw_goals = lambda xg: 1; pid = c.post("/duel/proposals", json={**fteam, "stake": 1}, headers=H["ana"]).json()["id"]; r = c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["bob"]).json()
fa = forms("ana")
ok(abs(fa.get(fcard.id, 1) - 0.9865) < 1e-9 and abs(fa.get(ecard.id, 1) - 0.9865) < 1e-9, "après 3 matchs avec un équipement rare (-10 % de fatigue : 0,45 % par match) : le Fan et l'équipement sont à 98,65 %")
ok(r["lineups"]["defender"]["fan"]["form"] == 99.1 and r["lineups"]["defender"]["equipment"][0]["form"] == 99.1, "3e match : joué avec un Fan et un équipement à 99,1 % (affiché dans le récit)")
cf = {x["player_name"]: x for x in c.get("/collection", headers=H["ana"]).json() if x.get("quantity")}
ok(cf["Fan Fatigue"]["form"] == 98.7 and cf["Gourde Test"]["form"] == 98.7, "la collection montre leur forme au dixième près (barre de fatigue : 98,7 %)")
mem = [{"slot": "ATT", "effective": 80}, {"slot": "GB", "effective": 80}]
a0 = DE.team_powers(mem, fcard, 1.0, [ecard], None, 0.0)[0]; a1 = DE.team_powers(mem, fcard, 1.0, [ecard], None, 0.0, {fcard.id: 0.5, ecard.id: 0.5})[0]
fb, eb = GL.TIER_FAN_BONUS["rare"], GL.TIER_EQUIPMENT_BONUS["rare"]
ok(abs(a1 / a0 - (1 + (fb + eb) * 0.5) / (1 + fb + eb)) < 1e-9, "le bonus du Fan et de l'équipement est multiplié par leur forme")
GL.today_paris = real_today
print("6) NETTOYAGE")
cfg = c.get("/duel/config").json(); ok(cfg.get("form_loss_per_match") == 0.005 and cfg.get("form_recovery_per_hour") == 0.01, "le site reçoit les règles (0,5 % par match, +1 % par heure)")
c.post("/admin/delete-user", json={"pseudo": "bob"}, headers={"X-Admin-Key": "k"}); db.expire_all()
ok(db.query(FA.PersonFatigue).filter(~FA.PersonFatigue.user_id.in_([u.id for u in db.query(User).all()])).count() == 0, "compte supprimé : la forme de ses cartes aussi")
print("BILAN (forme des cartes) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
