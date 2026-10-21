"""
Test : Défi du club (équipe du club tirée chaque jour, 3 niveaux, 3 essais, récompense de la première victoire, palmarès, titre,
cartes les plus utilisées alimentées par le club et le tournoi, remise à zéro par l'admin). Lancé par tests/run_tests.py.
Le jour du défi et le score des matchs sont simulés dans le test ; l'horloge du Pass est figée par FC_FAKE_NOW (mi-novembre : pas de points doublés).
"""
import json
import os
from datetime import datetime, timedelta

os.environ["FC_FAKE_NOW"] = "2026-11-12T10:00:00"

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import club as CL, tournament as TN, duel_engine as DE, weekly as WK, missions as MI, game_logic as GL
from app.battlepass import PassProgress
from app.models import User, Card, Player, OwnedCard, Tier, Duel, CardUsage
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
DAY = ["2026-11-12"]; CL.today = lambda: DAY[0]
real_sim = TN.simulate; FORCE = [None]                 # FORCE = (buts du joueur, buts du club) : impose le score, sans tirs au but
def sim(a, b):
    r = real_sim(a, b)
    if FORCE[0] is not None: r["score"], r["pens"] = FORCE[0], ((5, 4) if FORCE[0][0] == FORCE[0][1] else None)      # égalité : le joueur gagne aux tirs au but
    return r
TN.simulate = sim
card = lambda n, t: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]

# des épiques et des légendaires pour tout l'effectif (la base de test n'a que des communes et des rares)
for p in db.query(Player).all():
    for t in ("epique", "legendaire"):
        if card(p.name, t) is None: db.add(Card(player_id=p.id, tier=Tier(t), vitesse=0, tir=0))
db.commit()

