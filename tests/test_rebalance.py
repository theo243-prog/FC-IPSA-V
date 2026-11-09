"""
Test : rééquilibrage « les cartes d'abord ». Barème des niveaux (+2 / +3 / +4 / +6 / +8), échelle du Fan (seul bonus de puissance),
Loup en crédits (10 premiers matchs 1v1 du jour, 30 crédits par jour), équipement anti-fatigue (-15 % à -60 %, 1v1 seulement),
arbitre +2 %, tactique +4 %, synergie formation + tactique +2 %, tendances publiques des tactiques, ordre d'importance des facteurs.
Lancé par tests/run_tests.py.
"""
import json
import random
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import (fatigue as FA, duel_engine as DE, game_logic as GL, tournament as TN, card_levels as CL, missions as MI,
                 tactic_trends as TT, club as CLB)
from app.models import User, Card, Player, OwnedCard, Tier, Duel, JobRun
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); real_today, real_draw, real_xg = GL.today_paris, DE.draw_goals, DE.expected_goals
card = lambda n, t="commune": db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
CORE = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 2000
    for n, _ in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("ana", "bob", "cleo")}
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": s} for n, s in CORE]}
def special(name, poste, tier):
    p = Player(name=name, poste=poste); db.add(p); db.flush()
    k = Card(player_id=p.id, tier=Tier(tier), vitesse=0, tir=0); db.add(k); db.flush(); return k
def give(pseudo, k):
    db.add(OwnedCard(user_id=U(pseudo).id, card_id=k.id, quantity=1)); db.commit()
fake = lambda tier, cid="x": NS(id=cid, tier=NS(value=tier))
members = lambda note, slots=("GB", "DEF", "MC", "MC", "ATT"): [{"slot": s, "effective": note} for s in slots]

print("1) BARÈME DES NIVEAUX")
ok(CL.LEVEL_NOTE_BONUS == (0, 2, 3, 4, 6, 8) and [CL.note_bonus(i) for i in range(6)] == [0, 2, 3, 4, 6, 8], "LEVEL_NOTE_BONUS = (0, 2, 3, 4, 6, 8)")
lc = card("Lucas")
ok([DE.build_members([(lc, "ATT")], None, {lc.id: lv})[0]["base_note"] for lv in range(6)] == [75, 77, 78, 79, 81, 83], "commune 75 : 77 / 78 / 79 / 81 / 83 aux niveaux 1 à 5")
m = DE.build_members([(lc, "MC")], lc.id, {lc.id: 3}, {lc.id: 0.9})[0]
ok(abs(m["effective"] - (75 + 4) * 0.9 * 0.9 * 1.1) < 1e-9, "(note + bonus du niveau) × forme, puis malus hors poste, puis capitaine")
CL.set_level(db, U("ana").id, lc.id, 2); db.commit()
i = c.get("/cards/%s/level" % lc.id, headers=H["ana"]).json()
ok(i["note"] == 78 and i["level_bonus"] == 3 and i.get("next_note") == 79, "fiche « Évoluer » : niveau 2 = 78, niveau 3 -> 79 (%s -> %s)" % (i["note"], i.get("next_note")))
col = {x["player_name"]: x for x in c.get("/collection", headers=H["ana"]).json() if x.get("quantity") and x["tier"] == "commune"}
ok(col["Lucas"]["display_note"]["value"] == 78 and col["Lucas"]["level"] == 2, "collection : la note affichée suit le nouveau barème (78)")
r = c.post("/admin/set-card-level", json={"pseudo": "ana", "player_name": "Lucas", "tier": "commune", "level": 4}, headers={"X-Admin-Key": "k"})
ok(r.status_code == 200 and r.json().get("level_bonus") == 6, "commande admin set-card-level : renvoie le bonus du niveau (+6)")
CL.set_level(db, U("ana").id, lc.id, 0); db.commit()

