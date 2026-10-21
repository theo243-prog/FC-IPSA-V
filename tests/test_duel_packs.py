"""
Test : limite de 5 packs MATCH gagnés par jour en 1v1. Au-delà, un match gagné rapporte un pack classique (comme un perdant), tout en continuant à rapporter mises, Elo et missions.
Lancer comme test_tournament.py (voir tests/LISEZMOI.md).
"""
import itertools
from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import duel_engine as DE, game_logic as GL
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]; real_poisson, real_today = DE.poisson_random, GL.today_paris
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 500
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {"alice": mk("alice"), "bob": mk("bob")}
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
MODE = {"v": "bob"}
SEQ = {"bob": [3, 0], "alice": [0, 3], "nul": [1, 1]}; cyc = {}
def poisson(lam): return next(cyc[MODE["v"]])
DE.poisson_random = poisson
def match(winner):
    """alice publie un défi, bob le joue. winner : « bob » (le challenger gagne), « alice » (le créateur gagne) ou « nul »."""
    MODE["v"] = winner; cyc[winner] = itertools.cycle(SEQ[winner])
    pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["alice"]).json()["id"]
    return c.post(f"/duel/proposals/{pid}/play", json=team, headers=H["bob"]).json()
def tokens(p): d = c.get("/me", headers=H[p]).json()["pack_tokens"]; return d["match"], d["classique"]
print("1) LES 5 PREMIERS PACKS MATCH DU JOUR")
res = [match("bob") for _ in range(5)]
ok(all(r["result"] == "victoire" and r["pack_match_won"] and r["pack_match_capped_to"] is None and r["pack_match_to"] == "bob" for r in res), "bob gagne 5 matchs : un pack match à chaque victoire")
ok(tokens("bob") == (5, 0) and tokens("alice") == (0, 5), "bob a 5 packs match ; alice (qui perd) a 5 packs classiques")
print("2) AU-DELÀ : UN PACK CLASSIQUE, QU'ON GAGNE OU QU'ON PERDE")
r6 = match("bob")
ok(r6["result"] == "victoire" and not r6["pack_match_won"] and r6["pack_classique_won"] and r6["pack_match_to"] is None and r6["pack_match_capped_to"] == "bob" and "bob" in r6["pack_classique_to"], "6e victoire de bob : plus de pack match, un pack classique à la place (« pack_match_capped_to : bob »)")
ok(tokens("bob") == (5, 1) and tokens("alice") == (0, 6), "bob : 5 packs match et 1 classique ; alice : 6 classiques")
ok(r6["credits_delta"] == 1 and r6["elo_challenger_after"] > r6["elo_challenger_before"], "le match compte quand même : mise gagnée (+1) et Elo en hausse")
match("bob"); ok(tokens("bob") == (5, 2), "7e victoire : toujours un classique (bob : 5 match, 2 classiques)")
print("3) LE CRÉATEUR DU DÉFI GAGNANT A LA MÊME LIMITE")
rs = [match("alice") for _ in range(6)]
ok(all(r["result"] == "défaite" and r["pack_match_to"] == "alice" and r["pack_match_capped_to"] is None for r in rs[:5]) and tokens("alice")[0] == 5, "alice (créatrice) gagne 5 matchs : 5 packs match")
r = rs[5]; ok(r["pack_match_to"] is None and r["pack_match_capped_to"] == "alice" and tokens("alice")[0] == 5, "6e victoire d'alice : plus de pack match (limite atteinte aussi pour elle) : « " + str(r["pack_match_capped_to"]) + " »")
print("4) LE NUL NE COMPTE PAS DANS LA LIMITE")
rn = match("nul"); ok(rn["result"] == "nul" and rn["pack_match_to"] is None and rn["pack_match_capped_to"] is None and set(rn["pack_classique_to"]) == {"alice", "bob"}, "un match nul : un pack classique chacun, pas de pack match")
print("5) LE LENDEMAIN, LA LIMITE REPART DE ZÉRO")
GL.today_paris = lambda: real_today() + timedelta(days=1)
b0 = tokens("bob"); r = match("bob"); ok(r["pack_match_won"] and tokens("bob")[0] == b0[0] + 1, "le lendemain (minuit à Paris) : bob regagne un pack match")
for _ in range(4): match("bob")
r = match("bob"); ok(not r["pack_match_won"] and r["pack_match_capped_to"] == "bob", "…et la limite de 5 par jour s'applique de nouveau")
print("6) FACE-À-FACE (depuis toujours)")
from app.models import Duel
vs = c.get("/users/alice/versus", headers=H["bob"]).json(); rows = db.query(Duel).count()
ok(vs["pseudo"] == "alice" and vs["played"] == rows and vs["wins"] + vs["draws"] + vs["losses"] == rows, f"bob contre alice : {vs['played']} matchs ({vs['wins']} victoires, {vs['draws']} nul, {vs['losses']} défaites)")
ok(vs["wins"] == 13 and vs["losses"] == 6 and vs["draws"] == 1 and vs["goals_for"] == 13 * 3 + 1 and vs["goals_against"] == 6 * 3 + 1, "le détail : 13 victoires de bob, 6 défaites, 1 nul ; buts 40 pour, 19 contre")
ok(vs["last"]["result"] == "victoire" and vs["streak"] == {"type": "victoire", "count": 6} and vs["best_win"]["mine"] - vs["best_win"]["theirs"] == 3 and len(vs["recent"]) == 5, "dernier match, série en cours (6 victoires de suite), plus large victoire (3-0), 5 derniers matchs")
va = c.get("/users/bob/versus", headers=H["alice"]).json(); ok(va["wins"] == 6 and va["losses"] == 13 and va["goals_for"] == 19 and va["streak"]["type"] == "défaite", "vu d'alice, c'est l'inverse (6 victoires, 13 défaites, série de défaites)")
ok(c.get("/users/alice/versus", headers=H["alice"]).status_code == 400 and c.get("/users/inconnu/versus", headers=H["bob"]).status_code == 404 and c.get("/users/alice/versus").status_code == 401, "contre soi-même : 400 ; inconnu : 404 ; sans compte : 401")
DE.poisson_random = real_poisson; GL.today_paris = real_today
print(); print("BILAN (limite des packs match par jour) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
