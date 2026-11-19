"""
Test : un pack ultra tous les 20 matchs 1v1 joués dans la journée (20e, 40e…), pour chacun des deux joueurs, avec une notification.
Lancé par tests/run_tests.py.
"""
import itertools
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import duel_engine as DE, inbox
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 5000
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {"alice": mk("alice"), "bob": mk("bob"), "cyr": mk("cyr")}
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
cyc = itertools.cycle([1, 1]); DE.draw_goals = lambda xg: next(cyc)
def match(creator="alice", player="bob"):
    pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H[creator]).json()["id"]
    return c.post(f"/duel/proposals/{pid}/play", json=team, headers=H[player]).json()
ultra = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first().pack_state.ultra_pack_tokens)[1]
u0 = {p: ultra(p) for p in H}

print("1) 19 MATCHS : PAS ENCORE")
res = [match() for _ in range(19)]
ok(all(r.get("ultra_to") == [] for r in res) and ultra("alice") == u0["alice"] and ultra("bob") == u0["bob"], "19 matchs dans la journée : pas de pack ultra")

print("2) LE 20e MATCH")
r = match()
ok(sorted(r["ultra_to"]) == ["alice", "bob"] and r["ultra_every"] == 20, "20e match : un pack ultra pour chacun des deux joueurs")
ok(ultra("alice") == u0["alice"] + 1 and ultra("bob") == u0["bob"] + 1, "le pack ultra est dans la réserve des deux")
db.expire_all()
ok(any("Pack ultra" in n.title for n in db.query(inbox.UserNotice).filter_by(user_id=db.query(User).filter_by(pseudo="alice").first().id).all()), "alice (créatrice, pas devant le match) reçoit une notification")

print("3) CHACUN SON COMPTE")
r = match("cyr", "bob")
ok(r["ultra_to"] == [] and ultra("cyr") == u0["cyr"], "21e match de bob, 1er de cyr : rien")
for _ in range(18): match()
r = match()                                                             # 40e match de bob, 39e d'alice
ok(r["ultra_to"] == ["bob"] and ultra("bob") == u0["bob"] + 2 and ultra("alice") == u0["alice"] + 1, "40e match de bob (39e d'alice) : un 2e pack ultra pour bob seulement")
r = match()
ok(r["ultra_to"] == ["alice"] and ultra("alice") == u0["alice"] + 2, "40e match d'alice : son 2e pack ultra")
ok(c.get("/duel/config").json().get("ultra_every_matches") == 20, "/duel/config annonce « tous les 20 matchs »")

print("4) LA BARRE DU SITE (/me)")
u = c.get("/me", headers=H["alice"]).json()["ultra_progress"]
ok(u == {"matches": 40, "every": 20, "progress": 0, "lap": 2, "left": 20}, "alice : 40 matchs aujourd'hui, 2 packs ultra gagnés, la barre repart à 0 / 20 (%s)" % u)
u = c.get("/me", headers=H["cyr"]).json()["ultra_progress"]
ok(u["matches"] == 1 and u["progress"] == 1 and u["left"] == 19 and u["lap"] == 0, "cyr : 1 / 20, encore 19 matchs")

print(); print("BILAN (pack ultra tous les 20 matchs) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
