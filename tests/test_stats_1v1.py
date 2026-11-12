"""
Test : « Mes stats 1v1 » (bilan, séries, plus grosse victoire, face à face, cartes, buteurs, passeurs, formations, tactiques ; depuis le
début ou la saison en cours ; visible seulement par le joueur lui-même). Lancé par tests/run_tests.py.
"""
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import game_logic as GL
from app.models import User, Duel
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
H = {p: {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]} for p in ("ana", "bob", "cleo")}
real_today = GL.today_paris
GL.today_paris = lambda: datetime(2026, 11, 20).date()
T = [datetime(2026, 10, 20, 12)]
def duel(a, b, sa, sb, scorers_a=(), when=None, fa="1-2-1", ta="pressing", cards_a=("Lucas", "Hugo")):
    T[0] += timedelta(minutes=5)
    ev = [{"kind": "goal", "side": "challenger", "scorer": s, "assist": "Hugo" if s != "Hugo" else None} for s in scorers_a]
    lu = {"challenger": {"players": [{"player": p, "tier": "rare"} for p in cards_a]}, "defender": {"players": [{"player": "Tom", "tier": "commune"}]}}
    db.add(Duel(challenger_id=U(a).id, defender_id=U(b).id, stake=1, formation_challenger=fa, formation_defender="2-1-1", score_challenger=sa, score_defender=sb,
                elo_challenger_before=1000, elo_defender_before=1000, elo_challenger_after=1000, elo_defender_after=1000, tactic_challenger=ta, tactic_defender="contre",
                events_json=json.dumps(ev), lineups_json=json.dumps(lu), created_at=when or T[0]))
    db.commit()
# octobre : ana bat bob 2-0, perd contre bob 0-1 ; novembre : bat bob 4-1, bat cléo 1-0, bat cléo 2-1, nul contre bob 1-1 (côté créateur)
duel("ana", "bob", 2, 0, ["Lucas", "Lucas"])
duel("ana", "bob", 0, 1)
T[0] = datetime(2026, 11, 10, 12)
duel("ana", "bob", 4, 1, ["Lucas", "Hugo", "Lucas", "Lucas"], fa="1-1-2", ta="possession")
duel("ana", "cleo", 1, 0, ["Hugo"])
duel("ana", "cleo", 2, 1, ["Lucas", "Lucas"])
duel("bob", "ana", 1, 1)                                   # ana est l'adversaire (côté défenseur)

print("1) DEPUIS LE DÉBUT")
r = c.get("/duel/my-stats", headers=H["ana"]); s = r.json()
ok(r.status_code == 200 and (s["played"], s["wins"], s["draws"], s["losses"]) == (6, 4, 1, 1) and (s["goals_for"], s["goals_against"]) == (10, 4) and s["win_pct"] == 67,
   "bilan : 6 matchs, 4 V, 1 N, 1 D, 10 buts pour, 4 contre, 67 %")
ok(s["best_streak"] == 3 and s["current_streak"] == {"result": "N", "count": 1}, "meilleure série : 3 victoires ; série en cours : 1 nul")
ok(s["biggest_win"]["for"] == 4 and s["biggest_win"]["against"] == 1 and s["biggest_win"]["opponent"] == "bob", "plus grosse victoire : 4-1 contre bob")
op = {o["pseudo"]: o for o in s["opponents"]}
ok(s["opponents"][0]["pseudo"] == "bob" and (op["bob"]["played"], op["bob"]["wins"], op["bob"]["draws"], op["bob"]["losses"]) == (4, 2, 1, 1) and (op["cleo"]["played"], op["cleo"]["wins"]) == (2, 2),
   "face à face : bob 4 matchs (2 V, 1 N, 1 D), cléo 2 victoires ; le plus affronté d'abord")
ok(s["scorers"][0] == {"player": "Lucas", "count": 7} and {"player": "Hugo", "count": 2} in s["scorers"], "mes buteurs : Lucas 7, Hugo 2 (seulement les buts de MON équipe)")
ok(s["assists"][0]["player"] == "Hugo" and s["assists"][0]["count"] == 7, "mes passeurs : Hugo 7 (passe sur chaque but de Lucas)")
cards = {(x["player"], x["tier"]): x for x in s["top_cards"]}
ok(cards[("Lucas", "rare")]["played"] == 5 and cards[("Lucas", "rare")]["wins"] == 4 and cards[("Tom", "commune")]["played"] == 1, "mes cartes les plus jouées : Lucas 5 matchs, 4 victoires ; Tom 1 (le match où j'étais du côté du créateur adverse), jamais les cartes de l'adversaire")
fm = {f["id"]: f for f in s["formations"]}
ok(fm["1-2-1"]["played"] == 4 and fm["1-1-2"] == {"id": "1-1-2", "played": 1, "wins": 1} and fm["2-1-1"]["played"] == 1, "mes formations (côté défenseur compris : 2-1-1)")

print("2) LA SAISON EN COURS")
m = c.get("/duel/my-stats?scope=month", headers=H["ana"]).json()
ok(m["season"] == "2026-11" and m["season_label"] == "novembre 2026" and (m["played"], m["wins"], m["draws"]) == (4, 3, 1), "novembre seulement : 4 matchs, 3 V, 1 N")
ok(c.get("/duel/my-stats?scope=annee", headers=H["ana"]).status_code == 400, "période inconnue : refusée")

print("3) CONFIDENTIALITÉ ET CAS VIDES")
ok(c.get("/duel/my-stats").status_code == 401, "sans compte : 401")
b = c.get("/duel/my-stats", headers=H["bob"]).json()
ok((b["played"], b["wins"], b["losses"], b["draws"]) == (4, 1, 2, 1) and b["scorers"] == [] and b["top_cards"][0]["player"] == "Tom", "bob voit SES stats (ses cartes, pas celles d'ana)")
U("cleo"); dd = c.post("/auth/register", json={"pseudo": "nouveau", "password": "test1234"}).json()["token"]
e = c.get("/duel/my-stats", headers={"Authorization": "Bearer " + dd}).json()
ok(e["played"] == 0 and e["current_streak"] is None and e["biggest_win"] is None and e["opponents"] == [], "aucun match : tout à zéro, sans erreur")
GL.today_paris = real_today

print(); print("BILAN (mes stats 1v1) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
