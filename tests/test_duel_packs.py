"""
Test : au plus 10 packs gagnés par jour en 1v1 (pack match si on gagne, classique si on perd ou fait nul). Au-delà, chaque match rapporte 1 à 5 crédits
au hasard à la place, sans limite, tout en continuant à rapporter mises, Elo et missions.
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
db = SessionLocal(); CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]; real_draw, real_today = DE.draw_goals, GL.today_paris
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = 500
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {"alice": mk("alice"), "bob": mk("bob")}
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
MODE = {"v": "bob"}
SEQ = {"bob": [3, 0], "alice": [0, 3], "nul": [1, 1]}; cyc = {}
def goals(xg): return next(cyc[MODE["v"]])            # remplace draw_goals : le score exact du match est imposé (part acquise comprise)
DE.draw_goals = goals
def match(winner):
    """alice publie un défi, bob le joue. winner : « bob » (le challenger gagne), « alice » (le créateur gagne) ou « nul »."""
    MODE["v"] = winner; cyc[winner] = itertools.cycle(SEQ[winner])
    pid = c.post("/duel/proposals", json={**team, "stake": 1}, headers=H["alice"]).json()["id"]
    return c.post(f"/duel/proposals/{pid}/play", json=team, headers=H["bob"]).json()
def tokens(p): d = c.get("/me", headers=H[p]).json()["pack_tokens"]; return d["match"], d["classique"]
def credits(p): return c.get("/me", headers=H[p]).json()["credits"]
print("1) 10 PACKS PAR JOUR : UN PACK MATCH À CHAQUE VICTOIRE, UN CLASSIQUE À CHAQUE DÉFAITE")
res = [match("bob") for _ in range(10)]
ok(all(r["result"] == "victoire" and r["pack_match_won"] and r["pack_match_to"] == "bob" and r["pack_classique_to"] == ["alice"] and r["pack_none_to"] == [] for r in res), "bob gagne 10 matchs : un pack match à chaque victoire (plus de limite à 5)")
ok(tokens("bob") == (10, 0) and tokens("alice") == (0, 10), "bob a 10 packs match ; alice (qui perd) a 10 packs classiques")
print("2) AU-DELÀ DE 10 PACKS : 1 À 5 CRÉDITS À LA PLACE, SANS LIMITE")
cb, ca = credits("bob"), credits("alice"); r11 = match("bob")
bb, ba = r11["credits_instead"].get("bob"), r11["credits_instead"].get("alice")
ok(set(r11["pack_none_to"]) == {"bob", "alice"} and not r11["pack_match_won"] and r11["pack_classique_to"] == [] and tokens("bob") == (10, 0) and tokens("alice") == (0, 10), "11e match : plus aucun pack, ni pour bob ni pour alice")
ok(bb in range(1, 6) and ba in range(1, 6) and credits("bob") - cb == 1 + bb and credits("alice") - ca == -1 + ba, "chacun reçoit 1 à 5 crédits (bob +%s en plus de la mise gagnée, alice +%s malgré la défaite)" % (bb, ba))
ok(r11["elo_challenger_after"] > r11["elo_challenger_before"] and r11["duel_pack_cap"] == 10, "le match compte quand même : Elo en hausse")
got = [match("bob")["credits_instead"] for _ in range(20)]; vals = [g[k] for g in got for k in g]
ok(len(vals) == 40 and all(1 <= v <= 5 for v in vals) and len(set(vals)) >= 3, "20 matchs de plus : des crédits à chaque fois, toujours entre 1 et 5 (%s)" % sorted(set(vals)))
rn = match("nul"); ok(rn["result"] == "nul" and set(rn["credits_instead"]) == {"bob", "alice"} and rn["pack_classique_to"] == [], "un nul après la limite : des crédits aussi, pas de pack")
print("3) LE CRÉATEUR DU DÉFI A LA MÊME RÈGLE")
GL.today_paris = lambda: real_today() + timedelta(days=1)
a0 = tokens("alice"); rs = [match("alice") for _ in range(11)]
ok(all(r["result"] == "défaite" and r["pack_match_to"] == "alice" for r in rs[:10]) and tokens("alice")[0] - a0[0] == 10, "le lendemain, alice (créatrice) gagne 10 matchs : 10 packs match")
ok(rs[10]["pack_match_to"] is None and set(rs[10]["credits_instead"]) == {"alice", "bob"}, "11e victoire d'alice : des crédits à la place, pour elle et pour bob (qui a aussi reçu 10 packs classiques)")
print("4) LE LENDEMAIN, TOUT REPART DE ZÉRO")
GL.today_paris = lambda: real_today() + timedelta(days=2)
rn = match("nul"); ok(set(rn["pack_classique_to"]) == {"alice", "bob"} and rn["credits_instead"] == {}, "un nul : un pack classique chacun, pas de crédits")
print("5) FACE-À-FACE (depuis toujours)")
from app.models import Duel
vs = c.get("/users/alice/versus", headers=H["bob"]).json(); rows = db.query(Duel).count()
ok(vs["pseudo"] == "alice" and vs["played"] == rows and vs["wins"] + vs["draws"] + vs["losses"] == rows, f"bob contre alice : {vs['played']} matchs ({vs['wins']} victoires, {vs['draws']} nul, {vs['losses']} défaites)")
ok(vs["wins"] == 31 and vs["losses"] == 11 and vs["draws"] == 2 and vs["goals_for"] == 31 * 3 + 2 and vs["goals_against"] == 11 * 3 + 2, "le détail : 31 victoires de bob, 11 défaites, 2 nuls ; buts %d pour, %d contre" % (vs["goals_for"], vs["goals_against"]))
ok(vs["last"]["result"] == "nul" and vs["best_win"]["mine"] - vs["best_win"]["theirs"] == 3 and len(vs["recent"]) == 5, "dernier match (nul), plus large victoire (3-0), 5 derniers matchs")
va = c.get("/users/bob/versus", headers=H["alice"]).json(); ok(va["wins"] == 11 and va["losses"] == 31 and va["goals_for"] == 35, "vu d'alice, c'est l'inverse (11 victoires, 31 défaites)")
ok(c.get("/users/alice/versus", headers=H["alice"]).status_code == 400 and c.get("/users/inconnu/versus", headers=H["bob"]).status_code == 404 and c.get("/users/alice/versus").status_code == 401, "contre soi-même : 400 ; inconnu : 404 ; sans compte : 401")
DE.draw_goals = real_draw; GL.today_paris = real_today
print(); print("BILAN (10 packs 1v1 par jour, puis des crédits) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
