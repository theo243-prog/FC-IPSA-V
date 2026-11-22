"""
Test : joueurs connectés (points verts des onglets 1v1 et Draft), comptés en mémoire à partir de /me et de la page draft.
Lancé par tests/run_tests.py.
"""
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app import presence as P
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 22, 12, 0)]; P._now = lambda: NOW[0]
def mk(p): return {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]}
H = {p: mk(p) for p in ("on1", "on2", "on3", "ontest")}
c.post("/admin/set-test-account", json={"pseudo": "ontest", "is_test": True}, headers=A)
P.reset()
online = lambda p: c.get("/me", headers=H[p]).json()["online"]

print("1) SITE OUVERT")
ok(online("on1") == {"site": 1, "draft": 0}, "on1 seul : 1 connecté (il se compte), personne sur le draft")
online("on2"); ok(online("on1")["site"] == 2, "on2 ouvre le site : 2")
online("ontest"); ok(online("on1")["site"] == 2, "un compte de test ne compte pas")

print("2) PAGE DRAFT")
d = c.get("/draft", headers=H["on3"]).json()
ok(d["online"] == 1 and online("on1") == {"site": 3, "draft": 1}, "on3 sur la page draft : 1 sur le draft, et il compte aussi sur le site")

print("3) LE TEMPS PASSE")
NOW[0] += timedelta(seconds=45)
ok(online("on1") == {"site": 3, "draft": 0}, "45 s sans signe de vie du draft : il sort du draft, reste sur le site")
NOW[0] += timedelta(seconds=100)
ok(online("on1")["site"] == 1, "2 min 25 plus tard : on2 et on3 ne se sont plus manifestés, seul on1 (qui vient d'appeler /me) reste")
ok("on2" not in str(c.get("/me", headers=H["on1"]).json()["online"]), "seulement des nombres, jamais de pseudo")

print(); print("BILAN (joueurs connectés) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
