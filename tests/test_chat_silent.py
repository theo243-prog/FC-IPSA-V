"""
Test : couper les annonces automatiques du chat pour un compte (compte d'administration). Ses messages écrits à la main restent publiés,
les autres joueurs gardent leurs annonces, et on peut les rétablir. Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import chat as CH
from app.models import User
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p, credits=1000):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit()
    return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("chef", "joueur")}
msgs = lambda: c.get("/chat", params={"limit": 200}, headers=H["joueur"]).json()["messages"]
events_of = lambda p: [m for m in msgs() if m["kind"] == "event" and p in m["text"]]

print("1) COUPER LES ANNONCES")
ok(c.post("/admin/chat-silent", json={"pseudo": "chef"}).status_code == 403 and c.post("/admin/chat-silent", json={"pseudo": "personne"}, headers=A).status_code == 404, "403 sans clé admin, 404 pseudo inconnu")
r = c.post("/admin/chat-silent", json={"pseudo": "chef", "enabled": 1}, headers=A); ok(r.status_code == 200 and r.json()["annonces_coupees"] is True and CH.is_silent(db, U("chef")), "les annonces automatiques de « chef » sont coupées (1 accepté comme oui)")

print("2) EFFETS")
before = len(events_of("chef"))
ok(c.post("/pass/premium", headers=H["chef"]).status_code == 200 and len(events_of("chef")) == before, "« chef » prend le Pass Premium : aucune annonce dans le chat")
ok(c.post("/pass/premium", headers=H["joueur"]).status_code == 200 and any("Premium" in m["text"] for m in events_of("joueur")), "un autre joueur garde son annonce")
CH.add_event(db, "🏅 chef a obtenu un succès", U("chef")); CH.add_event(db, "🔁 chef et joueur ont échangé des cartes", None, also=(U("joueur"), U("chef"))); db.commit()
ok(len(events_of("chef")) == before, "succès et échange de cartes impliquant « chef » : rien n'est publié")
CH.post_event(db, "📣 annonce du club"); ok(any(m["text"] == "📣 annonce du club" for m in msgs()), "les annonces du club (sans joueur) ne changent pas")
r = c.post("/chat", json={"text": "Bienvenue à tous !"}, headers=H["chef"]); ok(r.status_code == 200 and any(m["kind"] == "user" and m["text"] == "Bienvenue à tous !" and m["pseudo"] == "chef" for m in msgs()), "les messages écrits à la main par « chef » restent publiés")

print("3) RÉTABLIR")
ok(c.post("/admin/chat-silent", json={"pseudo": "chef", "enabled": 0}, headers=A).status_code == 200 and not CH.is_silent(db, U("chef")), "on peut rétablir ses annonces")
CH.post_event(db, "🏅 chef a obtenu un autre succès", U("chef")); ok(len(events_of("chef")) == before + 1, "ses annonces reparaissent")
log = c.get("/admin/log", params={"q": "Annonces automatiques"}, headers=A).json(); ok(sum(1 for x in log if "chef" in x["action"] and x["result"] == "OK") == 2, "les deux commandes sont notées dans le journal de l'administration")

print("4) PAGE D'ADMINISTRATION")
import re
from app.admin_page import ADMIN_HTML
bad = [l.strip()[:60] for l in ADMIN_HTML.splitlines() if l.lstrip().startswith("{tab:") and re.search(r"(?<!\\)\w'\w", l)]
ok(not bad, "aucune commande de la page d'administration n'a d'apostrophe non échappée (elle casserait toute la page) %s" % (bad or ""))
print("BILAN (annonces du chat) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