TEAM = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 100
    for n, _ in TEAM: db.add(OwnedCard(user_id=u.id, card_id=card(n, "commune").id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
def team(tactic="pressing"):
    return {"formation": "1-2-1", "tactic": tactic, "slots": [{"card_id": card(n, "commune").id, "slot_category": s} for n, s in TEAM]}
def play(H, level, score=(2, 0)):
    FORCE[0] = score; return c.post("/club/%s/play" % level, json=team(), headers=H)
def pass_points(p): db.expire_all(); return sum(r.points for r in db.query(PassProgress).filter_by(user_id=U(p).id).all())
def mission_progress(p): db.expire_all(); r = db.query(MI.UserDaily).filter_by(user_id=U(p).id).first(); return r.progress if r else None
H = {p: mk(p) for p in ("ana", "bob", "cyr", "dan")}

print("1) L'ÉQUIPE DU CLUB DU JOUR")
g = c.get("/club", headers=H["ana"]).json(); lv = {x["level"]: x for x in g["levels"]}
ok([x["level"] for x in g["levels"]] == ["facile", "normal", "difficile"] and all(len(x["team"]["cards"]) == 5 for x in g["levels"]), "3 niveaux (facile, normal, difficile), 5 cartes chacun")
allowed = {"facile": {"commune", "rare"}, "normal": {"rare", "epique"}, "difficile": {"legendaire"} | set(GL.EDITION_TIERS)}
for k, x in lv.items():
    cards = x["team"]["cards"]; need = DE.FORMATIONS[x["team"]["formation"]]
    cats = {s: sum(1 for cd in cards if cd["slot"] == s) for s in need}
    postes_ok = all(DE.poste_category(cd["poste"]) == cd["slot"] or (cd["slot"] == "MC" and cd["poste"] == "MIL") for cd in cards)
    ok(cats == need and "tactic" not in x["team"] and postes_ok, f"{k} : formation {x['team']['formation']} respectée, chaque carte à son poste, tactique NON envoyée au site")
    ok(x["bonus_pct"] == (15 if k == "difficile" else 0), f"{k} : bonus du club +{x['bonus_pct']} %")
    ok(all(cd["tier"] in allowed[k] for cd in cards), f"{k} : raretés du niveau ({', '.join(sorted({cd['tier'] for cd in cards}))})")
    ok(len({cd["player_name"] for cd in cards}) == 5 and sum(1 for cd in cards if cd["captain"]) == 1, f"{k} : 5 joueurs différents, un capitaine")
ok(all(x["tries_left"] == 3 and x["rewarded_today"] is False and x["my_wins"] == 0 for x in g["levels"]) and g["title"]["hard_wins"] == 0, "un joueur neuf : 3 essais par niveau, aucune récompense, aucune victoire")
gb = c.get("/club", headers=H["bob"]).json()
ok([[cd["id"] for cd in x["team"]["cards"]] for x in gb["levels"]] == [[cd["id"] for cd in x["team"]["cards"]] for x in g["levels"]], "un autre joueur, le même jour : exactement les mêmes équipes")
ga = c.get("/club").json(); ok("tries_left" not in ga["levels"][0] and len(ga["levels"][0]["team"]["cards"]) == 5, "sans compte : on voit les équipes du jour (sans essais)")
ok(db.query(CL.ClubTeam).filter_by(day=DAY[0]).count() == 3, "une seule ligne par jour et par niveau, malgré plusieurs consultations")
ids = lambda d: [[cd["id"] for cd in x["team"]["cards"]] + [x["team"]["formation"]] for x in d["levels"]]
rows = {r.level: r for r in db.query(CL.ClubTeam).filter_by(day=DAY[0]).all()}
ok(all(rows[k].tactic in DE.TACTICS for k in CL.LEVELS) and all(e["tactique"] in DE.TACTICS for e in c.get("/admin/club", headers=A).json()["equipes"]), "la tactique tirée est bien enregistrée en base (et visible de l'admin seulement)")
sides = {k: CL.club_side(db, k, rows[k])[0] for k in CL.LEVELS}
ok(sides["difficile"]["team_bonus"] == 0.15 and sides["normal"]["team_bonus"] == 0 and sides["facile"]["team_bonus"] == 0, "bonus d'équipe passé au moteur : +15 % au niveau Difficile seulement")
a0 = DE.team_powers(sides["difficile"]["members"], None, 1.0, [], None, 0.0)[0]; a1 = DE.team_powers(sides["difficile"]["members"], None, 1.0, [], None, 0.15)[0]
ok(abs(a1 / a0 - 1.15) < 1e-9, "le bonus de +15 % multiplie bien la force de l'équipe du club")
days = []
for d in ("2026-11-13", "2026-11-14", "2026-11-15"):
    DAY[0] = d; days.append(ids(c.get("/club").json()))
DAY[0] = "2026-11-12"
ok(any(x != ids(g) for x in days), "le lendemain (et les jours suivants), de nouvelles équipes sont tirées")
ok(ids(c.get("/club").json()) == ids(g), "revenir au même jour redonne la même équipe (gardée en base)")
# repli : pas de carte de la rareté du niveau pour un poste -> rareté autorisée la plus proche
spec = CL.generate_team(db, "difficile"); ok(all(card is not None for card in [db.get(Card, s["card_id"]) for s in spec["slots"]]), "génération directe : 5 cartes existantes")
legends_gb = [cd for cd in db.query(Card).join(Player).filter(Player.poste == "GB", Card.tier == Tier.legendaire).all()]
for cd in legends_gb: cd.tier = Tier.speciale                                          # plus aucun gardien légendaire
db.commit(); fb = CL.generate_team(db, "difficile"); gk = [db.get(Card, s["card_id"]) for s in fb["slots"] if s["slot_category"] == "GB"][0]
ok(gk.player.poste == "GB" and gk.tier.value == "epique", f"sans gardien légendaire : repli sur la rareté la plus proche (épique), toujours un gardien ({gk.player.name}, {gk.tier.value})")
for cd in legends_gb: cd.tier = Tier.legendaire
db.commit()
# aucune légendaire dans le jeu (la situation réelle aujourd'hui) : le club n'invente rien, il prend les meilleures cartes existantes en dessous
legends = db.query(Card).filter(Card.tier == Tier.legendaire).all(); keep = {cd.id: cd.player_id for cd in legends}
for cd in legends: db.delete(cd)
db.commit()
ok(db.query(Card).filter(Card.tier == Tier.legendaire).count() == 0, "on retire toutes les légendaires du jeu")
for _ in range(5):
    sp = CL.generate_team(db, "difficile"); got = [db.get(Card, s["card_id"]) for s in sp["slots"]]
    if not all(cd is not None and cd.tier.value == "epique" for cd in got): break
ok(all(cd is not None for cd in got), "Difficile sans légendaire : les 5 cartes du club existent toutes dans le jeu (aucune inventée)")
ok(all(cd.tier.value == "epique" for cd in got), "Difficile sans légendaire : il aligne la meilleure rareté existante en dessous (épique), 5 tirages sur 5")
epics = db.query(Card).filter(Card.tier == Tier.epique).all()
for cd in epics: cd.tier = Tier.speciale                                   # ni légendaire ni épique : encore un niveau en dessous
db.commit(); got = [db.get(Card, s["card_id"]) for s in CL.generate_team(db, "difficile")["slots"]]
ok(all(cd.tier.value == "speciale" for cd in got), "ni légendaire ni épique : il descend encore d'un niveau (spéciale)")
for cd in epics: cd.tier = Tier.epique
for cid, pid in keep.items(): db.add(Card(id=cid, player_id=pid, tier=Tier.legendaire, vitesse=0, tir=0))
db.commit()

print("2) ESSAIS ET RÉCOMPENSES")
elo0 = {p: U(p).elo for p in H}; duels0 = db.query(Duel).count(); mp0 = U("ana").pack_state.match_pack_tokens; cl0 = U("ana").pack_state.shop_pack_tokens
miss0 = mission_progress("ana"); cr0 = U("ana").credits; pp0 = pass_points("ana")
r = play(H["ana"], "facile", (2, 0)); j = r.json()
ok(r.status_code == 200 and j["club"]["won"] and j["club"]["rewarded"] and j["club"]["credits"] == 5 and j["club"]["pass_points"] == 10 and j["club"]["tries_left"] == 2, "Facile, 1re victoire : +5 crédits, +10 points de Pass, 2 essais restants")
ok(j["defender"] == "Club · Facile" and j["events"] and j["lineups"]["defender"]["players"], "le résultat contient le récit et les compositions (comme un match 1v1)")
ok(j["tactics"]["defender"] in DE.TACTICS and j["lineups"]["defender"]["club_bonus_pct"] == 0, "après le match, la tactique du club est dévoilée dans le récit")
r = play(H["ana"], "facile", (3, 1)); ok(r.json()["club"]["won"] and not r.json()["club"]["rewarded"] and r.json()["club"]["credits"] == 0, "Facile, 2e victoire le même jour : aucune récompense")
r = play(H["ana"], "facile", (0, 1)); ok(r.status_code == 200 and not r.json()["club"]["won"] and r.json()["club"]["tries_left"] == 0, "Facile, une défaite compte aussi comme essai : 0 essai restant")
r = play(H["ana"], "facile"); ok(r.status_code == 400 and "demain" in r.json()["detail"], "4e essai au niveau Facile : refusé (« reviens demain »)")
play(H["ana"], "normal", (0, 2)); r = play(H["ana"], "normal", (1, 1)); j = r.json()["club"]
ok(j["pens"] == [5, 4] and j["won"] and j["rewarded"] and j["credits"] == 10 and j["pass_points"] == 20, "Normal, égalité 1–1 gagnée aux tirs au but (5–4) : c'est une victoire, +10 crédits, +20 points de Pass")
pens_real = TN._shootout(100, 100); ok(pens_real[0] != pens_real[1], "les vrais tirs au but désignent toujours un vainqueur")
FORCE[0] = None
for lv_, n in (("normal", 1), ("difficile", 3)):
    for _ in range(n): play(H["ana"], lv_, (4, 0))
won_normal = db.query(CL.ClubMatch).filter_by(user_id=U("ana").id, level="normal", rewarded=True).count()
ok(won_normal == 1, "Normal : une seule victoire récompensée")
ok(U("ana").credits - cr0 == 30 and pass_points("ana") - pp0 == 60, f"total du jour : +{U('ana').credits - cr0} crédits (30 au maximum) et +{pass_points('ana') - pp0} points de Pass (10 + 20 + 30)")
g = c.get("/club", headers=H["ana"]).json(); ok(all(x["tries_left"] == 0 and x["rewarded_today"] for x in g["levels"]), "les 3 niveaux : 0/3 essai et « récompense obtenue »")
ok(c.post("/club/expert/play", json=team(), headers=H["ana"]).status_code == 404 and c.post("/club/facile/play", json=team()).status_code == 401, "niveau inconnu : 404 ; sans compte : 401")
bad = team(); bad["slots"][0]["card_id"] = card("Sacha", "commune").id
ok(c.post("/club/facile/play", json=bad, headers=H["bob"]).status_code == 400 and CL.tries_left(db, U("bob").id, "facile") == 3, "une carte qu'on ne possède pas : refusé, et l'essai n'est pas consommé")

print("3) AUCUN EFFET SUR LE 1v1, LES PACKS ET LES MISSIONS")
ok({p: U(p).elo for p in H} == elo0, "Elo inchangé")
ok(db.query(Duel).count() == duels0 and c.get("/duel/history").json() == [], "aucun match dans la table des duels ni dans l'historique 1v1")
ok(U("ana").pack_state.match_pack_tokens == mp0 and U("ana").pack_state.shop_pack_tokens == cl0, "aucun pack match ni pack classique gagné")
ok(mission_progress("ana") == miss0, "missions du jour inchangées")
ok(json.loads(db.query(PassProgress).filter_by(user_id=U("ana").id).first().daily)["src"].get("duel") is None, "pas de points de Pass « duel »")

print("4) CARTES LES PLUS UTILISÉES (club et tournoi)")
club_names = {cd["player_name"] for x in g["levels"] for cd in x["team"]["cards"]} - {n for n, _ in TEAM}
week = c.get("/duel/card-stats", params={"scope": "week", "limit": 10}).json(); allt = c.get("/duel/card-stats", params={"limit": 10}).json()
wn = {e["card"]["player_name"]: e["count"] for e in week["most_used"]}; an = {(e["card"]["player_name"], e["card"]["tier"]): e["count"] for e in allt["most_used"]}
ok(all(wn.get(n) == 9 for n, _ in TEAM) and all(an.get((n, "commune")) == 9 for n, _ in TEAM), "les 5 cartes de « ana » : 9 utilisations, cette semaine et depuis toujours")
ok(not (set(wn) & club_names) and not ({n for n, _ in an} & club_names), "les cartes de l'équipe du club n'y sont jamais")
ok(week["top_scorers"] == [] and allt["top_scorers"] == [] and week["top_assisters"] == [], "buts et passes : seulement les matchs 1v1 (rien ici)")
used, goals, _a, n = WK.window_stats(db, datetime.utcnow() - timedelta(days=1), datetime.utcnow())
ok(used["Mathis"] == 9 and n == 0 and not goals, "le calcul des cartes spéciales du vendredi (window_stats) compte aussi ces utilisations")
# un match de tournoi joué (les deux équipes comptent), puis un forfait (rien)
t = TN.Tournament(month_key="2099-01", status="running", size=2, rounds=1); db.add(t); db.flush()
for p in ("bob", "cyr"): db.add(TN.TournamentEntry(tournament_id=t.id, user_id=U(p).id, paid=0, seed=1))
now = datetime(2026, 11, 12, 10); spec = json.dumps(team())
m = TN.TournamentMatch(tournament_id=t.id, round=1, slot=0, p1_id=U("bob").id, p2_id=U("cyr").id, team1=spec, team2=spec, opens_at=now, deadline_at=now)
db.add(m); db.flush(); FORCE[0] = (1, 0); TN._resolve(db, t, m, now); db.commit()
ok(db.query(CardUsage).filter_by(source="tournoi").count() == 10 and {u.user_id for u in db.query(CardUsage).filter_by(source="tournoi")} == {U("bob").id, U("cyr").id}, "match de tournoi joué : les 5 cartes de chaque équipe sont notées")
m2 = TN.TournamentMatch(tournament_id=t.id, round=1, slot=1, p1_id=U("bob").id, p2_id=U("dan").id, team1=spec, team2=None, opens_at=now, deadline_at=now)
db.add(m2); db.flush(); TN._resolve(db, t, m2, now); db.commit()
ok(m2.via == "forfeit" and db.query(CardUsage).filter_by(source="tournoi").count() == 10, "match gagné par forfait : rien n'est noté")
week = c.get("/duel/card-stats", params={"scope": "week", "limit": 10}).json(); allt = c.get("/duel/card-stats", params={"limit": 10}).json()
ok({e["card"]["player_name"]: e["count"] for e in week["most_used"]}.get("Lucas") == 11 and {(e["card"]["player_name"], e["card"]["tier"]): e["count"] for e in allt["most_used"]}.get(("Lucas", "commune")) == 11, "avec le tournoi : 11 utilisations (9 au club + 2 au tournoi), semaine et total")
ok(db.query(Duel).count() == duels0, "le tournoi n'écrit toujours rien dans la table des duels")

print("5) PALMARÈS ET TITRE")
def wins_hard(p, n):
    for _ in range(n):
        if CL.tries_left(db, U(p).id, "difficile") == 0: c.post("/admin/club-reset", json={"pseudo": p}, headers=A)
        play(H[p], "difficile", (2, 0))
wins_hard("bob", 9); cos = {x["id"]: x["unlocked"] for x in c.get("/cosmetics", headers=H["bob"]).json()["titles"]}
ok(cos.get("club") is False and c.get("/club", headers=H["bob"]).json()["title"]["hard_wins"] == 9, "9 victoires au niveau Difficile : titre « Tombeur du club » encore verrouillé")
wins_hard("bob", 1); cos = {x["id"]: x for x in c.get("/cosmetics", headers=H["bob"]).json()["titles"]}
ok(cos["club"]["unlocked"] and cos["club"]["label"] == "Tombeur du club" and c.get("/club", headers=H["bob"]).json()["title"]["unlocked"], "10e victoire au niveau Difficile : titre débloqué")
ok(c.post("/cosmetics", json={"title": "club"}, headers=H["bob"]).status_code == 200 and c.post("/cosmetics", json={"title": "club"}, headers=H["cyr"]).status_code == 400, "bob peut le choisir ; cyr (aucune victoire) non")
play(H["cyr"], "normal", (2, 0)); play(H["cyr"], "normal", (2, 0)); play(H["dan"], "facile", (2, 0)); play(H["dan"], "facile", (2, 0)); play(H["dan"], "facile", (2, 0))
rk = c.get("/club/ranking").json()
ok([r["pseudo"] for r in rk] == ["bob", "ana", "cyr", "dan"], "palmarès : Difficile d'abord (bob 10, ana 3), puis Normal (cyr 2), puis Facile (dan 3) : " + ", ".join(r["pseudo"] for r in rk))
ok(rk[1] == {"pseudo": "ana", "facile": 2, "normal": 2, "difficile": 3}, "le palmarès compte les victoires par niveau (ana : 2 / 2 / 3)")
c.post("/admin/set-test-account", json={"pseudo": "dan", "is_test": True}, headers=A); ok("dan" not in [r["pseudo"] for r in c.get("/club/ranking").json()], "un compte de test n'apparaît pas au palmarès")

print("6) ADMINISTRATION")
ok(c.get("/admin/club").status_code == 403 and c.post("/admin/club-reset", json={"pseudo": "ana"}).status_code == 403, "sans clé admin : 403")
ad = c.get("/admin/club", headers=A).json(); ok(ad["jour"] == DAY[0] and len(ad["equipes"]) == 3 and all(e["joueurs"].count("(") == 5 for e in ad["equipes"]), "l'admin voit les 3 équipes du jour")
cr1 = U("ana").credits; r = c.post("/admin/club-reset", json={"pseudo": "ana"}, headers=A)
g = c.get("/club", headers=H["ana"]).json()
ok(r.status_code == 200 and r.json()["matchs_remis_a_zero"] == 9 and all(x["tries_left"] == 3 and not x["rewarded_today"] for x in g["levels"]), "remise à zéro : 3 essais par niveau, récompenses à regagner")
r = play(H["ana"], "facile", (2, 0)); ok(r.json()["club"]["rewarded"] and U("ana").credits == cr1 + 5, "après la remise à zéro, la première victoire rapporte de nouveau")
ok(c.get("/club/ranking").json()[1]["facile"] == 3, "les matchs d'avant la remise à zéro restent au palmarès")
ok(c.post("/admin/club-reset", json={"pseudo": "personne"}, headers=A).status_code == 404, "pseudo inconnu : 404")
log = c.get("/admin/log", params={"q": "Défi du club"}, headers=A).json(); ok(any("ana" in x["action"] for x in log), "la remise à zéro est notée dans le journal de l'administration")

print("7) SUPPRESSION D'UN COMPTE")
c.post("/admin/delete-user", json={"pseudo": "cyr"}, headers=A)
ok(db.query(CL.ClubMatch).filter_by(user_id=U("bob").id).count() > 0 and "cyr" not in [r["pseudo"] for r in c.get("/club/ranking").json()], "le compte supprimé disparaît du palmarès (et ses matchs du club)")

print("BILAN (défi du club) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
