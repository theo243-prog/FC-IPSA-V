"""
Test : niveaux des cartes Fan, Loup et Équipement (11/11/2026). Gains modérés par niveau : Fan +0,1 point de bonus d'équipe,
Équipement +1 point de réduction de la fatigue (au-delà du plafond de 25 %), Loup +1 crédit par match aux niveaux 2 et 5 et plafond du
jour relevé de 2 par niveau. Communes, rares, éditions, épiques et légendaires (pas les secrètes) ; les joueurs épiques ou légendaires
n'évoluent toujours pas. Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import card_levels as CL, duel_engine as DE, game_logic as GL
from app.models import User, Card, Player, OwnedCard, Tier
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
def person(name, poste):
    p = Player(name=name, poste=poste); db.add(p); db.commit(); return p
def card(p, tier):
    k = Card(player_id=p.id, tier=Tier(tier), vitesse=50, tir=50); db.add(k); db.commit(); return k
def give(pseudo, k, n):
    u = U(pseudo); o = db.query(OwnedCard).filter_by(user_id=u.id, card_id=k.id).first()
    if o is None: db.add(OwnedCard(user_id=u.id, card_id=k.id, quantity=n))
    else: o.quantity = n
    db.commit()
H = {"ana": mk("ana", 5000)}
FAN, LOUP, EQ = person("Supporter Test", "FAN"), person("Loup Test", "MASCOTTE"), person("Gourde Test", "EQUIPEMENT")
fan_c, fan_e, fan_s = card(FAN, "commune"), card(FAN, "epique"), card(FAN, "secrete")
loup_l, eq_l, eq_r = card(LOUP, "legendaire"), card(EQ, "legendaire"), card(EQ, "rare")
joueur = db.query(Player).filter_by(poste="ATT").first(); j_epic = card(joueur, "epique")

print("1) QUELLES CARTES ÉVOLUENT")
ok(all(CL.ineligible_reason(k) is None for k in (fan_c, fan_e, loup_l, eq_l, eq_r)), "Fan, Loup et équipement : commune, rare, épique, légendaire éligibles")
ok(CL.ineligible_reason(fan_s) is not None and CL.ineligible_reason(j_epic) is not None, "pas une secrète, et un joueur épique n'évolue toujours pas")
ok(CL.DUPES_REQUIRED["epique"] == [1, 1, 1, 1, 1] and CL.DUPES_REQUIRED["legendaire"] == [1, 1, 1, 1, 1], "épique et légendaire : 1 doublon par niveau")

print("2) ÉVOLUER UN FAN")
give("ana", fan_c, 6)
i = c.get("/cards/%s/level" % fan_c.id, headers=H["ana"]).json()
ok(i["eligible"] and i["bonus_card"] and i["effect"] == "+0,75 % de bonus d'équipe" and i["effect_next"] == "+0,85 % de bonus d'équipe" and i["can"], "fiche : effet actuel et suivant (+0,75 % → +0,85 %)")
r = c.post("/cards/%s/evolve" % fan_c.id, headers=H["ana"])
ok(r.status_code == 200 and CL.level_of(db, U("ana").id, fan_c.id) == 1 and U("ana").credits == 5000 - 15, "niveau 1 : 5 doublons et 15 crédits (barème des communes)")
ok(i["effect_steps"][5] == "+1,25 % de bonus d'équipe", "niveau 5 : +1,25 % (toujours moins qu'un Fan rare à +1,5 %)")

print("3) EFFETS DANS LE MOTEUR")
mem = [{"slot": s, "effective": 85} for s in ("GB", "DEF", "MC", "MC", "ATT")]
base = DE.team_powers(mem, None)[0]
ok(abs(DE.team_powers(mem, fan_c, fan_level=5)[0] / base - 1.0125) < 1e-9 and abs(DE.team_powers(mem, fan_c)[0] / base - 1.0075) < 1e-9, "Fan commune : +0,75 % au niveau 0, +1,25 % au niveau 5")
ok(abs(GL.equipment_fatigue_reduction([eq_l]) - 0.25) < 1e-9 and abs(GL.equipment_fatigue_reduction([eq_l], {eq_l.id: 5}) - 0.30) < 1e-9 and abs(GL.equipment_fatigue_reduction([eq_r], {eq_r.id: 2}) - 0.12) < 1e-9,
   "équipement : légendaire 25 % → 30 % au niveau 5 ; rare 10 % → 12 % au niveau 2")
CL.set_level(db, U("ana").id, loup_l.id, 5); db.commit()
ua = U("ana"); got = [DE.loup_credits(db, ua, loup_l) for _ in range(8)]; db.commit()
ok(got == [7, 7, 7, 7, 7, 5, 0, 0], "Loup légendaire niveau 5 : 7 crédits par match (5 + 2), 40 par jour au plus (%s)" % got)
snap = DE._lineup_snapshot({"pseudo": "ana", "formation": "1-2-1", "tactic": "pressing", "members": [], "levels": {fan_c.id: 1, loup_l.id: 5, eq_l.id: 5}}, fan_c, [eq_l], loup_l)
ok(snap["fan"]["level"] == 1 and abs(snap["fan"]["bonus_pct"] - 0.85) < 1e-9 and snap["mascot"]["credits_per_match"] == 7 and snap["equipment"][0]["fatigue_reduction_pct"] == 30 and snap["fatigue_reduction_pct"] == 30,
   "récit du match : niveaux et effets du Fan, du Loup et de l'équipement")
cfg = c.get("/duel/config").json()
ok(cfg["fan_level_bonus"][5] == 0.005 and cfg["equipment_level_reduction"][5] == 0.05 and cfg["loup_level_credits"] == [0, 0, 1, 1, 1, 2], "/duel/config annonce les barèmes (pour la composition)")

print("4) LA COMPLÉTION DU JEU NE CHANGE PAS")
before = CL.game_completion(db, [U("ana").id])[U("ana").id]
CL.set_level(db, U("ana").id, fan_c.id, 5); db.commit()
ok(CL.game_completion(db, [U("ana").id])[U("ana").id] == before, "les niveaux du Fan, du Loup et de l'équipement ne comptent pas dans la complétion du jeu (seuls les joueurs)")

print(); print("BILAN (niveaux Fan, Loup, équipement) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
