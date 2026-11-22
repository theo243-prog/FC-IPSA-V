"""
Test : draft en direct (regarder une partie en cours) : liste « En direct » du salon, vue spectateur sans rien de secret (ni cartes à venir,
ni compositions, ni récompenses), compteur de spectateurs vu par les joueurs, accès réservé, regarder n'est pas un signe de vie.
Lancé par tests/run_tests.py.
"""
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import draft as D
from app.models import Player, Card, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
def mk(p):
    return {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]}
H = {p: mk(p) for p in ("dda", "ddb", "ddspec", "ddnon")}
for name in ("Fan Direct Un", "Fan Direct Deux"):
    f = Player(name=name, poste="FAN"); db.add(f); db.flush(); db.add(Card(player_id=f.id, tier=Tier.commune, vitesse=0, tir=0))
db.commit()
T = [datetime(2026, 11, 20, 12, 0, 0)]
D._now = lambda: T[0]
def tick(s): T[0] += timedelta(seconds=s)
c.post("/admin/draft-settings", json={"allowed": ["dda", "ddb", "ddspec"]}, headers=A)
W = lambda p, rid: c.get("/draft/%s/watch" % rid, headers=H[p])

print("1) AVANT LE DÉBUT")
rid = c.post("/draft/create", json={}, headers=H["dda"]).json()["id"]
ok(W("ddspec", rid).status_code == 400, "une partie qui attend un adversaire ne se regarde pas encore")
ok(c.get("/draft", headers=H["ddspec"]).json()["live_rooms"] == [], "rien dans « En direct »")

print("2) PENDANT LES ENCHÈRES")
c.post("/draft/%s/join" % rid, headers=H["ddb"])
live = c.get("/draft", headers=H["ddspec"]).json()["live_rooms"]
ok(len(live) == 1 and live[0]["id"] == rid and live[0]["host"] == "dda" and live[0]["guest"] == "ddb" and live[0]["lot"] == 1 and live[0]["total_lots"] == 12, "la partie apparaît dans « En direct » (%s)" % live)
ok(c.get("/draft", headers=H["dda"]).json()["live_rooms"] == [], "un joueur ne voit pas sa propre partie dans la liste")
v = W("ddspec", rid).json()
room = db.get(D.DraftRoom, rid); db.refresh(room); st = D._st(room)
future = {l["card_id"] for l in st["lots"][1:]}
txt = str(v)
ok(v["status"] == "bidding" and v["coins"] == {"host": 200, "guest": 200} and v["lot"]["number"] == 1 and v["lot"]["card"]["id"] == st["lots"][0]["card_id"], "il voit la carte en jeu et les pièces des deux équipes")
ok(not any(cid in txt for cid in future), "jamais les cartes à venir du tirage")
ok(c.get("/draft/%s" % rid, headers=H["dda"]).json()["spectators"] == 1, "les joueurs voient « 1 spectateur »")
seen_before = room.host_seen
tick(D.AFK_SECONDS - 5); W("ddspec", rid)
db.refresh(room); ok(room.host_seen == seen_before and room.status == "bidding", "regarder ne compte pas comme un signe de vie des joueurs")
c.get("/draft/%s" % rid, headers=H["dda"]); c.get("/draft/%s" % rid, headers=H["ddb"])
tick(D.WATCH_WINDOW + 1)
ok(c.get("/draft/%s" % rid, headers=H["dda"]).json()["spectators"] == 0, "un spectateur parti n'est plus compté après %d s" % D.WATCH_WINDOW)

print("3) ACCÈS")
ok(W("ddnon", rid).status_code == 403, "sans accès au draft : refusé")
ok(c.get("/draft/inconnue/watch", headers=H["ddspec"]).status_code == 404, "partie inconnue : 404")
ok(c.get("/draft/%s/watch" % rid).status_code == 401, "sans compte : refusé")

print("4) COMPOSITION PUIS MATCH")
for _ in range(40):                                         # on laisse filer le temps : chaque carte est laissée / prise d'office
    room = db.get(D.DraftRoom, rid); db.refresh(room)
    if room.status != "bidding": break
    c.get("/draft/%s" % rid, headers=H["dda"]); c.get("/draft/%s" % rid, headers=H["ddb"])
    tick(D.BID_SECONDS + 1)
    c.get("/draft/%s" % rid, headers=H["dda"]); c.get("/draft/%s" % rid, headers=H["ddb"])
v = W("ddspec", rid).json()
ok(v["status"] == "lineup" and v["ready"] == {"host": False, "guest": False}, "composition : seulement « équipe prête ou pas » (%s)" % v.get("ready"))
room = db.get(D.DraftRoom, rid); db.refresh(room); st = D._st(room)
mine = [p for p in st["picks"]["host"] if p["kind"] == "joueur"]
lu = D.auto_lineup([db.get(Card, p["card_id"]) for p in mine])
c.post("/draft/%s/lineup" % rid, json={"formation": lu["formation"], "tactic": "pressing", "captain_card_id": lu["captain_card_id"], "slots": lu["slots"]}, headers=H["dda"])
v = W("ddspec", rid).json()
ok(v.get("ready", {}).get("host") is True and "pressing" not in str(v) and "lineup" not in v, "une équipe prête : ni sa tactique ni sa formation ne sont envoyées")
tick(D.LINEUP_SECONDS + 1); c.get("/draft/%s" % rid, headers=H["ddb"])
v = W("ddspec", rid).json()
ok(v["status"] == "done" and "events" in v["match"] and "rewards" not in v["match"] and v["match"]["starts_in"] is not None, "match : le récit et le départ commun, sans les récompenses")
ok(any(r["id"] == rid for r in c.get("/draft", headers=H["ddspec"]).json()["live_rooms"]), "la partie finie reste dans « En direct » le temps du match")
tick(D.LIVE_DONE_SECONDS + 1)
ok(not any(r["id"] == rid for r in c.get("/draft", headers=H["ddspec"]).json()["live_rooms"]), "puis elle disparaît de la liste")

print(); print("BILAN (draft en direct) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
