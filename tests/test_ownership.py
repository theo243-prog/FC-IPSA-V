"""
Test : part des joueurs qui possèdent chaque carte (GET /cards/ownership). Plusieurs cartes et comptes, doublons comptés une fois,
comptes sans carte ignorés, EXCLUDED_FROM_STATS, cache de 60 s, carte secrète / trophée non débloqués absents de la réponse,
réservé aux comptes connectés, jamais de pseudo. Lancé par tests/run_tests.py.
"""
import json

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import ownership as OW
from app.models import User, Card, Player, OwnedCard, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
card = lambda n, t="commune": db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    return {"Authorization": "Bearer " + t}
def give(p, cd, n):
    u = db.query(User).filter_by(pseudo=p).first(); o = db.query(OwnedCard).filter_by(user_id=u.id, card_id=cd.id).first()
    if o is None: db.add(OwnedCard(user_id=u.id, card_id=cd.id, quantity=n))
    else: o.quantity = n
    db.commit()
def get(p):
    OW.clear_cache(); return c.get("/cards/ownership", headers=H[p]).json()

H = {p: mk(p) for p in ("ana", "bob", "cyr", "dom", "eva")}
db.query(OwnedCard).delete(); db.commit()                       # point de départ connu : personne n'a de carte
M, N, NR = card("Mathis"), card("Nathan"), card("Nathan", "rare")
mathis = db.query(Player).filter_by(name="Mathis").first()
S = Card(player_id=mathis.id, tier=Tier.secrete, vitesse=0, tir=0); T = Card(player_id=mathis.id, tier=Tier.saison, vitesse=0, tir=0)
db.add_all([S, T]); db.commit()
give("ana", M, 3); give("ana", N, 1)          # ana : 3 exemplaires de Mathis (doublons), Nathan
give("bob", M, 1); give("bob", S, 1)          # bob : Mathis et la secrète
give("cyr", NR, 1)                            # cyr : Nathan rare
give("eva", M, 1)                             # eva : Mathis ; dom n'a aucune carte
give("dom", N, 0)                             # une ligne à 0 exemplaire ne compte pas

print("1) POURCENTAGES")
r = c.get("/cards/ownership"); ok(r.status_code == 401, "sans compte : 401")
j = get("ana")
ok(j["total_players"] == 4, "total : les 4 comptes qui ont au moins une carte (dom, sans carte, est ignoré)")
ok(j["cards"][M.id] == 3, "Mathis commune : 3 propriétaires (les 3 exemplaires d'ana comptent une seule fois)")
ok(j["cards"][N.id] == 1 and j["cards"][NR.id] == 1, "Nathan commune et Nathan rare : 1 propriétaire chacune (une ligne à 0 exemplaire ne compte pas)")
other = card("Hugo"); ok(j["cards"].get(other.id) == 0, "une carte que personne n'a : 0 (le site affiche « personne »)")
ok(j["cache_seconds"] == OW.CACHE_SECONDS == 60, "cache de 60 secondes")

print("2) COMPTES EXCLUS")
OW.EXCLUDED_FROM_STATS[:] = ["eva"]
j = get("ana"); ok(j["total_players"] == 3 and j["cards"][M.id] == 2, "eva exclue : 3 joueurs, Mathis à 2 propriétaires")
OW.EXCLUDED_FROM_STATS[:] = []
ok(get("ana")["total_players"] == 4, "liste vide : tout le monde compte de nouveau")

print("3) CONFIDENTIALITÉ")
j = get("ana"); raw = json.dumps(c.get("/cards/ownership", headers=H["ana"]).json())
ok(S.id not in j["cards"] and S.id not in raw, "carte secrète non débloquée : absente de la réponse (ni pourcentage, ni identifiant)")
ok(T.id not in j["cards"], "trophée de saison non possédé : absent")
jb = get("bob"); ok(jb["cards"].get(S.id) == 1, "bob, qui a la secrète, voit qu'il en est le seul propriétaire")
ok(not any(p in raw for p in ("ana", "bob", "cyr", "eva")), "aucun pseudo dans la réponse")

print("4) CACHE")
OW.clear_cache(); c.get("/cards/ownership", headers=H["ana"])
give("dom", M, 1)
ok(c.get("/cards/ownership", headers=H["ana"]).json()["cards"][M.id] == 3, "dans les 60 s : le résultat gardé en cache est renvoyé")
OW._cache["at"] -= OW.CACHE_SECONDS
j = c.get("/cards/ownership", headers=H["ana"]).json()
ok(j["cards"][M.id] == 4 and j["total_players"] == 5, "après 60 s : recalculé (dom a maintenant une carte)")

print("BILAN (possession des cartes) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
