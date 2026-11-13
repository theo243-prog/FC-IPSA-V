"""
Test : cartes uniques (une nouvelle personne qui n'existe que dans UNE rareté ; aucune variante créée automatiquement : ni secrète,
ni Édition Noire, ni spéciale du vendredi, ni épique d'un premier but, ni légendaire de l'homme du match). Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import game_logic as GL, club_auctions as CA, weekly as W, motm as MO
from app.models import User, Player, Card, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
H = {"ana": {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": "ana", "password": "test1234"}).json()["token"]}}
P = lambda n: (db.expire_all(), db.query(Player).filter_by(name=n).first())[1]
cards_of = lambda n: sorted(k.tier.value for k in db.query(Card).filter_by(player_id=P(n).id).all())

print("1) CRÉATION")
r = c.post("/admin/create-unique-card", json={"name": "Zinédine", "tier": "legendaire", "poste": "mc", "grant_to_pseudo": "ana"}, headers=A)
ok(r.status_code == 200 and r.json()["note"] == 90 and r.json()["granted_to"] == "ana", "légendaire unique créée (note 90) et offerte à ana")
ok(cards_of("Zinédine") == ["legendaire"] and P("Zinédine").unique_card and P("Zinédine").poste == "MC", "une seule carte : la légendaire (poste MC)")
col = {x["player_name"]: x for x in c.get("/collection", headers=H["ana"]).json() if x.get("quantity")}
ok(col.get("Zinédine", {}).get("tier") == "legendaire", "elle est dans la collection d'ana")
ok(c.post("/admin/create-unique-card", json={"name": "Fan Unique", "tier": "rare", "poste": "FAN"}, headers=A).status_code == 200 and cards_of("Fan Unique") == ["rare"], "un fan unique en rare")
ok(c.post("/admin/create-unique-card", json={"name": "Commun Seul", "tier": "commune", "poste": "ATT"}, headers=A).status_code == 200, "un joueur unique en commune")
bad = [({"name": "zinédine", "tier": "rare"}, "nom déjà pris (sans tenir compte des majuscules)"), ({"name": "Lucas", "tier": "rare"}, "nom d'un joueur existant"),
       ({"name": "X1", "tier": "gold"}, "rareté gold refusée"), ({"name": "X2", "tier": "secrete"}, "rareté secrète refusée"),
       ({"name": "X3", "tier": "rare", "poste": "STADE"}, "poste réservé refusé"), ({"name": "X4", "tier": "rare", "grant_to_pseudo": "fantome"}, "pseudo inconnu refusé")]
ok(all(c.post("/admin/create-unique-card", json=b, headers=A).status_code in (400, 404) for b, _ in bad) and not P("X1") and not P("X4"), "refusés, et rien n'est créé : " + ", ".join(m for _, m in bad))
ok(any("Carte unique Zinédine (legendaire" in x["action"] for x in c.get("/admin/log", headers=A).json()), "l'action figure dans le journal")

print("2) AUCUNE VARIANTE AUTOMATIQUE")
GL.ensure_secret_cards(db)
ok(cards_of("Zinédine") == ["legendaire"] and cards_of("Fan Unique") == ["rare"], "pas de carte secrète au démarrage (joueur et fan)")
ok(not any(p.name in ("Zinédine", "Fan Unique") for p in CA.people(db)) and CA.ensure_series(db, P("Zinédine")) is None, "pas de série Édition Noire")
lucas = P("Lucas")
plan = W.plan_awards(db, [("most_used", "legendaire", [(P("Zinédine"), 9), (lucas, 3)])])
ok(not any(a["player"] == "Zinédine" for e in plan for a in e["actions"]) and plan[0]["created"] == "Lucas", "spéciales du vendredi : la carte unique est ignorée (Lucas reçoit la spéciale)")
res = MO.apply_cards(db, [{"player": "Commun Seul"}, {"player": "Zinédine"}, {"player": "Hugo"}]); db.commit()
ok(cards_of("Commun Seul") == ["commune"] and res["boosted"] == [{"player": "Zinédine", "note": 92}] and res["created"]["player"] == "Hugo",
   "homme du match : pas de légendaire créée pour une carte unique commune ; la légendaire unique prend +2 ; Hugo reçoit la sienne")
r = c.post("/admin/record-match", json={"date": "2026-11-10", "opponent": "AS Test", "score_us": 2, "score_them": 0, "buteurs": [{"player_name": "Commun Seul", "count": 1}, {"player_name": "Nathan", "count": 1}]}, headers=A)
ok(r.status_code == 200 and cards_of("Commun Seul") == ["commune"] and "epique" in cards_of("Nathan"), "premier but : pas d'épique pour la carte unique (Nathan reçoit la sienne)")
ok(sorted(k.tier.value for k in db.query(Card).filter_by(player_id=P("Hugo").id).all()).count("secrete") <= 1 and GL.has_secret_card(P("Hugo")), "un joueur normal garde sa carte secrète")

print(); print("BILAN (cartes uniques) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
