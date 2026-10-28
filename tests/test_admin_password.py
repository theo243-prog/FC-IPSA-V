"""
Test : mot de passe oublié (commande d'administration /admin/set-password). Le compte garde tout, ses appareils sont déconnectés,
et le mot de passe n'est jamais écrit dans le journal de l'administration. Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import sessions as SE, admin_tools as AT
from app.models import User
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
login = lambda p, pw: c.post("/auth/login", json={"pseudo": p, "password": pw})
NEW = "Nouveau-Mdp-42"

print("1) AVANT")
t1 = c.post("/auth/register", json={"pseudo": "Étourdi", "password": "ancien1"}).json()["token"]
t2 = login("Étourdi", "ancien1").json()["token"]                                  # connecté sur deux appareils
c.post("/auth/register", json={"pseudo": "voisin", "password": "voisin1"})
u = U("Étourdi"); u.credits = 321; db.commit()
ok(c.get("/me", headers={"Authorization": "Bearer " + t1}).status_code == 200 and c.get("/me", headers={"Authorization": "Bearer " + t2}).status_code == 200, "le joueur est connecté sur deux appareils")

print("2) REFUS")
ok(c.post("/admin/set-password", json={"pseudo": "Étourdi", "new_password": NEW}).status_code == 403, "sans clé admin : 403")
ok(c.post("/admin/set-password", json={"pseudo": "Étourdi", "new_password": NEW}, headers={"X-Admin-Key": "mauvaise"}).status_code == 403, "mauvaise clé admin : 403")
ok(c.post("/admin/set-password", json={"pseudo": "etourdi", "new_password": NEW}, headers=A).status_code == 404, "pseudo inexact (sans majuscule ni accent) : 404")
ok(c.post("/admin/set-password", json={"pseudo": "Étourdi", "new_password": "abc"}, headers=A).status_code == 422 and c.post("/admin/set-password", json={"pseudo": "Étourdi", "new_password": "x" * 73}, headers=A).status_code == 422, "mot de passe trop court (3) ou trop long (73) : refusé (422)")
ok(login("Étourdi", "ancien1").status_code == 200, "après ces refus, l'ancien mot de passe marche toujours")
t3 = login("Étourdi", "ancien1").json()["token"]

print("3) NOUVEAU MOT DE PASSE")
r = c.post("/admin/set-password", json={"pseudo": "Étourdi", "new_password": NEW}, headers=A)
ok(r.status_code == 200 and r.json()["pseudo"] == "Étourdi" and r.json()["appareils_deconnectes"] == 4, "commande acceptée : %s appareil(s) déconnecté(s)" % r.json().get("appareils_deconnectes"))
ok(login("Étourdi", "ancien1").status_code == 401, "l'ancien mot de passe ne marche plus")
ok(all(c.get("/me", headers={"Authorization": "Bearer " + t}).status_code == 401 for t in (t1, t2, t3)), "toutes les anciennes connexions sont fermées (401)")
r = login("Étourdi", NEW); ok(r.status_code == 200 and c.get("/me", headers={"Authorization": "Bearer " + r.json()["token"]}).json()["credits"] == 321, "connexion avec le nouveau mot de passe : le compte a gardé ses 321 crédits")
ok(login("voisin", "voisin1").status_code == 200, "les autres comptes ne sont pas touchés")
ok(U("Étourdi").password_hash.startswith("$2") and NEW not in U("Étourdi").password_hash, "le mot de passe est enregistré chiffré (bcrypt), jamais en clair")

print("4) JOURNAL DE L'ADMINISTRATION")
rows = db.query(AT.AdminLog).filter(AT.AdminLog.path == "/admin/set-password").all()
ok(len(rows) == 6, "les 6 tentatives (refusées ou non) sont notées dans le journal")
ok(not any(NEW in (r.payload or "") or NEW in r.summary or "abc" in (r.payload or "") for r in rows) and all("(masqué)" in (r.payload or "") for r in rows), "le mot de passe n'y apparaît jamais (« (masqué) »)")
log = c.get("/admin/log", params={"q": "mot de passe"}, headers=A).json()
ok(any(x["action"] == "Nouveau mot de passe pour Étourdi (tous ses appareils déconnectés)" and x["result"] == "OK" for x in log), "résumé lisible : « Nouveau mot de passe pour Étourdi (tous ses appareils déconnectés) »")
AT.write_entry("POST", "/admin/set-password", 400, b"pas du json " + NEW.encode(), "1.2.3.4")
last = db.query(AT.AdminLog).order_by(AT.AdminLog.id.desc()).first(); ok(last.payload == "(masqué)", "un contenu illisible envoyé à cette commande n'est pas recopié non plus")
ok("new_password" in c.get("/admin-panel").text and "set-password" in c.get("/admin-panel").text, "la page d'administration propose le formulaire")

print("BILAN (mot de passe oublié) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