print("2) FAN : SEUL BONUS DE PUISSANCE")
ok({k: GL.TIER_FAN_BONUS[k] for k in ("commune", "rare", "halloween", "noel", "epique", "secrete", "saison", "legendaire")} ==
   {"commune": 0.0075, "rare": 0.015, "halloween": 0.015, "noel": 0.015, "epique": 0.02, "secrete": 0.02, "saison": 0.025, "legendaire": 0.03}, "échelle du Fan : 0,75 / 1,5 / 1,5 / 1,5 / 2 / 2 / 2,5 / 3 %")
ok(all(GL.TIER_FAN_BONUS[s] == 0.015 for s in GL.CUSTOM_EDITION_SLOTS), "éditions personnalisées : Fan +1,5 %")
base = DE.team_powers(members(85), None)[0]
ok(abs(DE.team_powers(members(85), fake("legendaire"))[0] / base - 1.03) < 1e-9, "Fan légendaire : +3 % de puissance")
ok(abs(DE.team_powers(members(85), fake("rare"), forms={"x": 0.5})[0] / base - 1.0075) < 1e-9, "le bonus du Fan est multiplié par sa forme (rare à 50 % : +0,75 %)")

print("3) LOUP ET ÉQUIPEMENT : PLUS AUCUNE PUISSANCE")
ok(all(v == 0 for v in GL.TIER_MASCOT_BONUS.values()) and all(v == 0 for v in GL.TIER_EQUIPMENT_BONUS.values()), "TIER_MASCOT_BONUS et TIER_EQUIPMENT_BONUS à 0")
for tier in ("commune", "rare", "epique", "legendaire"):
    p = DE.team_powers(members(85), None, 1.0, [fake(tier, "e")], fake(tier, "m"))
    ok(abs(p[0] - base) < 1e-9 and abs(p[1] - DE.team_powers(members(85), None)[1]) < 1e-9, "Loup et équipement %s : même attaque et même défense" % tier)

print("4) CRÉDITS DU LOUP")
ok(GL.LOUP_CREDITS_BY_TIER == {**{"commune": 1, "rare": 2, "halloween": 2, "noel": 2, "epique": 3, "secrete": 3, "saison": 4, "legendaire": 5}, **{s: 2 for s in GL.CUSTOM_EDITION_SLOTS}} and GL.LOUP_DAILY_CAP == 30,
   "échelle du Loup : 1 / 2 / 2 / 2 / 3 / 3 / 4 / 5 crédits, éditions 2, plafond 30 par jour")
GL.today_paris = lambda: real_today() + timedelta(days=1)
wolf_l, wolf_c = special("Loup Légendaire", "MASCOTTE", "legendaire"), special("Loup Commun", "MASCOTTE", "commune")
give("ana", wolf_l); give("bob", wolf_c)
DE.draw_goals = lambda xg: 1                                  # tous les matchs nuls : la mise revient à chacun
def duel(creator="ana", player="bob", cteam=None, pteam=None):
    pid = c.post("/duel/proposals", json={**(cteam or team), "stake": 3}, headers=H[creator]).json()["id"]
    return c.post("/duel/proposals/%s/play" % pid, json=pteam or team, headers=H[player]).json()
