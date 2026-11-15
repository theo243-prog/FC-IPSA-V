"""
Test : succès secrets (fonction en essai « succes_secrets ») : 21 succès cachés, 20 crédits et un titre chacun, seulement le nombre trouvé
pour les autres, la liste des trouvés sur son propre profil, rien pour un compte sans accès. Lancé par tests/run_tests.py.
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import secret_achievements as SA, club, prono, motm, offers, communaute, auctions, chat
from app.models import User, Card, Tier, OwnedCard, Duel
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
H = {p: {"Authorization": "Bearer " + c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]} for p in ("ana", "bob", "dan")}
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
mine = lambda p: c.get("/secret-achievements", headers=H[p])
found = lambda p: {s["id"] for s in mine(p).json()["list"]}

print("1) ACCÈS (FONCTION EN ESSAI)")
ok(mine("ana").status_code == 403, "fermé par défaut : 403")
ok(c.get("/me", headers=H["ana"]).json()["features"].get("succes_secrets") is False, "/me renvoie features.succes_secrets à faux")
ok(c.get("/users/ana/profile").json()["secrets"] is None, "profil : rien sur les succès secrets sans accès")
ok(c.post("/admin/feature-settings", json={"feature": "succes_secrets", "allowed": ["ana", "bob"]}, headers=A).status_code == 200, "réservée à ana et bob")
r = mine("ana").json()
ok(r == {"found": 0, "total": 21, "list": []}, "au départ : 0 / 21, aucune liste de ce qui reste à trouver")
ok(SA.TOTAL == 21 and len(SA.BY_ID) == 21, "21 succès secrets")

print("2) MATCHS 1v1 (HISTORIQUE)")
ana, bob = U("ana"), U("bob")
credits0 = ana.credits
TEAM = lambda note, form=100: {"players": [{"player": "J%d" % i, "tier": "commune", "base_note": note, "form": form} for i in range(5)]}
t0 = datetime(2026, 11, 2, 12, 0)
def duel(sa, sb, when, la=None, lb=None, events=None):
    db.add(Duel(challenger_id=ana.id, defender_id=bob.id, stake=0, formation_challenger="1-2-1", formation_defender="1-2-1",
                score_challenger=sa, score_defender=sb, elo_challenger_before=1000, elo_defender_before=1000, elo_challenger_after=1000,
                elo_defender_after=1000, created_at=when, events_json=json.dumps(events) if events else None,
                lineups_json=json.dumps({"challenger": la or TEAM(80), "defender": lb or TEAM(80)})))
for i in range(5):                                            # 5 victoires 1-0 : le mur
    duel(1, 0, t0 + timedelta(hours=i))
for i in range(4):                                            # 4 nuls le même jour : pas encore « le roi du nul »
    duel(2, 2, t0 + timedelta(days=1, hours=i))
db.commit()
ok(found("ana") == {"le_mur"}, "5 victoires sans encaisser : « Le mur » (et rien d'autre)")
duel(1, 1, t0 + timedelta(days=1, hours=6))                   # 5e nul du jour
duel(4, 3, t0 + timedelta(days=2), events=[{"kind": "goal", "score": [0, 1]}, {"kind": "goal", "score": [0, 2]}, {"kind": "goal", "score": [0, 3]},
                                           {"kind": "goal", "score": [4, 3]}])                  # mené 0-3, gagne 4-3
duel(2, 1, t0 + timedelta(days=3), la=TEAM(78, form=88), lb=TEAM(90))                            # David contre Goliath, une carte à 88 %
duel(1, 0, datetime(2026, 11, 6, 2, 30))                      # 3 h 30 à Paris (UTC+1)
for i in range(10):
    duel(0, 1, t0 + timedelta(days=4, hours=i))               # 20 matchs avec la même équipe en tout
db.commit()
got = found("ana")
ok({"le_mur", "roi_du_nul", "remontada", "david_goliath", "increvable", "oiseau_nuit", "fidele"} <= got, "remontada, roi du nul, David, increvable, oiseau de nuit, fidèle")
ok("roi_du_nul" in found("bob") and "oiseau_nuit" not in found("bob") and "remontada" not in found("bob"), "bob : roi du nul aussi ; l'oiseau de nuit est celui qui joue le défi")
ok(U("ana").credits == credits0 + 20 * 7, "20 crédits par succès secret")
ok(any("succès secret" in m.get("text", "") and "ana" in m.get("text", "") for m in c.get("/chat", headers=H["ana"]).json().get("messages", [])), "annonce dans le chat")

print("3) ÉVÉNEMENTS DU MOMENT (PACKS, CRÉDITS, ENCHÈRE, DOUBLONS)")
leg, com, epi = (SimpleNamespace(tier=t) for t in (Tier.legendaire, Tier.commune, Tier.epique))
SA.on_pack(db, U("ana"), "match", [leg, com, com])
ok("bonne_etoile" not in found("ana"), "légendaire dans un pack match : pas « Né sous une bonne étoile »")
SA.on_pack(db, U("ana"), "free", [leg, com, com])
SA.on_pack(db, U("ana"), "classique", [leg, leg, com])
ok({"bonne_etoile", "jackpot"} <= found("ana"), "légendaire en pack classique (gratuit compris) ; 2 légendaires dans un pack")
for i in range(49):
    SA.on_pack(db, U("bob"), "classique", [com, com, com])
SA.on_pack(db, U("bob"), "classique", [epi, com, com])
for i in range(49):
    SA.on_pack(db, U("bob"), "classique", [com, com, com])
ok("maudit" not in found("bob"), "une épique remet la série à zéro (49 packs)")
SA.on_pack(db, U("bob"), "classique", [com, com, com])
ok("maudit" in found("bob"), "50 packs d'affilée sans épique ni légendaire : « Maudit »")
b = U("bob"); b.credits = 2000; db.commit()
b = U("bob"); b.credits = 1500; db.commit()
b = U("bob"); b.credits = 1600; db.commit()
ok("panier_perce" not in found("bob"), "500 crédits dépensés dans la journée : pas encore")
b = U("bob"); b.credits = 950; db.commit()
ok("panier_perce" in found("bob"), "1 000 crédits dépensés dans la même journée (les gains ne se retirent pas) : « Panier percé »")
b = U("bob"); b.credits = 0; db.commit(); b = U("bob"); b.credits = 30; db.commit()
ok("a_sec" in found("bob"), "tombé à 0 crédit (puis remonté) : « À sec »")
card = db.query(Card).filter(Card.tier == Tier.commune).first()
a = auctions.Auction(seller_id=U("bob").id, card_id=card.id, start_price=10, current_bid=10, top_bidder_id=U("ana").id, bids=1, ends_at=datetime.utcnow())
db.add(a); db.commit(); auctions._settle(db, a); db.commit()
ok("radin" in found("ana"), "enchère gagnée au prix de départ, sans autre enchère : « Radin »")
o = db.query(OwnedCard).filter_by(user_id=U("ana").id, card_id=card.id).first()
if o is None:
    o = OwnedCard(user_id=U("ana").id, card_id=card.id, quantity=0); db.add(o)
o.quantity = 501; db.commit()
ok("maniaque" in found("ana"), "20 exemplaires de la même carte : « Collectionneur maniaque »")
r = c.post("/collection/sell-duplicates", json={"keep_for_secrets": False}, headers=H["ana"])
ok(r.status_code == 200 and r.json()["sold"] >= 500 and "cimetiere" in found("ana"), "500 doublons vendus d'un coup : « Le cimetière »")

print("4) CLUB, PRONOSTICS, HOMME DU MATCH, MARCHÉ, COMMUNAUTÉ")
for i in range(5):
    d = "2026-11-%02d" % (10 + i)
    db.add(club.ClubMatch(user_id=ana.id, day=d, level="difficile", result="victoire", score_user=2, score_club=1, created_at=datetime(2026, 11, 10 + i, 9)))
    db.add(club.ClubMatch(user_id=ana.id, day=d, level="difficile", result="défaite", score_user=0, score_club=1, created_at=datetime(2026, 11, 10 + i, 10)))
db.add(club.ClubMatch(user_id=bob.id, day="2026-11-10", level="facile", result="victoire", score_user=0, score_club=0, created_at=datetime(2026, 11, 10, 9)))
for i in range(4):
    db.add(club.ClubMatch(user_id=bob.id, day="2026-11-1%d" % (i + 1), level="difficile", result="défaite", score_user=1, score_club=1, pens_user=3, pens_club=4,
                          created_at=datetime(2026, 11, 11 + i, 9)))
db.add(prono.PronoBet(upcoming_id="u1", user_id=ana.id, score_us=3, score_them=2, stake=5, status="won", exact=1, match_label="Match", match_date="2026-11-01"))
db.add(prono.PronoBet(upcoming_id="u2", user_id=ana.id, score_us=1, score_them=0, stake=5, status="won", exact=1, match_label="Match", match_date="2026-11-08"))
db.add(prono.PronoBet(upcoming_id="u2", user_id=bob.id, score_us=1, score_them=0, stake=5, status="won", exact=1, match_label="Match", match_date="2026-11-08"))
v = motm.MotmVote(match_label="Match", match_date="2026-11-01", players_json="[]", opens_at=datetime(2026, 11, 1), closes_at=datetime(2026, 11, 2), status="closed")
db.add(v); db.flush()
db.add(motm.MotmPoint(vote_id=v.id, player_name="Lucas", points=9, rank=1))
db.add(motm.MotmBallot(vote_id=v.id, user_id=bob.id, first="Hugo", second="Max", third="Lucas"))
db.add(motm.MotmBallot(vote_id=v.id, user_id=ana.id, first="Hugo", second="Max", third="Léo"))
T = lambda s, bu, p, when: offers.Trade(kind="annonce", seller_id=s.id, buyer_id=bu.id, seller_pseudo=s.pseudo, buyer_pseudo=bu.pseudo, card_id=card.id, card_tier="commune", price=p, created_at=when)
db.add(T(bob, ana, 30, datetime(2026, 11, 3))); db.add(T(ana, bob, 59, datetime(2026, 11, 4)))
db.commit()
g = found("ana")
ok("premier_essai" in g and "pas_de_chance" not in g, "5 victoires au premier essai du jour en Difficile : « Du premier coup »")
ok("pas_de_chance" in found("bob"), "3 séances de tirs au but perdues d'affilée : « Pas de chance »")
ok("prophete" in g and "prophete" not in found("bob"), "seul à trouver un score exact : « Prophète » (un score trouvé à deux ne compte pas)")
ok("supporter" in found("bob") and "supporter" not in g, "a voté (dans son top 3) pour l'élu : « Supporter numéro 1 »")
ok("coup_de_poker" not in g, "revendue 59 après l'avoir payée 30 : pas le double")
db.add(T(bob, ana, 30, datetime(2026, 11, 5))); db.add(T(ana, bob, 60, datetime(2026, 11, 6))); db.commit()
ok("coup_de_poker" in found("ana"), "revendue le double du prix payé : « Coup de poker »")
for i in range(3):
    db.add(communaute.CommunityProposal(user_id=bob.id, author="bob", name="Idée %d" % i, image_desc="abc", status="released"))
db.commit()
ok("muse" in found("bob"), "3 propositions sorties en cartes de la communauté : « Muse »")

print("5) AFFICHAGE, TITRES, ANNONCES")
r = mine("ana").json()
ok(r["found"] == len(r["list"]) and r["total"] == 21 and all(set(x) >= {"id", "name", "icon", "desc"} for x in r["list"]), "ma liste : seulement les trouvés, avec nom et explication")
ok(c.get("/users/ana/profile").json()["secrets"] == {"found": r["found"], "total": 21}, "profil vu par les autres : seulement le nombre")
me = c.get("/me", headers=H["ana"]).json()
sec = [b for b in me["unseen_badges"] if b.get("secret")]
ok(len(sec) == r["found"] and all(b["reward"] == 20 for b in sec), "les nouveaux succès secrets sont annoncés par /me")
c.post("/badges/seen", headers=H["ana"])
ok(not [b for b in c.get("/me", headers=H["ana"]).json()["unseen_badges"] if b.get("secret")], "annonces vues : plus répétées")
cos = c.get("/cosmetics", headers=H["ana"]).json()
st = [t for t in cos["titles"] if t.get("secret")]
ok(len(st) == r["found"] and any(t["label"] == "Remontada" for t in st), "un titre par succès secret trouvé")
ok(not any(t["id"] == "secret-muse" for t in cos["titles"]), "jamais le titre d'un succès pas trouvé")
ok(c.post("/cosmetics", json={"title": "secret-remontada", "frame": None}, headers=H["ana"]).status_code == 200
   and c.get("/users/ana/profile").json()["title"] == "Remontada", "le titre s'équipe et s'affiche sur le profil")
ok(c.post("/cosmetics", json={"title": "secret-muse", "frame": None}, headers=H["ana"]).status_code == 400, "titre d'un succès pas trouvé : refusé")
before = U("ana").credits
mine("ana")
ok(U("ana").credits == before, "rien n'est donné deux fois")

print("6) SANS ACCÈS, ADMINISTRATION, SUPPRESSION D'UN COMPTE")
dan = U("dan")
SA.on_pack(db, dan, "classique", [leg, com, com])
c.get("/me", headers=H["dan"])
ok(db.query(SA.SecretAchievement).filter_by(user_id=dan.id).count() == 0 and mine("dan").status_code == 403, "dan (sans accès) ne reçoit rien")
ok(db.query(SA.SecretProgress).filter_by(user_id=dan.id, key="flag:bonne_etoile").count() == 1, "… mais l'événement est noté pour la sortie")
adm = c.get("/admin/succes-secrets", headers=A).json()
ok(len(adm["secrets"]) == 21 and any(x["pseudo"] == "ana" for s in adm["secrets"] if s["id"] == "remontada" for x in s["found_by"]), "l'admin voit qui a trouvé quoi")
bob_id = bob.id
ok(c.post("/admin/delete-user", json={"pseudo": "bob"}, headers=A).status_code == 200, "compte de bob supprimé")
db.expire_all()
ok(db.query(SA.SecretAchievement).filter_by(user_id=bob_id).count() == 0 and db.query(SA.SecretProgress).filter_by(user_id=bob_id).count() == 0, "ses succès secrets et ses repères partent avec lui")

print(); print("BILAN (succès secrets) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
