"""
Test : événement « elo_half » (Elo perdu divisé par 2 en 1v1, gains inchangés), lancé depuis l'administration ; l'Elo rejoué à l'identique.
Lancé par tests/run_tests.py.
"""
import itertools, json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import duel_engine as DE, events as EV
from app.models import User, Card, Player, OwnedCard, Tier, Duel
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
H = {"alice": mk("alice"), "bob": mk("bob")}
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
cyc = {}
DE.draw_goals = lambda xg: next(cyc["g"])
def match():
    """alice crée le défi, bob le joue et gagne 3-0 (alice perd)."""
    cyc["g"] = itertools.cycle([3, 0])
    pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["alice"]).json()["id"]
    return c.post(f"/duel/proposals/{pid}/play", json=team, headers=H["bob"]).json()
elo = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first().elo)[1]

print("1) LE CALCUL")
ok(DE.elo_delta(1000, 1000, 0) == -16 and DE.elo_delta(1000, 1000, 0, loss_factor=0.5) == -8, "Elo égal : défaite -16, -8 pendant l'événement")
ok(DE.elo_delta(1400, 1000, 0, True, loss_factor=0.5) == -8 and DE.elo_delta(1000, 1000, 1, loss_factor=0.5) == 20, "créateur favori battu : -15 → -8 ; une victoire rapporte toujours +20")
ok(EV.elo_loss_factor(db) == 1.0, "sans événement : pertes normales")

print("2) SANS ÉVÉNEMENT")
r = match(); ok(r["elo_challenger_after"] - r["elo_challenger_before"] == 20 and r["elo_defender_after"] - r["elo_defender_before"] == -12, "bob gagne +20, alice (créatrice) perd -12")

print("3) ÉVÉNEMENT « ELO PERDU ÷2 »")
ok(c.post("/admin/event", json={"kind": "elo_half", "duration_hours": 24}).status_code == 403, "sans clé admin : 403")
ev = c.post("/admin/event", json={"kind": "elo_half", "duration_hours": 24}, headers=A).json()
ok(ev["status"] == "ok" and ev["active"] and ev["kind"] == "elo_half" and ev["title"] == "Défaites moins chères : Elo perdu ÷2", "lancé depuis l'administration, titre par défaut")
ok(any(e["kind"] == "elo_half" and e["active"] for e in c.get("/events", headers=H["bob"]).json()["events"]), "le bandeau du site l'annonce")
ok(EV.elo_loss_factor(db) == 0.5, "pendant l'événement : pertes ×0,5")
r = match(); da, db_ = r["elo_defender_after"] - r["elo_defender_before"], r["elo_challenger_after"] - r["elo_challenger_before"]
normal = DE.elo_delta(r["elo_defender_before"], r["elo_challenger_before"], 0, True)
ok(db_ > 0 and da < 0 and da == DE.elo_delta(r["elo_defender_before"], r["elo_challenger_before"], 0, True, loss_factor=0.5) and abs(da) < abs(normal),
   "alice perd deux fois moins (%d au lieu de %d) ; bob gagne normalement (+%d)" % (da, normal, db_))
ok(db_ == DE.elo_delta(r["elo_challenger_before"], r["elo_defender_before"], 1), "le gain du vainqueur ne change pas")
last = db.query(Duel).order_by(Duel.created_at.desc()).first()
ok(json.loads(last.lineups_json).get("elo_loss_factor") == 0.5, "le match garde la trace de l'événement")
ok(any(x["sorte"] == "elo_half" and x["détail"] == "Elo perdu ÷2" for x in c.get("/admin/events", headers=A).json()), "liste admin : « Elo perdu ÷2 »")

print("4) FIN DE L'ÉVÉNEMENT ET ELO REJOUÉ")
c.post("/admin/event-cancel", json={"id": ev["id"]}, headers=A)
ok(EV.elo_loss_factor(db) == 1.0, "événement annulé : pertes normales")
before = {p: elo(p) for p in ("alice", "bob")}
rep = DE.reset_duels(db, "none", True, True)
ok(not [x for x in rep["elo_modifies"] if x["pseudo"] in ("alice", "bob")], "Elo rejoué depuis les matchs : identique (la moitié de perte est rejouée)")

print(); print("BILAN (événement Elo perdu ÷2) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