ana0, bob0, tok0 = U("ana").credits, U("bob").credits, U("ana").pack_state.shop_pack_tokens
res = [duel(cteam={**team, "mascot_card_id": wolf_l.id}, pteam={**team, "mascot_card_id": wolf_c.id}) for _ in range(12)]
la = [r.get("loup_credits", {}).get("ana", 0) for r in res]; lb = [r.get("loup_credits", {}).get("bob", 0) for r in res]
ok(la == [5] * 6 + [0] * 6, "Loup légendaire (créateur du défi) : 5 crédits par match jusqu'au plafond de 30 (%s)" % la)
ok(lb == [1] * 10 + [0] * 2, "Loup commun (challenger) : 1 crédit pendant les 10 premiers matchs du jour seulement (%s)" % lb)
instead = lambda p: sum(r["credits_instead"].get(p, 0) for r in res)
ok(U("ana").credits - ana0 == 30 + instead("ana") and U("bob").credits - bob0 == 10 + instead("bob"), "crédits versés aux deux équipes, indépendamment (la mise des matchs nuls revient intacte)")
ok(all(r["credits_delta"] == 0 and r["stake"] == 3 for r in res), "la mise n'est pas touchée")
ok(MI.daily_count(db, U("ana"), "duel_packs") == 10 and U("ana").pack_state.shop_pack_tokens - tok0 == 10, "les packs gagnés ne changent pas (10 packs, puis des crédits au hasard)")
ok(MI.daily_count(db, U("ana"), "loup_credits") == 30 and MI.daily_count(db, U("bob"), "duel_matches") == 12, "compteurs du jour : loup_credits 30, duel_matches 12")
ok(res[0]["lineups"]["defender"]["mascot"]["credits_won"] == 5 and res[0]["lineups"]["defender"]["mascot"]["bonus_pct"] == 0, "le récapitulatif du match montre les crédits du Loup (et plus de bonus en %)")
GL.today_paris = lambda: real_today() + timedelta(days=2)
r = duel(cteam={**team, "mascot_card_id": wolf_l.id})
ok(r.get("loup_credits", {}).get("ana") == 5, "nouveau jour (Paris) : le Loup rapporte de nouveau")
# forfait : le défi n'est plus valide (le créateur n'a plus ses cartes) -> aucun match, aucun crédit
give("cleo", wolf_l); cl0 = U("cleo").credits
pid = c.post("/duel/proposals", json={**team, "stake": 3, "mascot_card_id": wolf_l.id}, headers=H["cleo"]).json()["id"]
db.query(OwnedCard).filter_by(user_id=U("cleo").id, card_id=card("Lucas").id).delete(); db.commit()
r = c.post("/duel/proposals/%s/play" % pid, json=team, headers=H["bob"])
ok(r.status_code == 400 and U("cleo").credits == cl0 and MI.daily_count(db, U("cleo"), "duel_matches") == 0, "défi annulé (forfait) : aucun crédit du Loup, aucun match compté")
give("cleo", card("Lucas"))
spec = {**team, "captain_card_id": None, "mascot_card_id": wolf_l.id}
a0 = U("ana").credits
TN.simulate(TN._prepare(db, U("ana"), spec), TN._prepare(db, U("bob"), {**team, "captain_card_id": None})); db.commit()
ok(U("ana").credits == a0, "tournoi : aucun crédit du Loup")
CLB.today = lambda: "2026-11-20"
a0 = U("ana").credits
lv = c.get("/club", headers=H["ana"]).json()["levels"][0]["level"]
r = c.post("/club/%s/play" % lv, json={**team, "mascot_card_id": wolf_l.id}, headers=H["ana"]).json()
gain = r["club"]["credits"] if r["club"].get("rewarded") else 0
ok(U("ana").credits - a0 == gain and not r["lineups"]["challenger"]["mascot"]["credits_won"], "défi du club : aucun crédit du Loup (seulement la récompense du club, %d)" % gain)

print("5) ÉQUIPEMENT : MOINS DE FATIGUE")
ok(GL.EQUIPMENT_FATIGUE_REDUCTION == {"commune": 0.15, "rare": 0.25, "epique": 0.40, "legendaire": 0.60} and GL.EQUIPMENT_FATIGUE_MAX == 0.60, "réductions 15 / 25 / 40 / 60 %, plafond 60 %")
ok([GL.equipment_fatigue_reduction([fake(t)]) for t in ("commune", "rare", "epique", "legendaire")] == [0.15, 0.25, 0.40, 0.60], "réduction par rareté")
ok(GL.equipment_fatigue_reduction([fake("legendaire"), fake("epique")]) == 0.60 and abs(GL.equipment_fatigue_reduction([fake("rare"), fake("commune")]) - 0.40) < 1e-9, "plusieurs pièces : additionnées, plafonnées à 60 %")
ok([FA.loss_per_match(r) for r in (0, 0.15, 0.25, 0.40, 0.60, 0.9)] == [100, 85, 75, 60, 40, 40], "perte par match : 1 %, 0,85 %, 0,75 %, 0,6 %, 0,4 % (jamais plus de 60 % de réduction)")
ok(FA.form_from_loss(10 ** 6) == FA.MIN_FORM == 0.5, "la forme minimale reste 50 %")
GL.today_paris = lambda: real_today() + timedelta(days=4)
gear = special("Gourde Légendaire", "EQUIPEMENT", "legendaire"); give("ana", gear)
for _ in range(3):
    r = duel(cteam={**team, "equipment_card_ids": [gear.id], "mascot_card_id": wolf_l.id})
