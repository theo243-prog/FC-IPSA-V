"""
Test : Homme du match (vote après un match officiel, 24 h, bulletin 5/3/1, secret jusqu'à la fin, cartes légendaires ou +2 sans plafond,
classement privé de la saison des votes). L'horloge du vote est simulée (motm.now). Lancé par tests/run_tests.py.
"""
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import motm as M, game_logic as GL, duel_engine as DE, chat as CH
from app.admin_tools import AdminLog
from app.models import User, Card, Player, Tier, Match
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
T0 = datetime(2026, 11, 10, 12, 0, 0); CLOCK = [T0]; M.now = lambda: CLOCK[0]
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
leg = lambda n: (db.expire_all(), db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.legendaire).first())[1]
def mk(p):
    return {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]}
H = {p: mk(p) for p in ("v1", "v2", "v3", "v4", "v5")}
db.add(Player(name="Supporter Fou", poste="FAN")); db.commit()
LINEUP = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo", "Tom", "Supporter Fou"]
N = [0]
def record(lineup=LINEUP, vote=True, hdm=None):
    N[0] += 1; body = {"date": "2026-11-0%d" % (N[0] % 9 + 1), "opponent": "Adversaire %d" % N[0], "score_us": 2, "score_them": 1, "lineup": lineup, "open_vote": vote}
    if hdm: body["homme_du_match"] = hdm
    return c.post("/admin/record-match", json=body, headers=A)
def vote(p, vid, a, b, d):
    return c.post("/motm/%s/vote" % vid, json={"first": a, "second": b, "third": d}, headers=H[p])
def pub():
    return c.get("/motm", headers=H["v1"]).json()
def vrow(vid): db.expire_all(); return db.get(M.MotmVote, vid)

print("1) OUVERTURE DU VOTE")
n0 = db.query(Match).count()
r = record(["Lucas", "Hugo", "Supporter Fou"])
ok(r.status_code == 400 and "au moins 3" in r.json()["detail"] and db.query(Match).count() == n0, "moins de 3 vrais joueurs présents (le fan ne compte pas) : refusé, et rien n'est enregistré")
r = record(); V1 = r.json()["motm_vote"]
ok(r.status_code == 200 and V1 and V1["players"] == ["Lucas", "Hugo", "Nathan", "Léo", "Enzo", "Tom"], "vote ouvert parmi les présents ; le fan est exclu")
ok(vrow(V1["id"]).closes_at == T0 + timedelta(hours=24), "fermeture 24 h exactement après l'enregistrement")
ok(record(vote=False).json()["motm_vote"] is None, "case non cochée : aucun vote")
g = pub(); ok(len(g["current"]) == 1 and g["current"][0]["voters"] == 0, "un seul vote en cours")
ok(c.get("/me", headers=H["v1"]).json()["motm_todo"] is True, "point rouge : un vote ouvert et pas encore voté")

print("2) LE BULLETIN")
vid = V1["id"]
ok(c.post("/motm/%s/vote" % vid, json={"first": "Lucas", "second": "Hugo", "third": "Nathan"}).status_code == 401, "sans compte : 401")
ok(vote("v1", "inconnu", "Lucas", "Hugo", "Nathan").status_code == 404, "vote inconnu : 404")
ok(vote("v1", vid, "Lucas", "Hugo", "").status_code == 400, "les trois places sont obligatoires")
ok(vote("v1", vid, "Lucas", "Lucas", "Hugo").status_code == 400, "trois joueurs différents")
ok(vote("v1", vid, "Lucas", "Hugo", "Mathis").status_code == 400, "un joueur absent du match est refusé")
ok(vote("v1", vid, "Lucas", "Hugo", "Supporter Fou").status_code == 400, "un fan (même présent) ne peut pas être voté")
r1 = vote("v1", vid, "Hugo", "Lucas", "Nathan"); r2 = vote("v1", vid, "Lucas", "Hugo", "Nathan")
ok(r1.status_code == 200 and r2.status_code == 200 and r2.json()["updated"] and r2.json()["voters"] == 1 and r2.json()["my_ballot"] == ["Lucas", "Hugo", "Nathan"], "un bulletin par compte, modifiable : 1 votant, bulletin à jour")
ok(c.get("/me", headers=H["v1"]).json()["motm_todo"] is False, "point rouge éteint une fois voté")
vote("v2", vid, "Lucas", "Nathan", "Hugo"); vote("v3", vid, "Lucas", "Léo", "Hugo"); vote("v4", vid, "Hugo", "Lucas", "Enzo")

