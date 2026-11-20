"""
Test : renommer une personne du club partout (POST /admin/rename-player).
Lancé par tests/run_tests.py.
"""
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import duel_engine as DE, motm, numbered
from app.models import User, Card, Player, OwnedCard, Tier, Duel, Match, MatchMoment, CardUsage
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 500
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("rena", "renb", "renc")}
lucas = db.query(Player).filter_by(name="Lucas").first(); lucas_id = lucas.id

print("0) PRÉPARATION : 1v1, carte gold, Édition Noire, match réel avec vote, utilisation au club")
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
DE.draw_goals = lambda xg: 2
pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["rena"]).json()["id"]
ok(c.post(f"/duel/proposals/{pid}/play", json=team, headers=H["renb"]).status_code == 200, "un match 1v1 joué avec Lucas")
ok(c.post("/admin/create-gold", json={"moments": [{"player_name": "Lucas", "action": "Petit pont"}, {"player_name": "Lucas", "action": "Petit pont"}]}, headers=A).status_code == 200, "deux cartes gold « Petit pont — Lucas »")
r = c.post("/admin/series-create", json={"title": "Édition Noire", "subject": "Lucas", "total": 3}, headers=A)
ok(r.status_code == 200, "une série Édition Noire de Lucas (%s)" % r.status_code)
r = c.post("/admin/record-match", json={"date": "2026-11-18", "opponent": "AS Test", "score_us": 1, "score_them": 0, "buteurs": [{"player_name": "Lucas", "count": 1}],
                                         "lineup": CORE, "cartons_jaunes": ["Lucas"], "moments": [{"player_name": "Lucas", "action": "Sauvetage"}], "open_vote": True}, headers=A)
ok(r.status_code == 200, "un match réel avec Lucas présent, carton, moment et vote ouvert (%s)" % r.text[:120])
vid = db.query(motm.MotmVote).filter_by(status="open").first().id
for p in H:
    c.post("/motm/%s/vote" % vid, json={"first": "Lucas", "second": "Hugo", "third": "Nathan"}, headers=H[p])
db.add(CardUsage(source="club", user_id="x", player_name="Lucas", tier="commune")); db.commit()
cards_before = sorted(x.id for x in db.query(Card).filter_by(player_id=lucas_id).all())         # (dont l'épique créée par son but)

print("1) REFUS")
ok(c.post("/admin/rename-player", json={"old_name": "Lucas", "new_name": "Luc"}).status_code == 403, "sans clé admin : 403")
ok(c.post("/admin/rename-player", json={"old_name": "Inconnu", "new_name": "Luc"}, headers=A).status_code == 404, "ancien nom introuvable : 404")
ok(c.post("/admin/rename-player", json={"old_name": "Lucas", "new_name": "hugo"}, headers=A).status_code == 400, "nouveau nom déjà pris (sans tenir compte des majuscules) : refus")
ok(c.post("/admin/rename-player", json={"old_name": "Lucas", "new_name": "Lucas"}, headers=A).status_code == 400, "nom identique : refus")
ok(c.post("/admin/rename-player", json={"old_name": "Petit pont — Lucas", "new_name": "Truc"}, headers=A).status_code == 400, "une carte gold ne se renomme pas ici")
db.expire_all(); ok(db.get(Player, lucas_id).name == "Lucas", "après les refus, rien n'a changé")

print("2) RENOMMAGE")
r = c.post("/admin/rename-player", json={"old_name": "Lucas", "new_name": "Lucas Martin"}, headers=A)
ok(r.status_code == 200, "renommé (%s)" % r.text[:300])
rep = r.json(); db.expire_all()
ok(db.get(Player, lucas_id).name == "Lucas Martin" and sorted(x.id for x in db.query(Card).filter_by(player_id=lucas_id).all()) == cards_before, "même fiche, mêmes cartes, nouveau nom")
golds = sorted(p.name for p in db.query(Player).filter(Player.poste == "MOMENT").all() if "Lucas" in p.name)
ok(golds == ["Petit pont — Lucas Martin", "Petit pont — Lucas Martin (%s)" % golds[1][-6:-1], "Sauvetage — Lucas Martin"] if len(golds) == 3 else False, "cartes gold renommées (%s)" % golds)
ok(db.query(MatchMoment).filter_by(real_player_name="Lucas Martin").count() == 1 and db.query(MatchMoment).filter_by(real_player_name="Lucas").count() == 0, "moment du match réel renommé")
s = db.query(numbered.NumberedSeries).filter_by(subject="Lucas Martin").first()
ok(s is not None and db.query(Player).filter(Player.name.like("Édition Noire — Lucas Martin · n° %/3")).count() == 3, "série Édition Noire et ses 3 exemplaires renommés")
d = db.query(Duel).order_by(Duel.created_at.desc()).first()
ok("Lucas Martin" in d.lineups_json and '"player": "Lucas"' not in d.lineups_json, "composition du 1v1 renommée")
ev = json.loads(d.events_json or "[]")
ok(all(e.get("scorer") != "Lucas" and e.get("assist") != "Lucas" for e in ev), "buteurs et passeurs du récit renommés")
m = db.query(Match).order_by(Match.created_at.desc()).first()
ok("Lucas Martin" in json.loads(m.lineup_json) and json.loads(m.yellow_json) == ["Lucas Martin"], "match réel : présents et cartons renommés")
v = db.get(motm.MotmVote, vid)
ok("Lucas Martin" in json.loads(v.players_json) and "Lucas" not in json.loads(v.players_json), "vote de l'homme du match : présents renommés")
ok(db.query(motm.MotmBallot).filter_by(vote_id=vid, first="Lucas Martin").count() == 3, "bulletins renommés (3)")
ok(db.query(CardUsage).filter_by(player_name="Lucas Martin").count() == 1 and db.query(CardUsage).filter_by(player_name="Lucas").count() == 0, "utilisation des cartes renommée")
ok(rep["gold_cards"] == 3 and rep["numbered_copies"] == 3 and rep["duels"] >= 1 and rep["motm_ballots"] == 3, "le rapport compte ce qui a changé")
g = c.get("/motm", headers=H["rena"]).json()
ok("Lucas Martin" in json.dumps(g, ensure_ascii=False), "le vote affiche le nouveau nom")
ok(c.post("/motm/%s/vote" % vid, json={"first": "Lucas Martin", "second": "Hugo", "third": "Nathan"}, headers=H["rena"]).status_code == 200, "on peut voter pour le nouveau nom")
cs = c.get("/duel/card-stats?scope=week").json()
ok("Lucas Martin" in json.dumps(cs, ensure_ascii=False) and '"Lucas"' not in json.dumps(cs, ensure_ascii=False), "cartes les plus utilisées de la semaine : un seul nom")

print("3) CORRIGER UNE MAJUSCULE")
r = c.post("/admin/rename-player", json={"old_name": "Lucas Martin", "new_name": "lucas martin"}, headers=A)
ok(r.status_code == 200, "changer seulement la casse est permis")

print(); print("BILAN (renommer un joueur) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