fa = FA.forms_for(db, U("ana").id); fb = FA.forms_for(db, U("bob").id)
ok(all(abs(fa[k.id] - 0.988) < 1e-9 for k in [card(n) for n, _ in CORE] + [wolf_l, gear]), "équipement légendaire : 3 matchs = -1,2 % (joueurs, Loup et équipement à 98,8 %)")
ok(all(abs(v - 0.97) < 1e-9 for v in fb.values()), "l'adversaire sans équipement : -1 % par match (97 %)")
ok(r["lineups"]["defender"]["fatigue_reduction_pct"] == 60 and r["lineups"]["challenger"]["fatigue_reduction_pct"] == 0, "le récapitulatif montre la réduction de fatigue de chaque équipe")
before = dict(FA.forms_for(db, U("ana").id))
tr = TN.simulate(TN._prepare(db, U("ana"), {**team, "captain_card_id": None, "equipment_card_ids": [gear.id]}), TN._prepare(db, U("bob"), {**team, "captain_card_id": None})); db.commit()
ok(FA.forms_for(db, U("ana").id) == before and tr["lineups"]["challenger"]["fatigue_reduction_pct"] == 0, "tournoi : aucune fatigue et aucune réduction affichée")

print("6) ARBITRE ET TACTIQUE")
ok(DE.REFEREE_BONUS == 0.02 and DE.TACTIC_BONUS == 0.04, "arbitre +2 %, tactique +4 %")
ok(DE.TACTICS["pressing"]["beats"] == "possession" and DE.TACTICS["possession"]["beats"] == "contre" and DE.TACTICS["contre"]["beats"] == "pressing", "matrice pierre-feuille-ciseaux inchangée")
cfg = c.get("/duel/config").json()
ok(cfg["referee_bonus"] == 0.02 and cfg["tactic_bonus"] == 0.04 and cfg["synergy_bonus"] == 0.02 and cfg["loup_daily_cap"] == 30 and cfg["equipment_fatigue_reduction"]["rare"] == 0.25, "/duel/config envoie les nouvelles règles au site")

print("7) SYNERGIE FORMATION x TACTIQUE")
ok(DE.SYNERGY == {"pressing": "1-1-2", "possession": "1-2-1", "contre": "2-1-1"} and DE.SYNERGY_BONUS == 0.02, "SYNERGY et SYNERGY_BONUS")
combos = [(f, t) for f in ("2-1-1", "1-2-1", "1-1-2") for t in ("pressing", "possession", "contre")]
good = [(f, t) for f, t in combos if DE.has_synergy(f, t)]
ok(sorted(good) == sorted([("1-1-2", "pressing"), ("1-2-1", "possession"), ("2-1-1", "contre")]) and len(combos) - len(good) == 6, "3 combinaisons cohérentes, 6 sans synergie")
for f, t in combos:
    slots = {"2-1-1": ("GB", "DEF", "DEF", "MC", "ATT"), "1-2-1": ("GB", "DEF", "MC", "MC", "ATT"), "1-1-2": ("GB", "DEF", "MC", "ATT", "ATT")}[f]
    ratio = DE.team_powers(members(85, slots), None, formation=f, tactic=t)[0] / DE.team_powers(members(85, slots), None)[0]
    ok(abs(ratio - (1.02 if (f, t) in good else 1.0)) < 1e-9, "%s + %s : x%.2f" % (t, f, ratio))