print("3) RIEN AVANT LA FIN")
cur = c.get("/motm", headers=H["v2"]).json()["current"][0]
ok(set(cur) == {"id", "match", "date", "status", "closes_at", "players", "voters", "my_ballot"} and cur["voters"] == 4, "pendant le vote : présents, votants, échéance et mon bulletin seulement")
raw = c.get("/motm").text
ok("points" not in json.dumps(cur) and "podium" not in raw and "ranking" not in raw, "aucun point ni classement dans l'API publique (même sans compte)")
ok(c.get("/motm").json()["current"][0].get("my_ballot") is None, "sans compte : pas de bulletin")
adm = c.get("/admin/motm", headers=A).json(); a1 = next(x for x in adm if x["id"] == vid)
ok(a1["ranking"][0] == {"player": "Lucas", "points": 5 + 5 + 5 + 3, "firsts": 3, "seconds": 1, "thirds": 0} and a1["ballots"] == 4, "l'admin voit le classement complet pendant le vote (barème 5/3/1)")
ok(c.get("/admin/motm").status_code == 403, "classement admin : clé obligatoire")

print("4) FERMETURE À 24 H ET PREMIÈRE CARTE")
CLOCK[0] = T0 + timedelta(hours=24) - timedelta(seconds=1)
ok(vote("v5", vid, "Tom", "Enzo", "Léo").status_code == 200 and vrow(vid).status == "open", "une seconde avant l'échéance : on vote encore")
ok(leg("Lucas") is None, "Lucas n'a pas encore de légendaire")
CLOCK[0] = T0 + timedelta(hours=24)
g = pub(); h = g["history"][0]
ok(g["current"] == [] and vrow(vid).status == "closed" and h["voters"] == 5, "à 24 h exactement : fermé au premier accès")
ok([p["player"] for p in h["podium"]] == ["Lucas", "Hugo", "Tom"] and [p["points"] for p in h["podium"]] == [18, 10, 5], "podium révélé avec les points")
ok(h["created"]["player"] == "Lucas" and h["boosted"] == [] and leg("Lucas") is not None and GL.card_note(leg("Lucas").player, "legendaire", leg("Lucas")) == 90, "cas 1 : le 1er n'a pas de légendaire → elle est créée (note 90)")
ok(vote("v1", vid, "Hugo", "Lucas", "Nathan").status_code == 400, "après la fermeture : bulletin non modifiable (400)")
names_pub = json.dumps(h["podium"]) + json.dumps({k: v for k, v in h.items() if k not in ("players", "my_ballot")})
ok(not any(n in names_pub for n in ("Léo", "Enzo", "Nathan")) and db.query(M.MotmPoint).filter_by(vote_id=vid).count() == 6, "hors podium : jamais publiés, mais leurs points sont conservés (6 joueurs votés en base)")
ok(db.query(Card).join(Player).filter(Player.name == "Lucas", Card.tier == Tier.legendaire).count() == 1, "la carte est créée dans le jeu, une seule fois")
pts = {r.player_name: r.points for r in db.query(M.MotmPoint).filter_by(vote_id=vid)}
ok(pts == {"Lucas": 18, "Hugo": 10, "Nathan": 4, "Léo": 4, "Enzo": 4, "Tom": 5}, "points de tous les joueurs votés : %s" % pts)
db.expire_all(); m = db.get(Match, vrow(vid).match_id)
ok(m.motm_player is not None and m.motm_player.name == "Lucas" and m.motm_player.homme_du_match_count == 1, "champ « homme du match » vide : le 1er du vote le devient (statistiques)")

print("5) DOUBLE FERMETURE")
ok(M.close_vote(db, vrow(vid)) is False and M.close_due(db) == 0 and c.post("/admin/motm-close", json={"vote_id": vid}, headers=A).status_code == 400, "fermer à nouveau : aucun effet")
ok(db.query(Card).join(Player).filter(Player.name == "Lucas", Card.tier == Tier.legendaire).count() == 1 and db.query(M.MotmPoint).filter_by(vote_id=vid).count() == 6, "toujours une seule carte et les mêmes points")

def full_vote(ballots, lineup=LINEUP, hdm=None):
    CLOCK[0] = CLOCK[0] + timedelta(days=1)
    r = record(lineup, hdm=hdm); vid = r.json()["motm_vote"]["id"]
    for p, b in zip(("v1", "v2", "v3", "v4", "v5"), ballots):
        assert vote(p, vid, *b).status_code == 200
    CLOCK[0] = CLOCK[0] + timedelta(hours=24)
    pub(); return vid, json.loads(vrow(vid).result_json or "{}")

