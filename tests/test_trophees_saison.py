"""
Test : trophées de fin de saison en plus du podium. Les 3 joueurs qui ont joué le plus de matchs 1v1 du mois (« Joueur le plus assidu
de la saison », 2e, 3e) et, en surprise, la lanterne rouge (le dernier en Elo parmi les joueurs classés). Lancé par tests/run_tests.py.
"""
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import seasons as S
from app.models import User, Card, Player, OwnedCard, Tier, Duel
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
for p in ("p1", "p2", "p3", "p4", "p5", "p6"):
    c.post("/auth/register", json={"pseudo": p, "password": "test1234"})
KEY = "2026-09"
t = [0]
def duel(a, b, elo_a, elo_b, sa=1, sb=0):
    t[0] += 1
    db.add(Duel(challenger_id=U(a).id, defender_id=U(b).id, stake=1, formation_challenger="1-2-1", formation_defender="1-2-1", score_challenger=sa, score_defender=sb,
                elo_challenger_before=1000, elo_defender_before=1000, elo_challenger_after=elo_a, elo_defender_after=elo_b, created_at=datetime(2026, 9, 10, 12, 0, t[0])))
# p1 : 12 matchs ; p2 : 10 ; p3 : 8 ; p4 : 6 ; p5 : 5 (dernier en Elo, classé) ; p6 : 2 matchs (pas classé, encore plus bas)
for _ in range(5): duel("p1", "p5", 1200, 800)
for _ in range(4): duel("p1", "p2", 1210, 1100)
for _ in range(3): duel("p1", "p3", 1220, 1050)
for _ in range(6): duel("p2", "p4", 1120, 950)
for _ in range(5): duel("p3", "p4", 1060, 940)
for _ in range(2): duel("p6", "p4", 700, 945)
db.commit()
rows = S.standings(db, KEY)
ass = S.assiduous_of(rows); lan = S.lantern_of(rows)
m = {r["pseudo"]: r["matches"] for r in rows}
expect = [p for p, _ in sorted(m.items(), key=lambda kv: (-kv[1], -{r["pseudo"]: r["elo"] for r in rows}[kv[0]]))][:3]
ok([r["pseudo"] for r in ass] == expect and [r["rank"] for r in ass] == [7, 8, 9], "les 3 qui ont joué le plus de matchs : %s" % [(r["pseudo"], r["matches"]) for r in ass])
ok(lan is not None and lan["pseudo"] == "p5" and lan["rank"] == 10, "lanterne rouge : le dernier en Elo parmi les classés (p5, 800), pas p6 qui n'a joué que 2 matchs")
ok(S.lantern_of([r for r in rows if r["pseudo"] in ("p1", "p2", "p3")]) is None, "moins de 4 joueurs classés : pas de lanterne rouge")
res = S.close_season(db, KEY); db.expire_all()
def has(p, title):
    pl = db.query(Player).filter_by(name="%s (septembre 2026)" % title).first()
    if pl is None: return False
    k = db.query(Card).filter_by(player_id=pl.id, tier=Tier.saison).first()
    o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=k.id).first()
    return o is not None and o.quantity == 1
ok(has(expect[0], "Joueur le plus assidu de la saison") and has(expect[1], "Deuxième joueur le plus assidu de la saison") and has(expect[2], "Troisième joueur le plus assidu de la saison"), "les trophées d'assiduité sont donnés")
ok(has("p5", "Lanterne rouge de la saison") and not has("p6", "Lanterne rouge de la saison"), "la lanterne rouge reçoit sa carte")
ok(has("p1", "Vainqueur de saison"), "le podium reste inchangé (p1 vainqueur)")
ok(len(res["extra_trophies"]) == 4, "4 trophées en plus du podium")
col = {x["player_name"]: x for x in c.get("/collection", headers={"Authorization": "Bearer " + c.post("/auth/login", json={"pseudo": "p5", "password": "test1234"}).json()["token"]}).json() if x.get("quantity")}
tr = col.get("Lanterne rouge de la saison (septembre 2026)")
ok(tr is not None and tr["tier"] == "saison" and tr["trophy"]["rank"] == 10, "la carte apparaît dans la collection de p5 (trophée rang 10)")
from app import changelog_data as CD
ok(not any("lanterne" in (e["title"] + e["text"]).lower() for e in CD.ENTRIES), "la lanterne rouge n'est pas annoncée dans les Nouveautés (surprise)")
print("BILAN (trophées de saison) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
