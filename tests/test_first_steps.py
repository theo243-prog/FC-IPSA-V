"""
Test : Premiers pas (5 objectifs des nouveaux comptes, récompense unique de 20 crédits + 1 pack classique, comptes de plus de 14 jours exclus,
remise à zéro par l'admin). Lancé par tests/run_tests.py.
"""
import base64
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import first_steps as FS, missions as MI, tournament as TN, club as CL, game_logic as GL
from app.models import User, Card, Player, OwnedCard, Tier, Duel
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
card = lambda n, t: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
TEAM = [("Mathis", "GB"), ("Nathan", "DEF"), ("Hugo", "MC"), ("Enzo", "MC"), ("Lucas", "ATT")]
def mk(p, credits=100):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits
    for n, _ in TEAM: db.add(OwnedCard(user_id=u.id, card_id=card(n, "commune").id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
team = lambda: {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n, "commune").id, "slot_category": s} for n, s in TEAM]}
fs = lambda p: c.get("/first-steps", headers=H[p]).json()
steps = lambda p: {s["id"]: s["done"] for s in fs(p)["steps"]}
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9").decode()
def claim_one_mission(p):
    """Termine la première mission du jour du joueur (sans passer par son événement) puis la récupère."""
    u = U(p); m = MI.todays_missions(u.id, GL.today_paris())[0]; c.get("/missions", headers=H[p])
    r = db.query(MI.UserDaily).filter_by(user_id=u.id).first(); prog = json.loads(r.progress or "{}"); prog[m["id"]] = m["target"]; r.progress = json.dumps(prog); db.commit()
    return c.post("/missions/claim", json={"kind": "mission", "mission_id": m["id"]}, headers=H[p])
H = {p: mk(p) for p in ("neo", "ada", "vieux", "solo")}
old = U("vieux"); old.created_at = datetime.utcnow() - timedelta(days=15); db.commit()

print("1) UN COMPTE NEUF")
g = fs("neo")
ok(g["visible"] and g["done"] == 0 and g["total"] == 5 and [s["id"] for s in g["steps"]] == ["pack", "photo", "duel", "chat", "mission"] and g["claimable"] is False, "5 objectifs dans l'ordre (pack, photo, match 1v1, chat, mission), 0/5")
ok(g["reward"] == {"credits": 20, "pack": "classique"} and g["ends_at"].startswith((U("neo").created_at + timedelta(days=14)).date().isoformat()), "récompense annoncée : 20 crédits + 1 pack classique ; visible jusqu'à 14 jours après la création du compte")
ok(steps("neo")["chat"] is False, "l'annonce automatique « neo a rejoint le club » (à son nom) ne coche pas le chat")
ok(c.post("/first-steps/claim", headers=H["neo"]).status_code == 400, "récupérer à 0/5 : refusé (400)")
ok(c.get("/first-steps").status_code == 401 and c.post("/first-steps/claim").status_code == 401, "sans compte : 401")

print("2) CHAQUE OBJECTIF SE COCHE AU BON ÉVÉNEMENT")
r = c.post("/pack/open", json={}, headers=H["neo"]); s = steps("neo")
ok(r.status_code == 200 and s["pack"] and not any(s[k] for k in ("photo", "duel", "chat", "mission")), "ouvrir un pack coche « pack », et seulement lui")
r = c.post("/me/avatar", json={"image": JPEG}, headers=H["neo"]); ok(r.status_code == 200 and steps("neo")["photo"], "ajouter une photo de profil coche « photo »")
c.delete("/me/avatar", headers=H["neo"]); ok(steps("neo")["photo"], "retirer sa photo ensuite ne décoche pas l'objectif (indicateur durable)")
# ni le défi du club, ni le tournoi ne comptent comme match 1v1
CL.today = lambda: "2026-11-12"; c.post("/club/facile/play", json=team(), headers=H["neo"])
t = TN.Tournament(month_key="2099-02", status="running", size=2, rounds=1); db.add(t); db.flush(); now = datetime(2026, 11, 12, 10); spec = json.dumps(team())
m = TN.TournamentMatch(tournament_id=t.id, round=1, slot=0, p1_id=U("neo").id, p2_id=U("solo").id, team1=spec, team2=spec, opens_at=now, deadline_at=now)
db.add_all([TN.TournamentEntry(tournament_id=t.id, user_id=U(p).id, paid=0, seed=i) for i, p in enumerate(("neo", "solo"), 1)] + [m]); db.flush(); TN._resolve(db, t, m, now); db.commit()
ok(m.via == "play" and not steps("neo")["duel"] and db.query(Duel).count() == 0, "un match du défi du club et un match de tournoi ne cochent pas « match 1v1 »")
pid = c.post("/duel/proposals", json={**team(), "stake": 1}, headers=H["ada"]).json()["id"]
ok(not steps("ada")["duel"], "proposer un défi ne suffit pas : il faut qu'il soit joué")
r = c.post("/duel/proposals/%s/play" % pid, json=team(), headers=H["neo"])
ok(r.status_code == 200 and steps("neo")["duel"] and steps("ada")["duel"], "un match 1v1 joué coche « match 1v1 » pour les deux : celui qui l'a joué et le créateur du défi")
r = c.post("/chat", json={"text": "Salut le club !"}, headers=H["neo"]); ok(r.status_code == 200 and steps("neo")["chat"], "écrire un message dans le chat coche « chat »")
c.post("/admin/chat-delete", json={"id": r.json()["id"]}, headers=A); ok(steps("neo")["chat"], "même si l'admin supprime le message, l'objectif reste coché (compteur à vie)")
c.get("/missions", headers=H["neo"]); c.post("/missions/claim", json={"kind": "streak"}, headers=H["neo"]); ok(not steps("neo")["mission"], "récupérer la récompense de la série de connexion ne compte pas comme mission")
r = claim_one_mission("neo"); g = fs("neo")
ok(r.status_code == 200 and g["steps"][4]["done"] and g["done"] == 5 and g["claimable"], "récupérer une mission du jour coche « mission » : 5/5, récompense disponible")