print("6) RÈGLE DES CARTES")
v2, res = full_vote([("Lucas", "Hugo", "Nathan")] * 3)
ok(res["boosted"] == [{"player": "Lucas", "note": 92}] and res["created"]["player"] == "Hugo", "cas 2 : 1er avec carte (+2 → 92), carte créée pour le 2e")
v3, res = full_vote([("Lucas", "Hugo", "Nathan")] * 3)
ok(res["boosted"] == [{"player": "Lucas", "note": 94}, {"player": "Hugo", "note": 92}] and res["created"]["player"] == "Nathan", "cas 3 : 1er et 2e +2, carte créée pour le 3e")
v4, res = full_vote([("Lucas", "Hugo", "Nathan")] * 3)
ok(res["created"] is None and res["boosted"] == [{"player": "Lucas", "note": 96}, {"player": "Hugo", "note": 94}, {"player": "Nathan", "note": 92}], "tous en ont une : tous +2, aucune carte créée ; Lucas passe à 96 (pas de plafond)")
L = leg("Lucas")
ok(GL.get_display_note(L.player, "legendaire", L)["value"] == 96, "la note affichée de la carte est 96")
mem = DE.build_members([(L, "ATT")], None)[0]
ok(mem["base_note"] == 96 and abs(mem["effective"] - 96) < 1e-9, "le moteur 1v1 utilise 96")
ok(GL.card_note(L.player, "legendaire", None) == 90, "sans carte précise, la légendaire de base reste à 90")

print("7) DÉPARTAGE")
CLOCK[0] += timedelta(days=1); vt = record().json()["motm_vote"]["id"]
for p, b in zip(("v1", "v2", "v3"), [("Lucas", "Hugo", "Tom"), ("Enzo", "Hugo", "Lucas"), ("Tom", "Léo", "Nathan")]): vote(p, vt, *b)
t = [(r["player"], r["points"]) for r in M.tally(db, vrow(vt))]
ok(t[:3] == [("Lucas", 6), ("Tom", 6), ("Hugo", 6)], "égalité à 6 points : d'abord le nombre de 1res places (Lucas et Tom avant Hugo), puis l'ordre alphabétique (Lucas avant Tom) : %s" % t)
ok(c.post("/admin/motm-cancel", json={"vote_id": vt}, headers=A).status_code == 200 and vrow(vt).status == "cancelled", "l'admin annule un vote ouvert : pas de résultat")
ok(vote("v4", vt, "Lucas", "Hugo", "Tom").status_code == 404, "vote annulé : introuvable pour les joueurs")

print("8) MOINS DE 3 BULLETINS")
before = leg("Lucas").note
v5, res = full_vote([("Lucas", "Hugo", "Nathan"), ("Léo", "Hugo", "Lucas")])
h = next(x for x in pub()["history"] if x["id"] == v5)
ok(vrow(v5).status == "no_result" and h["status"] == "no_result" and "podium" not in h and leg("Lucas").note == before, "2 bulletins : clôturé sans résultat ni carte")
msgs = c.get("/chat", params={"limit": 200}, headers=H["v1"]).json()["messages"]
ok(any("pas assez de votes" in m["text"] for m in msgs), "message public « pas assez de votes » dans le chat")
ok(db.query(AdminLog).filter(AdminLog.summary.like("%sans résultat%")).count() >= 1, "mention dans le journal de l'administration")

print("9) CHAMP « HOMME DU MATCH » DÉJÀ REMPLI")
v6, res = full_vote([("Hugo", "Lucas", "Nathan")] * 3, hdm="Tom")
db.expire_all(); m = db.get(Match, vrow(v6).match_id)
ok(m.motm_player.name == "Tom" and res["podium"][0]["player"] == "Hugo", "le champ rempli par l'admin reste (Tom), même si Hugo gagne le vote")

