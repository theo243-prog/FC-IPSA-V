"""
Test : points bonus du Pass (au-delà du niveau 30) convertis en crédits à la fin du mois, 20 points = 1 crédit, sans plafond, une seule fois.
Lancé par tests/run_tests.py.
"""
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import battlepass as BP, inbox
from app.models import User
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 20, 10, 0)]; BP.now_paris = lambda: NOW[0]
db = SessionLocal()
H = {}
for p in ("ana", "bob", "cle", "dan"):
    H[p] = {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def setp(p, points, key="2026-11"):
    r = BP._progress(db, U(p).id, key, create=True); r.points = points; db.commit()
setp("ana", 4250); setp("bob", 3010); setp("cle", 1800); setp("dan", 5000, "2026-10")
cred0 = {p: U(p).credits for p in H}

print("1) PENDANT LE MOIS : APERÇU")
b = c.get("/pass", headers=H["ana"]).json()["current"]["bonus"]
ok(b == {"points": 1250, "credits": 62, "converted": False, "per_credit": 20}, "ana : 1250 points bonus -> 62 crédits prévus (20 points = 1 crédit, arrondi en dessous)")
ok(c.get("/pass", headers=H["cle"]).json()["current"]["bonus"]["points"] == 0, "sous 3000 points : aucun point bonus")
ok(BP.convert_bonus(db, "2026-11", NOW[0]) == 0 and U("ana").credits == cred0["ana"], "rien n'est converti avant la fin du mois")

print("2) FIN DU MOIS : CONVERSION AUTOMATIQUE")
NOW[0] = datetime(2026, 12, 1, 0, 1); BP.tick(db)
ok(U("ana").credits == cred0["ana"] + 62, "ana reçoit 62 crédits")
ok(U("bob").credits == cred0["bob"], "bob (10 points bonus) : 0 crédit")
ok(U("cle").credits == cred0["cle"], "cle (pas de points bonus) : rien")
db.expire_all()
ok(any("Points bonus" in n.title for n in db.query(inbox.UserNotice).filter_by(user_id=U("ana").id).all()), "notification à ana")
prev = c.get("/pass", headers=H["ana"]).json()["previous"]["bonus"]
ok(prev["converted"] and prev["credits"] == 62, "le Pass en rattrapage affiche « convertis : +62 »")

print("3) UNE SEULE FOIS")
BP.tick(db); BP.convert_bonus(db, "2026-11", NOW[0])
ok(U("ana").credits == cred0["ana"] + 62, "pas de deuxième versement")
ok(U("dan").credits == cred0["dan"], "les Pass d'avant novembre 2026 ne sont pas convertis")

print(); print("BILAN (points bonus du Pass) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