seen = []
DE.expected_goals = lambda a, d: (seen.append((a, d)), real_xg(a, d))[1]
GL.today_paris = lambda: real_today() + timedelta(days=6)              # (forme à 100 % pour tout le monde)
syn_team = {**team, "tactic": "possession"}
r = duel(creator="ana", player="bob", cteam={**team, "tactic": "contre"}, pteam=syn_team); one = seen[0]; seen.clear()
TN.simulate(TN._prepare(db, U("bob"), {**syn_team, "captain_card_id": None}), TN._prepare(db, U("ana"), {**team, "tactic": "contre", "captain_card_id": None})); two = seen[0]
DE.expected_goals = real_xg
ok(abs(one[0] - two[0]) < 1e-9 and abs(one[1] - two[1]) < 1e-9, "effet identique en 1v1 et en tournoi (même attaque et même défense)")
ok(r["lineups"]["challenger"]["synergy"] is True and r["lineups"]["defender"]["synergy"] is False, "le récapitulatif indique la synergie de chaque équipe")

print("8) TENDANCES DES TACTIQUES")
TT.record(db, "1v1", [(U("cleo").id, "pressing", "1-1-2")] ); db.commit()
tr = c.get("/users/cleo/profile", headers=H["ana"]).json()["tactic_trends"]
ok(tr["matches"] == 1 and tr["tactics"] is None and tr["formations"] is None and tr["enough"] is False, "moins de 5 matchs : pas assez de matchs")
ok(c.get("/users/cleo/profile").json()["tactic_trends"] is None, "sans compte : pas de tendances")
t0 = datetime(2026, 1, 1)
db.query(TT.TacticHistory).filter_by(user_id=U("cleo").id).delete()
for k in range(5):
    TT.record(db, "1v1", [(U("cleo").id, "contre", "2-1-1")], played_at=t0 + timedelta(minutes=k))          # trop anciens : hors des 20 derniers
seq = ["pressing"] * 11 + ["possession"] * 5 + ["contre"] * 4; random.Random(1).shuffle(seq)
for k, t in enumerate(seq):
    TT.record(db, "tournoi" if k % 3 == 0 else "1v1", [(U("cleo").id, t, DE.SYNERGY[t])], played_at=t0 + timedelta(days=1, minutes=k))
db.commit()
tr = c.get("/users/cleo/profile", headers=H["ana"]).json()["tactic_trends"]
ok(tr["tactics"] == {"pressing": 55, "possession": 25, "contre": 20} and tr["tactic_matches"] == 20, "20 derniers matchs : pressing 55 %%, possession 25 %%, contre 20 %% (%s)" % tr["tactics"])
ok(tr["formations"] == {"2-1-1": 20, "1-2-1": 25, "1-1-2": 55}, "formations en pourcentage")
ok(set(tr) == {"window", "min_matches", "matches", "tactics", "tactic_matches", "formations", "formation_matches", "enough"}, "seulement des pourcentages : ni match précis, ni dernière tactique")
ok(sum(TT._shares(["pressing", "possession", "contre"], TT.TACTIC_KEYS).values()) == 100, "les pourcentages font toujours 100")
n0 = db.query(TT.TacticHistory).filter_by(user_id=U("ana").id).count()
pid = c.post("/duel/proposals", json={**team, "tactic": "contre", "stake": 1}, headers=H["ana"]).json()["id"]
pub = [p for p in c.get("/duel/proposals", headers=H["bob"]).json() if p["id"] == pid]
ok(pub and "tactic" not in pub[0] and db.query(TT.TacticHistory).filter_by(user_id=U("ana").id).count() == n0, "défi publié pas encore joué : tactique cachée et rien dans les tendances")
now = datetime.utcnow()
tn = TN.Tournament(month_key="2099-01", status="running", size=2, rounds=1); db.add(tn); db.flush()
for p in ("ana", "bob"):
    db.add(TN.TournamentEntry(tournament_id=tn.id, user_id=U(p).id, seed=1 if p == "ana" else 2))
