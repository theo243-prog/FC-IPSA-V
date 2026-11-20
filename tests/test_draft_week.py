"""
Test : la semaine draft du mois (tirage, annonce 48 h avant, ouverture à tous, podium à la fermeture, administration).
Lancé par tests/run_tests.py.
"""
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import draft_week as W, draft as D, seasons, cosmetics, chat
from app.models import User, Card, Player, OwnedCard
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 20, 10, 0)]; W.now_paris = lambda: NOW[0]
def at(mo, d, h=10, mi=0): NOW[0] = datetime(2026, mo, d, h, mi)
db = SessionLocal()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; db.query(User).filter_by(pseudo=p).first().credits = 100; db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("wa", "wb", "wc", "wd", "we")}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
tick = lambda: (W.tick(db), db.expire_all())
msgs = lambda: [m.text for m in db.query(chat.ChatMessage).filter_by(kind="event").all()]

print("1) TIRAGE")
nov = W.possible_starts("2026-11"); feb = W.possible_starts("2027-02")
ok(nov == [1] + list(range(16, 25)) and feb == [1] + list(range(16, 23)), "départs possibles : le 1er, ou du 16 au dernier jour − 6 (jamais pendant les matchs du tournoi, du 8 au 15) : %s" % nov)
ok(all(not (set(range(s, s + 7)) & set(range(8, 16))) and s + 6 <= 30 for s in nov), "la semaine tient dans le mois et ne touche pas le tournoi")
starts = set()
for i in range(40):
    W.RNG.seed(i); db.query(W.AppSetting).filter_by(key="draft_week:2026-11").delete(); db.flush()
    starts.add(int(W.ensure(db, "2026-11", datetime(2026, 11, 20, 10))["start"][-2:]))
db.rollback()
ok(starts and starts <= {21, 22, 23, 24}, "tiré le 20 novembre : seulement des jours à venir (21 à 24) : %s" % sorted(starts))
ok(c.get("/me", headers=H["wa"]).json()["draft_week"]["state"] == "soon", "pas encore tiré : « bientôt »")

print("2) ANNONCE 48 H AVANT (date forcée par l'admin au 23)")
r = c.post("/admin/draft-week", json={"start": "2026-11-23"}, headers=A)
ok(r.status_code == 200 and r.json()["start"] == "2026-11-23", "l'admin force le départ au 23")
ok(c.post("/admin/draft-week", json={"start": "2026-11-26"}, headers=A).status_code == 400 and c.post("/admin/draft-week", json={"month": "2026-13"}, headers=A).status_code == 422, "refus : semaine qui déborde du mois, mois invalide")
at(11, 20, 23); tick()
st = c.get("/draft", headers=H["wa"]).json()
ok(st["access"] is False and st["week"]["state"] == "soon" and st["week"]["starts_at"] is None, "plus de 48 h avant : la date reste secrète, le draft est fermé")
ok(c.post("/draft/create", json={}, headers=H["wa"]).status_code == 403, "créer une partie : refusé")
at(11, 21, 0, 30); tick()
w = c.get("/me", headers=H["wa"]).json()["draft_week"]
ok(w["state"] == "announced" and w["starts_at"].startswith("2026-11-23") and any("La semaine draft arrive" in m for m in msgs()), "48 h avant : annoncée (date dévoilée), message dans le chat")
n = len(msgs()); tick(); ok(len(msgs()) == n, "l'annonce n'est faite qu'une fois")

print("3) OUVERTURE À TOUS")
db.add(D.DraftRating(user_id=U("wa").id, season="2026-11", elo=1300, played=9, wins=9, draws=0, losses=0)); db.commit()
at(11, 23, 0, 5); tick()
w = c.get("/draft", headers=H["we"]).json()
ok(w["access"] is True and w["week"]["state"] == "open" and any("La semaine draft est ouverte" in m for m in msgs()), "le 23 à 0 h : ouverte à tous (même sans accès d'essai), message dans le chat")
ok(db.query(D.DraftRating).filter_by(season="2026-11").count() == 0, "le classement du mois repart de zéro (les parties d'essai d'avant ne comptent pas)")
r = c.post("/draft/create", json={}, headers=H["we"]); ok(r.status_code == 200, "créer une partie pendant la semaine : OK")
ok(c.post("/admin/draft-week", json={"start": "2026-11-24"}, headers=A).status_code == 400, "la semaine a commencé : on ne change plus sa date")