print("10) ADMIN : PROLONGER, CLÔTURER, SUPPRIMER LE MATCH")
CLOCK[0] += timedelta(days=1); r = record(); va = r.json()["motm_vote"]["id"]; end0 = vrow(va).closes_at
ok(c.post("/admin/motm-extend", json={"hours": 6}, headers=A).status_code == 200 and vrow(va).closes_at == end0 + timedelta(hours=6), "prolonger de 6 h (vote ouvert trouvé sans identifiant)")
for p in ("v1", "v2", "v3"): vote(p, va, "Enzo", "Tom", "Léo")
r = c.post("/admin/motm-close", json={"vote_id": va}, headers=A)
ok(r.status_code == 200 and vrow(va).status == "closed" and r.json()["ranking"][0]["player"] == "Enzo", "clôturer tout de suite : résultat appliqué")
ok(leg("Enzo") is not None, "Enzo, sans légendaire, reçoit la sienne")
CLOCK[0] += timedelta(days=1); r = record(); vd = r.json()["motm_vote"]["id"]; mid = vrow(vd).match_id; mt = db.get(Match, mid)
c.post("/admin/delete-match", json={"date": mt.date.date().isoformat(), "opponent": mt.opponent}, headers=A)
ok(vrow(vd).status == "cancelled", "match supprimé pendant son vote : vote annulé")
CLOCK[0] += timedelta(days=2); M.close_due(db); ok(vrow(vd).status == "cancelled", "et il n'est jamais appliqué")

print("11) SAISON DES VOTES (PRIVÉE)")
ok(c.post("/admin/motm-season-create", json={"name": "Saison test", "starts": "2026-11-01", "ends": "2027-06-30"}).status_code == 403, "créer une saison : clé admin obligatoire")
s = c.post("/admin/motm-season-create", json={"name": "Saison test", "starts": "2026-11-01", "ends": "2027-06-30"}, headers=A).json(); sid = s["id"]
ok(c.post("/admin/motm-season-create", json={"name": "Autre", "starts": "2027-01-01", "ends": "2027-02-01"}, headers=A).status_code == 400, "deux saisons ouvertes qui se chevauchent : refusé")
vs1, _ = full_vote([("Tom", "Enzo", "Léo"), ("Tom", "Léo", "Enzo"), ("Enzo", "Tom", "Nathan")])
vs2, _ = full_vote([("Léo", "Nathan", "Tom"), ("Léo", "Tom", "Nathan"), ("Nathan", "Léo", "Hugo")])
sv = c.get("/admin/motm-season", params={"season_id": sid}, headers=A).json(); tot = {r["player"]: r["points"] for r in sv["ranking"]}
ok(sv["votes"] == 2 and tot == {"Tom": 5 + 5 + 3 + 1 + 3, "Enzo": 3 + 1 + 5, "Léo": 1 + 3 + 5 + 5 + 3, "Nathan": 1 + 3 + 1 + 5, "Hugo": 1}, "les points de TOUS les joueurs votés s'ajoutent (podium ou non) : %s" % tot)
ok(sv["ranking"][0]["player"] == "Léo" and sv["ranking"][0]["points"] == 17, "Léo mène la saison (17 points)")
ok(c.get("/admin/motm-season").status_code == 403 and "Saison test" not in c.get("/motm", headers=H["v1"]).text and "season" not in c.get("/motm").text, "classement de la saison : jamais visible des joueurs")
cl = c.post("/admin/motm-season-close", json={"season_id": sid}, headers=A).json()
ok(cl["status"] == "ok" and [r["player"] for r in cl["podium"]] == ["Léo", "Tom", "Nathan"] and cl["annonce_privee"][0].startswith("homme de la saison : Léo"), "clôture : classement figé, homme de la saison, 2e et 3e montrés à l'admin")
msgs = c.get("/chat", params={"limit": 200}, headers=H["v1"]).json()["messages"]
ok(not any("Homme de la saison" in m["text"] for m in msgs), "aucune annonce publique à la clôture")
full_vote([("Hugo", "Lucas", "Nathan")] * 3)
ok(c.get("/admin/motm-season", params={"season_id": sid}, headers=A).json()["ranking"] == cl["ranking"], "un vote clôturé après la saison ne change pas le classement figé")
ok(c.post("/admin/motm-season-publish", json={"season_id": sid}, headers=A).status_code == 200 and any("Homme de la saison" in m["text"] and "Léo" in m["text"] for m in c.get("/chat", params={"limit": 200}, headers=H["v1"]).json()["messages"]), "publication du podium dans le chat sur commande")

print("12) SUPPRESSION D'UN COMPTE")
CLOCK[0] += timedelta(days=1); vx = record().json()["motm_vote"]["id"]; vote("v5", vx, "Lucas", "Hugo", "Tom")
c.post("/admin/delete-user", json={"pseudo": "v5"}, headers=A)
ok(db.query(M.MotmBallot).filter_by(vote_id=vx).count() == 0 and db.query(M.MotmBallot).filter_by(vote_id=vid).count() == 5, "son bulletin du vote ouvert disparaît ; les votes clôturés gardent les leurs")
print("BILAN (homme du match) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