print("3) LA RÉCOMPENSE")
cr0, pk0 = U("neo").credits, U("neo").pack_state.shop_pack_tokens
r = c.post("/first-steps/claim", headers=H["neo"])
ok(r.status_code == 200 and U("neo").credits == cr0 + 20 and U("neo").pack_state.shop_pack_tokens == pk0 + 1, "5/5 : +20 crédits et +1 pack classique")
ok(db.get(FS.FirstStepsClaim, U("neo").id).claimed_at is not None, "la date de récupération est enregistrée")
ok(c.post("/first-steps/claim", headers=H["neo"]).status_code == 400 and U("neo").credits == cr0 + 20, "deuxième récupération : refusée, rien de plus versé")
ok(fs("neo") == {"visible": False}, "une fois récupérée, la carte disparaît (masquée)")
ok(fs("ada")["done"] == 1 and c.post("/first-steps/claim", headers=H["ada"]).status_code == 400, "ada (1/5) : récupérer est refusé")

print("4) COMPTE DE PLUS DE 14 JOURS")
c.post("/pack/open", json={}, headers=H["vieux"]); c.post("/me/avatar", json={"image": JPEG}, headers=H["vieux"]); c.post("/chat", json={"text": "hello"}, headers=H["vieux"])
pid = c.post("/duel/proposals", json={**team(), "stake": 1}, headers=H["solo"]).json()["id"]; c.post("/duel/proposals/%s/play" % pid, json=team(), headers=H["vieux"]); claim_one_mission("vieux")
ok(FS.done_steps(db, U("vieux")) == {k: True for k, _ in FS.STEPS}, "« vieux » a pourtant fait les 5 objectifs")
cr = U("vieux").credits
ok(fs("vieux") == {"visible": False} and c.post("/first-steps/claim", headers=H["vieux"]).status_code == 400 and U("vieux").credits == cr, "compte créé il y a 15 jours : rien d'affiché, récupération refusée")
ok(FS.eligible(U("solo")) and not FS.eligible(U("solo"), datetime.utcnow() + timedelta(days=14, minutes=1)), "un compte n'y a droit que pendant ses 14 premiers jours")

print("5) ADMINISTRATION")
ok(c.post("/admin/first-steps-reset", json={"pseudo": "neo"}).status_code == 403, "sans clé admin : 403")
ok(c.post("/admin/first-steps-reset", json={"pseudo": "personne"}, headers=A).status_code == 404, "pseudo inconnu : 404")
r = c.post("/admin/first-steps-reset", json={"pseudo": "neo"}, headers=A); g = fs("neo")
ok(r.status_code == 200 and r.json()["recuperation_effacee"] and g["visible"] and g["done"] == 5 and g["claimable"], "remise à zéro : la carte revient, les objectifs restent faits (5/5)")
cr = U("neo").credits; ok(c.post("/first-steps/claim", headers=H["neo"]).status_code == 200 and U("neo").credits == cr + 20, "la récompense peut être récupérée de nouveau (pour tester)")
r = c.post("/admin/first-steps-reset", json={"pseudo": "vieux"}, headers=A); ok(r.status_code == 200 and r.json()["compte_eligible"] is False and fs("vieux") == {"visible": False}, "sur un compte de plus de 14 jours, la remise à zéro ne le rend pas visible")
log = c.get("/admin/log", params={"q": "Premiers pas"}, headers=A).json(); ok(any("neo" in x["action"] for x in log), "la remise à zéro est notée dans le journal de l'administration")
c.post("/admin/delete-user", json={"pseudo": "neo"}, headers=A); ok(db.query(FS.FirstStepsClaim).count() == 0, "supprimer un compte efface sa récupération des Premiers pas")

print("BILAN (premiers pas) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
