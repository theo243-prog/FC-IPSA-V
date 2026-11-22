"""
Test : l'historique des crédits (chaque mouvement noté avec un libellé, « Autre » pour un mouvement sans libellé, rien d'oublié,
visible par le joueur seul, pages, filtres, totaux, nettoyage après 90 jours).
Lancé par tests/run_tests.py.
"""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import duel_engine as DE, credit_log as CL
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); CORE = ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"]
card = lambda n: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier.commune).first()
def mk(p, credits=1000):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]; u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits
    for n in CORE: db.add(OwnedCard(user_id=u.id, card_id=card(n).id, quantity=1))
    db.commit(); return {"Authorization": "Bearer " + t}
H = {"cla": mk("cla"), "clb": mk("clb")}
uid = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
hist = lambda p, q="": c.get("/credits/history" + q, headers=H[p]).json()
labels = lambda p: [(i["label"], i["delta"]) for i in hist(p)["items"]]
team = {"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": card(n).id, "slot_category": cat} for n, cat in zip(CORE, ["GB", "DEF", "MC", "MC", "ATT"])]}
DE.draw_goals = lambda xg: 1

print("1) MOUVEMENTS ÉTIQUETÉS")
h = hist("cla")
ok(h["items"] and h["items"][0]["label"] == CL.OTHER and h["items"][0]["delta"] == 1000, "les 1000 crédits du test (changement direct) sont notés « Autre » (%s)" % h["items"][:1])
c.post("/shop/fatigue-gel/buy", headers=H["cla"]); c.post("/shop/fatigue-gel/buy", headers=H["cla"])
ok(labels("cla")[:2] == [("Gel de fatigue", -100), ("Gel de fatigue", -50)], "deux gels : −50 puis −100, le plus récent en premier (%s)" % labels("cla")[:2])
ok(hist("cla")["items"][0]["balance"] == uid("cla").credits == 850, "le solde après le mouvement est noté (850)")
r = c.post("/shop/buy", json={"item": "pack_classique"}, headers=H["cla"])
it = hist("cla")["items"][0]
ok(r.status_code == 200 and it["label"] == "Shop" and it["delta"] == -10 and it["detail"] == "Pack classique", "achat au shop : « Shop », pack classique, −10 (%s)" % it)

print("2) MATCH 1V1 : CHAQUE MOUVEMENT SÉPARÉ")
pid = c.post("/duel/proposals", json={**team, "stake": 5}, headers=H["cla"]).json()["id"]
ok(labels("cla")[0] == ("Mise 1v1 (défi publié)", -5), "défi publié : la mise est notée (%s)" % (labels("cla")[0],))
c.post(f"/duel/proposals/{pid}/play", json=team, headers=H["clb"])          # 1-1 (draw_goals) : nul
b = hist("clb")["items"][:2]
ok([(i["label"], i["delta"]) for i in b] == [("Nul 1v1 : mise rendue", 5), ("Mise 1v1", -5)], "celui qui relève : mise puis mise rendue, deux lignes (%s)" % b)
ok(b[1]["detail"] == "défi de cla" and b[0]["detail"] == "contre cla", "avec l'adversaire en détail")
ok(labels("cla")[0] == ("Nul 1v1 : mise rendue", 5), "le créateur aussi récupère sa mise (%s)" % (labels("cla")[0],))

print("3) RIEN N'EST OUBLIÉ")
u = uid("cla"); u.credits += 7; db.commit()
ok(labels("cla")[0] == (CL.OTHER, 7), "un changement sans libellé est noté « Autre » (+7)")
u = uid("cla"); CL.add(u, 4, "Essai", "détail"); u.credits += 3; db.commit()
ok(labels("cla")[:2] == [(CL.OTHER, 3), ("Essai", 4)] or labels("cla")[:2] == [("Essai", 4), (CL.OTHER, 3)], "dans la même écriture : la part étiquetée et le reste, séparés (%s)" % labels("cla")[:2])
u = uid("cla"); CL.add(u, 10, "Annulé"); CL.add(u, -10, "Annulé aussi"); db.commit()
ok(sorted(labels("cla")[:2]) == [("Annulé", 10), ("Annulé aussi", -10)], "+10 puis −10 dans la même écriture : les deux sont notés (%s)" % labels("cla")[:2])
n0 = db.query(CL.CreditLog).count()
u = uid("cla"); CL.add(u, 99, "Fantôme"); db.rollback()
u = uid("cla"); CL.add(u, 1, "Après"); db.commit()
ok(db.query(CL.CreditLog).count() == n0 + 1 and labels("cla")[0] == ("Après", 1), "une écriture annulée ne laisse rien (pas de « Fantôme »)")
for p in ("cla", "clb"):
    rows = db.query(CL.CreditLog).filter_by(user_id=uid(p).id).all()
    ok(sum(r.delta for r in rows) == uid(p).credits, "%s : la somme de l'historique = ses crédits (%d)" % (p, uid(p).credits))

print("4) LECTURE : PAGES, FILTRES, TOTAUX, CONFIDENTIALITÉ")
u = uid("clb")
for i in range(60): CL.add(u, 1, "Page")
db.commit()
p1 = hist("clb"); p2 = hist("clb", "?before=%d" % p1["items"][-1]["id"])
ok(len(p1["items"]) == CL.PAGE and p1["more"] and p2["items"] and p2["items"][0]["id"] < p1["items"][-1]["id"], "pages de %d lignes, la suite avec « before »" % CL.PAGE)
ok(all(i["delta"] > 0 for i in hist("clb", "?kind=gains")["items"]) and all(i["delta"] < 0 for i in hist("clb", "?kind=spent")["items"]), "filtres gains / dépenses")
t = hist("cla")["totals"]
ok(t["today"]["spent"] >= 165 and t["today"]["gains"] >= 1000 and t["week"]["spent"] >= t["today"]["spent"], "totaux du jour et de la semaine (%s)" % t)
ok(c.get("/credits/history").status_code == 401, "sans compte : refusé")
ok(all(r.user_id == uid("cla").id for r in db.query(CL.CreditLog).filter(CL.CreditLog.id.in_([i["id"] for i in hist("cla")["items"]])).all()), "seulement ses propres lignes")
ok(c.get("/credits/history?kind=nimporte", headers=H["cla"]).status_code == 422, "filtre inconnu refusé")

print("5) ENTRETIEN")
old = db.query(CL.CreditLog).filter_by(user_id=uid("cla").id).first(); old.at = datetime.utcnow() - timedelta(days=CL.KEEP_DAYS + 1); db.commit(); oid = old.id
CL.tick(db)
ok(db.get(CL.CreditLog, oid) is None and hist("cla")["items"], "les lignes de plus de %d jours sont effacées, les autres restent" % CL.KEEP_DAYS)
CL.on_user_deleted(db, uid("clb").id); db.commit()
ok(db.query(CL.CreditLog).filter_by(user_id=uid("clb").id).count() == 0, "compte supprimé : son historique part avec lui")

print(); print("BILAN (historique des crédits) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