tspec = lambda tac: json.dumps({**team, "tactic": tac, "captain_card_id": None})
mp = TN.TournamentMatch(tournament_id=tn.id, round=1, slot=0, p1_id=U("ana").id, p2_id=U("bob").id, seed1=1, seed2=2, team1=tspec("contre"), team2=tspec("pressing"), opens_at=now, deadline_at=now)
db.add(mp); db.flush(); TN._resolve(db, tn, mp, now); db.commit()
trows = {(r.user_id, r.tactic, r.formation) for r in db.query(TT.TacticHistory).filter_by(ref=mp.id, mode="tournoi").all()}
ok(mp.via == "play" and trows == {(U("ana").id, "contre", "1-2-1"), (U("bob").id, "pressing", "1-2-1")}, "match de tournoi joué : la tactique et la formation des deux joueurs sont enregistrées")
tn2 = TN.Tournament(month_key="2099-02", status="running", size=2, rounds=1); db.add(tn2); db.flush()
mf = TN.TournamentMatch(tournament_id=tn2.id, round=1, slot=0, p1_id=U("ana").id, p2_id=U("bob").id, seed1=1, seed2=2, team1=tspec("contre"), team2=None, opens_at=now, deadline_at=now)
db.add(mf); db.flush(); TN._resolve(db, tn2, mf, now); db.commit()
ok(mf.via == "forfeit" and db.query(TT.TacticHistory).filter_by(ref=mf.id).count() == 0, "forfait au tournoi : rien d'enregistré")
# reprise de l'historique : un duel sans ligne de tendance est repris une seule fois
db.query(JobRun).filter_by(name=TT.BACKFILL_JOB).delete(); db.commit()
d = Duel(challenger_id=U("cleo").id, defender_id=U("bob").id, stake=1, formation_challenger="1-1-2", formation_defender="2-1-1", score_challenger=1, score_defender=0,
         elo_challenger_before=1000, elo_defender_before=1000, elo_challenger_after=1010, elo_defender_after=990, tactic_challenger=None, tactic_defender="contre")
db.add(d); db.commit()
added = TT.backfill(db); again = TT.backfill(db)
rows = db.query(TT.TacticHistory).filter_by(ref=d.id).all()
ok(added == 2 and again == 0 and len(rows) == 2 and {(r.tactic, r.formation) for r in rows} == {(None, "1-1-2"), ("contre", "2-1-1")}, "reprise des anciens duels une seule fois (tactique vide gardée vide)")
ok(db.query(TT.TacticHistory).filter(TT.TacticHistory.ref.in_([x.id for x in db.query(Duel).all()])).count() == 2 * db.query(Duel).count(), "chaque duel joué a ses deux lignes, sans doublon")

print("9) ORDRE D'IMPORTANCE : CARTES, PUIS TACTIQUE, PUIS FAN")
def win_rate(mult=1.0, note=85, n=20000):
    a = DE.team_powers(members(note), None, mult); b = DE.team_powers(members(85), None); random.seed(11); w = 0
    for _ in range(n):
        w += real_draw(real_xg(a[0], b[1])) > real_draw(real_xg(b[0], a[1]))
    return w / n
lvl3, tac, fan = win_rate(note=85 + CL.note_bonus(3)), win_rate(1 + DE.TACTIC_BONUS), win_rate(1 + GL.TIER_FAN_BONUS["legendaire"])
ok(lvl3 > tac > fan > win_rate(), "niveau 3 sur 5 cartes (%.0f %%) > tactique (%.0f %%) > Fan légendaire (%.0f %%) > rien" % (lvl3 * 100, tac * 100, fan * 100))

DE.draw_goals = real_draw; GL.today_paris = real_today
c.post("/admin/delete-user", json={"pseudo": "cleo"}, headers={"X-Admin-Key": "k"}); db.expire_all()
ok(db.query(TT.TacticHistory).filter(~TT.TacticHistory.user_id.in_([u.id for u in db.query(User).all()])).count() == 0, "compte supprimé : ses tendances aussi")
print("BILAN (rééquilibrage) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