print("4) FERMETURE ET PODIUM")
for p, elo, played in (("wa", 1100, 6), ("wb", 1050, 5), ("wc", 1200, 4), ("wd", 1000, 7)):
    db.add(D.DraftRating(user_id=U(p).id, season="2026-11", elo=elo, played=played, wins=played, draws=0, losses=0))
db.commit()
cr = {p: U(p).credits for p in H}
at(11, 29, 23, 59); tick(); ok(c.get("/draft", headers=H["wd"]).json()["week"]["state"] == "open", "le 29 à 23 h 59 : encore ouverte (7 jours : du 23 au 29)")
at(11, 30, 0, 1); tick()
w = c.get("/draft", headers=H["wd"]).json()
ok(w["week"]["state"] == "closed" and w["access"] is False, "le 30 à 0 h : fermée")
pod = w["week"]["podium"]
ok([p["pseudo"] for p in pod] == ["wa", "wb", "wd"], "podium : wa, wb, wd (wc a la meilleure note mais seulement 4 parties) : %s" % [p["pseudo"] for p in pod])
ok([U(p).credits - cr[p] for p in ("wa", "wb", "wd", "wc")] == [150, 100, 50, 0], "crédits : 150 / 100 / 50")
names = {p: [o.card.player.name for o in db.query(OwnedCard).filter_by(user_id=U(p).id).all() if (o.card.player.poste or "") == "TROPHEE"] for p in ("wa", "wb", "wd")}
ok(names == {"wa": ["Champion du draft (novembre 2026)"], "wb": ["Deuxième du draft (novembre 2026)"], "wd": ["Troisième du draft (novembre 2026)"]}, "cartes trophées : %s" % names)
card = db.query(Card).join(Player).filter(Player.name == "Champion du draft (novembre 2026)").first()
ok(seasons.trophy_info(card.player)["rank"] == 12 and any("Champion du draft" in name for _, name in cosmetics.trophy_titles(db, U("wa").id)),
   "le trophée est reconnu (rang 12) et donne un titre")
ok(any("Fin de la semaine draft" in m and "wa" in m for m in msgs()), "podium annoncé dans le chat")
n = sum(U(p).credits for p in H); tick(); ok(sum(U(p).credits for p in H) == n, "le podium n'est versé qu'une fois")
mine = c.get("/draft", headers=H["we"]).json()
ok(mine["my_room"] is not None or mine["access"] is False, "après la fermeture : la partie déjà créée reste visible pour son créateur (ou a expiré)")
ok(c.post("/draft/create", json={}, headers=H["wb"]).status_code == 403, "après la fermeture : plus de nouvelle partie")

print("5) MOIS SUIVANT ET PAUSE")
ok(db.query(W.AppSetting).filter_by(key="draft_week:2026-12").first() is not None, "le tirage de décembre est fait pendant les 3 derniers jours de novembre")
dec = W._get(db, "2026-12"); ok(int(dec["start"][-2:]) in W.possible_starts("2026-12"), "décembre : départ le %s" % dec["start"])
r = c.post("/admin/draft-week", json={"month": "2026-12", "paused": True}, headers=A); ok(r.status_code == 200 and r.json()["paused"] is True, "pause de décembre")
at(12, int(dec["start"][-2:]), 12); tick(); ok(c.get("/draft", headers=H["wb"]).json()["access"] is False and c.get("/me", headers=H["wb"]).json()["draft_week"]["state"] == "none", "en pause : pas de semaine draft")
ok("last_podium" in c.get("/me", headers=H["wb"]).json()["draft_week"], "le podium de novembre reste affiché en décembre")
r = c.get("/admin/draft-week", headers=A); ok(r.status_code == 200 and r.json()["current"]["month"] == "2026-12", "l'admin voit la semaine du mois")

print(); print("BILAN (semaine draft) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
