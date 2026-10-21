"""
Test : sauvegarde de la base (instantané quotidien, export, téléchargement, restauration). Lancer comme test_tournament.py (voir tests/LISEZMOI.md).
"""
import base64, gzip, io, json, os, subprocess, sys, tempfile
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import backup as BK, avatars as AV
from app.models import User, Card
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
tok = c.post("/auth/register", json={"pseudo": "zoe", "password": "test1234"}).json()["token"]; H = {"Authorization": "Bearer " + tok}
jpeg = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/yQALCAABAAEBAREA/8wABgAQEAX/2gAIAQEAAD8A0s8g/9k=")
c.post("/me/avatar", json={"image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}, headers=H)
c.post("/chat", json={"text": "bonjour la sauvegarde"}, headers=H)
read = lambda data: json.loads(gzip.decompress(data).decode("utf-8"))
print("1) L'EXPORT")
r = c.get("/admin/backup-export", headers=A); d = read(r.content)
ok(r.status_code == 200 and r.headers["content-type"] == "application/gzip" and "fc-ipsa-v-sauvegarde-" in r.headers["content-disposition"] and r.headers["content-disposition"].endswith("-export.json.gz\""), "export frais : fichier .json.gz « " + r.headers["content-disposition"].split("filename=")[1] + " »")
ok(c.get("/admin/backup-export").status_code == 403 and c.get("/admin/backups").status_code == 403 and c.post("/admin/backup-now").status_code == 403, "réservé à l'administrateur : 403 sans clé")
ok(d["format"] == BK.FORMAT and "db_backups" not in d["tables"] and "user_sessions" not in d["tables"] and len(d["tables"]) > 30, f"{len(d['tables'])} tables ; ni les connexions ni les instantanés eux-mêmes")
u = d["tables"]["users"]; ci = u["columns"].index("pseudo"); ok(len(u["rows"]) == db.query(User).count() and any(row[ci] == "zoe" for row in u["rows"]), f"tous les comptes y sont ({len(u['rows'])}), dont zoe")
ok(len(d["tables"]["cards"]["rows"]) == db.query(Card).count(), f"toutes les cartes y sont ({len(d['tables']['cards']['rows'])})")
av = d["tables"]["user_avatars"]; blob = av["rows"][0][av["columns"].index("data")]; ok(base64.b64decode(blob["$b64"]) == jpeg, "la photo de profil (octets) est sauvegardée à l'identique")
ok(any(r[d["tables"]["chat_messages"]["columns"].index("text")] == "bonjour la sauvegarde" for r in d["tables"]["chat_messages"]["rows"]), "les messages du chat aussi")
ci_t = d["tables"]["cards"]["columns"].index("tier"); ok({r[ci_t] for r in d["tables"]["cards"]["rows"]} >= {"commune", "rare"}, "les raretés sont enregistrées par leur nom (commune, rare…)")
print("2) UNE SAUVEGARDE À LA MAIN")
r = c.post("/admin/backup-now", headers=A).json(); bid = r["id"]
ok(r["status"] == "ok" and r["kind"] == "manuel" and r["tables"] == len(d["tables"]) and r["rows"] > 50, f"sauvegarde prise : {r['tables']} tables, {r['rows']} lignes, {r['size_kb']} Ko")
lst = c.get("/admin/backups", headers=A).json(); ok(len(lst) == 1 and lst[0]["id"] == bid, "elle apparaît dans la liste")
dl = c.get(f"/admin/backup/{bid}/download", headers=A); ok(dl.status_code == 200 and read(dl.content)["tables"]["users"]["rows"] == u["rows"] and c.get("/admin/backup/inconnu/download", headers=A).status_code == 404, "on la télécharge (contenu identique) ; une sauvegarde inconnue : 404")
d2 = read(c.get("/admin/backup-export", headers=A).content); ok(set(d2["tables"]) == set(d["tables"]), "les sauvegardes ne se contiennent pas elles-mêmes")
ok(any(x["action"] == "Sauvegarde de la base prise à la main" and x["result"] == "OK" for x in c.get("/admin/log", headers=A).json()), "l'action figure dans le journal")
print("3) LA SAUVEGARDE AUTOMATIQUE QUOTIDIENNE (à partir de 4h)")
for x in db.query(BK.DbBackup).all(): db.delete(x)
db.commit(); day = datetime(2027, 3, 10, 3, 0)
BK.tick(db, day); db.expire_all(); ok(db.query(BK.DbBackup).count() == 0, "à 3h : rien (trop tôt)")
BK.tick(db, day.replace(hour=4, minute=1)); db.expire_all(); ok(db.query(BK.DbBackup).filter_by(kind="auto").count() == 1, "à 4h01 : l'instantané du jour est pris")
BK.tick(db, day.replace(hour=15)); BK.tick(db, day.replace(hour=23)); db.expire_all(); ok(db.query(BK.DbBackup).filter_by(kind="auto").count() == 1, "le reste de la journée : pas de deuxième (un seul par jour)")
for k in range(1, 9): BK.tick(db, (day + timedelta(days=k)).replace(hour=5))
db.expire_all(); ok(db.query(BK.DbBackup).filter_by(kind="auto").count() == BK.KEEP_AUTO == 7, "au fil des jours : on ne garde que les 7 derniers automatiques")
for _ in range(5): c.post("/admin/backup-now", headers=A)
db.expire_all(); ok(db.query(BK.DbBackup).filter_by(kind="manuel").count() == BK.KEEP_MANUAL == 3 and db.query(BK.DbBackup).filter_by(kind="auto").count() == 7, "et les 3 derniers manuels, sans effacer les automatiques")
print("4) LA RESTAURATION (base vide)")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "sauvegarde.json.gz"); open(path, "wb").write(c.get("/admin/backup-export", headers=A).content)
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + os.path.join(tmp, "neuve.db"), "PYTHONPATH": "."}
    r1 = subprocess.run([sys.executable, "-m", "app.restore_backup", path], env=env, capture_output=True, text=True)
    ok(r1.returncode == 0 and "Restauration terminée" in r1.stdout, "restauration dans une base vide : " + r1.stdout.strip().split("\n")[-1])
    probe = "import json\nfrom app.database import SessionLocal\nfrom app.models import User, Card, OwnedCard\nfrom app.avatars import UserAvatar\nfrom app.chat import ChatMessage\nfrom app.security import verify_password\nd = SessionLocal(); u = d.query(User).filter_by(pseudo='zoe').first()\nprint(json.dumps({'users': d.query(User).count(), 'cards': d.query(Card).count(), 'owned': d.query(OwnedCard).count(), 'avatar': len(bytes(d.query(UserAvatar).first().data)), 'chat': d.query(ChatMessage).count(), 'login': bool(verify_password('test1234', u.password_hash)), 'created': u.created_at.isoformat()[:4]}))"
    p = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True); got = json.loads(p.stdout.strip().split("\n")[-1]) if p.returncode == 0 else {}
    ok(got.get("users") == db.query(User).count() and got.get("cards") == db.query(Card).count() and got.get("avatar") == len(jpeg) and got.get("chat", 0) >= 1 and got.get("login") is True, f"la base restaurée est identique : {got}")
    r2 = subprocess.run([sys.executable, "-m", "app.restore_backup", path], env=env, capture_output=True, text=True)
    ok(r2.returncode != 0 and "n'est pas vide" in (r2.stdout + r2.stderr), "restaurer dans une base NON vide : refusé (jamais d'écrasement ni de doublons)")
print(); print("BILAN (sauvegarde de la base) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
