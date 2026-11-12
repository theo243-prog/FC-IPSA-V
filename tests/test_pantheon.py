"""
Test : fonctions en essai (interrupteur commun : fermé par défaut, comptes choisis, ouvert à tous) et Panthéon (palmarès des saisons et
des tournois, légendes du club, records du jeu, jamais un compte de test ni la lanterne rouge). Lancé par tests/run_tests.py.
"""
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import seasons as S, features as F
from app.models import User, Duel, Match, Player, Card
from app.profiles import UserCounter
from app.offers import Trade
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
H = {p: {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]} for p in ("ana", "bob", "tst")}
t = U("tst"); t.is_test = True; db.commit()

print("1) FONCTIONS EN ESSAI")
ok(c.get("/pantheon", headers=H["ana"]).status_code == 403 and c.get("/me", headers=H["ana"]).json()["features"] == {"draft": False, "pantheon": False}, "fermé par défaut : 403, /me renvoie features à faux")
ok(c.post("/admin/feature-settings", json={"feature": "inconnue", "public": False}, headers=A).status_code == 400, "fonction inconnue : refusée")
ok(c.post("/admin/feature-settings", json={"feature": "pantheon", "allowed": ["ana", "fantome"]}, headers=A).status_code == 400, "pseudo inconnu : refusé")
ok(c.post("/admin/feature-settings", json={"feature": "pantheon", "allowed": ["ana"]}, headers=A).status_code == 200, "Panthéon réservé à ana")
ok(c.get("/pantheon", headers=H["ana"]).status_code == 200 and c.get("/pantheon", headers=H["bob"]).status_code == 403 and c.get("/me", headers=H["ana"]).json()["features"]["pantheon"], "ana y a accès, bob non (le serveur refuse)")
c.post("/admin/feature-settings", json={"feature": "draft", "allowed": ["bob"]}, headers=A)
ok(c.get("/draft", headers=H["bob"]).status_code == 200 and c.get("/me", headers=H["bob"]).json()["draft_access"], "le mode draft passe par le même interrupteur (même réglage qu'avant)")
ok(any(f["fonction"] == "pantheon" and f["allowed"] == ["ana"] for f in c.get("/admin/features", headers=A).json()["fonctions"]), "l'administration liste les fonctions en essai et leur accès")
c.post("/admin/feature-settings", json={"feature": "pantheon", "public": True}, headers=A)
ok(c.get("/pantheon", headers=H["bob"]).status_code == 200 and F.get(db, "pantheon")["allowed"] == ["ana"], "« ouvert à tous » : tout le monde y a accès (la liste reste en place)")
c.post("/admin/feature-settings", json={"feature": "pantheon", "public": False}, headers=A)

print("2) LE PANTHÉON")
for season, rows in (("2026-09", [(1, "ana", 1300), (2, "bob", 1200)]), ("2026-10", [(1, "bob", 1450), (2, "ana", 1100)])):
    for rank, p, elo in rows:
        db.add(S.SeasonResult(season=season, rank=rank, user_id=U(p).id, pseudo=p, elo=elo, matches=10, wins=6, credits=0))
T = [datetime(2026, 11, 1, 12)]
def duel(a, b, sa, sb):
    T[0] += timedelta(minutes=5)
    db.add(Duel(challenger_id=U(a).id, defender_id=U(b).id, stake=1, formation_challenger="1-2-1", formation_defender="1-2-1", score_challenger=sa, score_defender=sb,
                elo_challenger_before=1000, elo_defender_before=1000, elo_challenger_after=1000, elo_defender_after=1000, created_at=T[0]))
for sa, sb in ((2, 0), (3, 1), (1, 0), (0, 2)): duel("ana", "bob", sa, sb)
duel("bob", "ana", 6, 1)                                     # la plus large victoire : bob 6-1
duel("tst", "ana", 9, 0)                                     # un compte de test ne détient jamais un record
p1, p2 = db.query(Player).filter_by(name="Lucas").first(), db.query(Player).filter_by(name="Hugo").first()
p1.buts, p1.passes_decisives, p1.homme_du_match_count, p1.matches_joues = 12, 3, 4, 10
p2.buts, p2.passes_decisives, p2.matches_joues = 5, 9, 11
db.commit()                                                  # (avant tout U(), qui oublie les changements pas encore enregistrés)
db.add(Match(date=datetime(2026, 10, 3), opponent="AS Test", score_us=7, score_them=1)); db.add(Match(date=datetime(2026, 10, 10), opponent="FC Autre", score_us=2, score_them=1))
db.add(UserCounter(user_id=U("ana").id, key="open_packs", value=120)); db.add(UserCounter(user_id=U("tst").id, key="open_packs", value=999))
card = db.query(Card).filter_by(player_id=p1.id).first()
db.add(Trade(kind="annonce", seller_id=U("bob").id, buyer_id=U("ana").id, seller_pseudo="bob", buyer_pseudo="ana", card_id=card.id, card_tier=card.tier.value, price=250, created_at=datetime(2026, 11, 2)))
db.commit()
c.post("/admin/feature-settings", json={"feature": "pantheon", "allowed": ["ana"]}, headers=A)
r = c.get("/pantheon", headers=H["ana"]).json()
ok([s["season"] for s in r["seasons"]] == ["2026-10", "2026-09"] and r["seasons"][0]["podium"][0]["pseudo"] == "bob" and r["seasons"][0]["label"] == "octobre 2026", "palmarès des saisons : la plus récente d'abord (octobre : bob 1er)")
cl = r["club"]
ok(cl["scorers"][0] == {"player": "Lucas", "count": 12} and cl["assists"][0]["player"] == "Hugo" and cl["motm"][0]["player"] == "Lucas" and cl["matches"][0]["player"] == "Hugo", "légendes du club : meilleur buteur, passeur, homme du match, le plus de matchs")
ok(cl["biggest_win"] == {"opponent": "AS Test", "score_us": 7, "score_them": 1, "date": "2026-10-03"}, "plus large victoire du club : 7-1 contre AS Test")
rec = {x["id"]: x for x in r["records"]}
ok(rec["biggest_1v1"]["holder"] == "bob" and rec["biggest_1v1"]["value"] == "6-1", "plus large victoire 1v1 : bob 6-1 (pas le 9-0 du compte de test)")
ok(rec["streak_1v1"]["holder"] == "ana" and rec["streak_1v1"]["value"] == "3 victoires", "plus longue série : ana, 3 victoires")
ok(rec["season_elo"]["holder"] == "bob" and rec["season_elo"]["value"] == "1450", "meilleur Elo de fin de saison : bob 1450")
ok(rec["packs"]["holder"] == "ana" and rec["packs"]["value"] == "120 packs", "le plus de packs ouverts : ana (le compte de test est ignoré)")
ok(rec["top_sale"]["holder"] == "ana" and rec["top_sale"]["value"] == "250 crédits" and "Lucas" in rec["top_sale"]["detail"], "vente la plus chère : 250 crédits")
ok("top_club_auction" not in rec and "club_hard" not in rec, "un record sans donnée n'est pas montré")
ok("tst" not in json.dumps(r) and "Lanterne" not in json.dumps(r, ensure_ascii=False), "jamais un compte de test, jamais la lanterne rouge")
ok(c.get("/pantheon").status_code == 401, "sans compte : 401")

print(); print("BILAN (fonctions en essai, Panthéon) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
