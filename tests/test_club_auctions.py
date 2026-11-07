"""
Test : enchères quotidiennes du club (cartes uniques Édition Noire, app/club_auctions.py), avec une horloge simulée (FC_FAKE_NOW).
Séries pour tous (22 chacune, n° 1 réservé), création automatique à l'ajout d'une personne, activation différée (rien avant la date,
section masquée sauf testadmin, teaser, lot de test avant la date), 5 enchères à 17h00 pour 5 personnes différentes, choix des moins
émises, numéros parmi les restants, fin à 16h00 le lendemain, prolongation plafonnée à +60 min, gagnant servi avec son numéro,
crédits détruits, pas de limite de gains, sans offre : retour en réserve, idempotence (deux passages, redémarrage), rattrapage
après 17h00, pause, moins de 5 personnes, séries épuisées, heure d'été et d'hiver. Lancé par tests/run_tests.py.
"""
import os
from datetime import datetime, timedelta

os.environ["FC_FAKE_NOW"] = "2026-11-08T10:00:00"

from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from app.main import app
from app.database import SessionLocal
from app import club_auctions as CA, numbered as NB, auctions as AU, chat as CH, weekly as WK
from app.admin_tools import AdminLog
from app.models import User, OwnedCard, Player

c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
def at(s):
    os.environ["FC_FAKE_NOW"] = s
def mk(p, credits=1000):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit(); return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("testadmin", "ana", "bob", "cyr", "dan")}
def tick():
    s = SessionLocal()                                     # une nouvelle session à chaque passage, comme la tâche de fond
    try:
        CA.tick(s)
    finally:
        s.close()
    db.expire_all()
def batches():
    db.expire_all(); return db.query(CA.ClubAuctionBatch).order_by(CA.ClubAuctionBatch.id).all()
def lots(b):
    return db.query(CA.ClubAuctionLot).filter_by(batch_id=b.id).all()
def state():
    db.expire_all(); return {r["subject"]: r for r in CA.series_state(db)}
def credits_total():
    db.expire_all(); return int(db.query(func.sum(User.credits)).scalar() or 0)
def club_msgs():
    db.expire_all(); return [m.text for m in db.query(CH.ChatMessage).filter(CH.ChatMessage.text.like("%enchères du club%") | CH.ChatMessage.text.like("%Enchères du club%")).all()]
def bid(p, aid, amount):
    return c.post("/auctions/%s/bid" % aid, json={"amount": amount}, headers=H[p])
copy_of = lambda lot: (db.expire_all(), db.query(NB.NumberedCopy).filter_by(card_id=lot.card_id).first())[1]
owner = lambda cid: [db.get(User, o.user_id).pseudo for o in db.query(OwnedCard).filter_by(card_id=cid).all() if o.quantity > 0]

print("1) LES SÉRIES")
r = c.post("/admin/create-player", json={"name": "Zoé", "poste": "FAN"}, headers=A).json()
ok(r.get("edition_noire") is True, "un fan créé : sa série Édition Noire est créée automatiquement")
db.add_all([Player(name="Wolfy", poste="MASCOTTE"), Player(name="Ballon", poste="EQUIPEMENT"), Player(name="But — Lucas", poste="MOMENT")]); db.commit()
ok(CA.ensure_series(db, db.query(Player).filter_by(name="Wolfy").first()) is None and CA.ensure_series(db, db.query(Player).filter_by(name="Ballon").first()) is None, "mascotte, équipement : pas de série")
ok(c.post("/admin/series-create-all", json={"dry_run": True}).status_code == 403, "sans clé admin : 403")
dry = c.post("/admin/series-create-all", json={"dry_run": True}, headers=A).json()
names = {x["name"] for x in dry["to_create"]}
ok(dry["status"] == "dry_run" and len(names) == 30 and "Lucas" in names and "Zoé" not in names and "Wolfy" not in names and "Ballon" not in names and "But — Lucas" not in names and "Zoé" in dry["already"], "aperçu : les 30 joueurs (Zoé l'a déjà ; ni mascotte, ni équipement, ni moment gold)")
ok(not CA.black_series(db) or len(CA.black_series(db)) == 1, "l'aperçu ne crée rien")
r = c.post("/admin/series-create-all", json={"dry_run": False}, headers=A).json()
ok(r["status"] == "ok" and len(r["created"]) == 30, "30 séries créées")
ok(c.post("/admin/series-create-all", json={"dry_run": False}, headers=A).json()["created"] == [], "relancer ne crée rien de plus")
st = state()
ok(len(st) == 31 and all(x["total"] == 22 and x["emitted"] == 0 and len(x["available"]) == 21 and 1 not in x["available"] and x["number_one"] == "reserve" for x in st.values()), "31 séries de 22, tout dans la réserve, 21 numéros pour les enchères (le n° 1 est réservé)")
r = c.post("/admin/create-player", json={"name": "Yasmine", "poste": "ATT"}, headers=A).json()
ok(r.get("edition_noire") is True and "Yasmine" in state(), "une joueuse créée ensuite : sa série aussi")
s_lucas = NB.find_series(db, "Édition Noire — Lucas")
ok(s_lucas.total == CA.SERIES_TOTAL == 22, "SERIES_TOTAL = 22")

print("2) AVANT LE DÉMARRAGE (lundi 9 novembre 2026, 17h00)")
cfg = c.get("/admin/club-auctions", headers=A).json()
ok(cfg["start_at"] == "2026-11-09T17:00:00" and not cfg["started"] and "lundi 9 novembre 2026 à 17h00" in cfg["start_label"], "date de démarrage par défaut : lundi 9 novembre 2026 à 17h00")
at("2026-11-08T17:30:00"); tick()
ok(batches() == [], "dimanche 17h30 : aucun lot créé avant la date")
pub = c.get("/club-auctions").json()
ok(pub["visible"] is False and pub["teaser"] == "Enchères du club : premier lot le lundi 9 novembre à 17h" and "lots" not in pub, "joueurs : section masquée, teaser « premier lot le lundi 9 novembre à 17h »")
ok(c.get("/club-auctions", headers=H["ana"]).json()["visible"] is False, "un joueur connecté ne la voit pas non plus")
c.post("/admin/club-auctions-settings", json={"teaser": False}, headers=A)
ok(c.get("/club-auctions").json()["teaser"] is None, "teaser désactivable")
c.post("/admin/club-auctions-settings", json={"teaser": True, "teaser_text": "Bientôt : les enchères du club !"}, headers=A)
ok(c.get("/club-auctions").json()["teaser"] == "Bientôt : les enchères du club !", "texte du teaser réglable")
c.post("/admin/club-auctions-settings", json={"teaser_text": ""}, headers=A)
pv = c.get("/club-auctions", headers=H["testadmin"]).json()
ok(pv["visible"] is True and pv["preview"] is True and pv["lots"] == [], "testadmin voit la section (aperçu)")
nmsg = len(club_msgs())
r = c.post("/admin/club-auctions-launch", json={"minutes": 5}, headers=A).json()
ok(r["status"] == "ok" and r["count"] == 5 and r["public"] is False and r["note"] and "Test avant le démarrage" in r["note"], "lancer un lot tout de suite AVANT la date : 5 enchères, avec une note claire")
ok(len(club_msgs()) == nmsg, "lot de test : aucune annonce dans le chat")
test_lots = lots(batches()[0])
ok(bid("ana", test_lots[0].auction_id, 20).status_code == 400, "lot de test : un joueur ne peut pas enchérir")
ok(bid("testadmin", test_lots[0].auction_id, 20).status_code == 200, "testadmin peut enchérir")
ok(len(c.get("/auctions").json()["auctions"]) == 0, "les enchères du club ne sont pas dans la liste des enchères entre joueurs")
at("2026-11-08T17:40:00"); tick()
won_test = lots(batches()[0])
ok(sum(1 for l in won_test if l.status == "won") == 1 and owner(test_lots[0].card_id) == ["testadmin"] and sum(1 for l in won_test if l.status == "unsold") == 4, "fin du lot de test : testadmin servi, les 4 autres sans preneur")
test_person = db.get(NB.NumberedSeries, test_lots[0].series_id).subject
ok(state()[test_person]["emitted"] == 1, "la personne du lot de test a 1 exemplaire émis")

print("3) PREMIER LOT : LUNDI 17h00")
at("2026-11-09T16:59:00"); tick()
ok(len(batches()) == 1, "16h59 : pas encore")
before = state(); nmsg = len(club_msgs())
at("2026-11-09T17:00:00"); tick()
bs = batches(); b1 = bs[-1]; L1 = lots(b1)
ok(len(bs) == 2 and b1.day == "2026-11-09" and b1.count == 5 and len(L1) == 5, "17h00 : un lot de 5 enchères")
subjects = [db.get(NB.NumberedSeries, l.series_id).subject for l in L1]
ok(len(set(subjects)) == 5, "5 personnes différentes")
ok(test_person not in subjects and all(before[s]["emitted"] == 0 for s in subjects), "choisies parmi celles qui ont le moins d'exemplaires émis (pas celle du test)")
ok(all(l.number != 1 and l.number in before[db.get(NB.NumberedSeries, l.series_id).subject]["available"] for l in L1), "numéros pris parmi les restants, jamais le n° 1")
ok(all(db.get(AU.Auction, l.auction_id).ends_at == datetime(2026, 11, 10, 16, 0) and l.base_end == datetime(2026, 11, 10, 16, 0) for l in L1), "fin : le lendemain (mardi) à 16h00")
ok(all(db.get(AU.Auction, l.auction_id).start_price == 20 and db.get(AU.Auction, l.auction_id).seller_id == "club" for l in L1), "prix de départ 20, vendeur « club »")
msgs = club_msgs()
ok(len(msgs) == nmsg + 1 and "jusqu'à demain 16h" in msgs[-1] and "5 nouvelles cartes uniques" in msgs[-1], "annonce dans le chat : « 5 nouvelles cartes uniques … jusqu'à demain 16h »")
at("2026-11-09T17:01:00"); tick(); tick()
ok(len(batches()) == 2, "idempotence : d'autres passages après 17h00 ne créent rien")
try:
    s2 = SessionLocal(); CA.create_batch(s2, datetime(2026, 11, 9, 18, 0)); s2.commit(); dup = False
except IntegrityError:
    s2.rollback(); dup = True
finally:
    s2.close()
ok(dup, "redémarrage / deux passages en même temps : le jour unique empêche un deuxième lot")
pub = c.get("/club-auctions").json()
ok(pub["visible"] and not pub["preview"] and len(pub["lots"]) == 5 and pub["lots"][0]["number"] >= 2, "après le démarrage : tout le monde voit les 5 enchères")
ok(c.get("/series/%d" % L1[0].series_id).json()["emitted"] == 1 and any(x["where"] == "aux enchères du club" for x in c.get("/series/%d" % L1[0].series_id).json()["copies"]), "fiche de la série : 1 émise, « aux enchères du club »")

print("4) ENCHÈRES, PROLONGATION PLAFONNÉE")
aA, aB, aC = L1[0].auction_id, L1[1].auction_id, L1[2].auction_id
T0 = credits_total()
ok(bid("ana", aA, 20).status_code == 200, "ana enchérit 20")
ok(bid("bob", aA, 20).status_code == 400 and bid("bob", aA, 21).status_code == 200, "hausse minimale de 5 % : 21")
db.expire_all(); ok(db.query(User).filter_by(pseudo="ana").first().credits == 1000, "ana dépassée : remboursée")
ok(bid("bob", aB, 30).status_code == 200 and bid("bob", aC, 25).status_code == 200, "bob enchérit aussi sur deux autres cartes (aucune limite)")
at("2026-11-10T15:59:30")
r = bid("cyr", aA, 40).json()
db.expire_all()
ok(db.get(AU.Auction, aA).ends_at == datetime(2026, 11, 10, 16, 1, 30), "enchère à 15h59:30 : prolongée de 2 minutes (16h01:30)")
t, who, fine = datetime(2026, 11, 10, 16, 1), "dan", True       # une enchère par minute jusqu'à 16h59:30 : la fin recule à chaque fois
while t <= datetime(2026, 11, 10, 16, 59, 30):
    at(t.isoformat()); db.expire_all()
    amount = AU.min_next_bid(db.get(AU.Auction, aA)); fine = fine and bid(who, aA, amount).status_code == 200
    last_who, last_amount = who, amount; who = "cyr" if who == "dan" else "dan"
    t += timedelta(minutes=1) if t.minute < 59 else timedelta(seconds=30)
db.expire_all()
ok(fine and db.get(AU.Auction, aA) is not None, "enchères chaque minute de 16h01 à 16h59:30 : l'enchère continue")
ok(db.get(AU.Auction, aA).ends_at == datetime(2026, 11, 10, 17, 0), "prolongation plafonnée : fin à 17h00 au plus tard (+60 min après 16h00), jamais au-delà")

print("5) FIN À 16h00 ET LOT SUIVANT À 17h00")
at("2026-11-10T16:00:30"); tick()
db.expire_all()
lb, lc = db.get(CA.ClubAuctionLot, aB), db.get(CA.ClubAuctionLot, aC)
ok(lb.status == lc.status == "won" and owner(lb.card_id) == ["bob"] and owner(lc.card_id) == ["bob"], "16h00 : bob remporte ses deux cartes (aucune limite de gains)")
ok(copy_of(lb).status == "attribue" and copy_of(lb).number == lb.number, "le gagnant reçoit l'exemplaire avec son numéro")
unsold = [l for l in lots(b1) if l.status == "unsold"]
ok(len(unsold) == 2 and all(copy_of(l).status == "reserve" and not owner(l.card_id) for l in unsold), "sans offre : l'exemplaire reste dans la réserve")
ok(all(l.number in state()[db.get(NB.NumberedSeries, l.series_id).subject]["available"] for l in unsold), "son numéro redevient disponible")
ok(db.get(CA.ClubAuctionLot, aA).status == "open", "l'enchère prolongée continue")
ok(len(batches()) == 2, "pas de lot avant 17h00")
nmsg = len(club_msgs())
at("2026-11-10T17:00:00"); tick()
la = db.get(CA.ClubAuctionLot, aA)
ok(la.status == "won" and la.winner_pseudo == last_who and la.price == last_amount and owner(la.card_id) == [last_who], "17h00 : l'enchère prolongée se termine d'abord (%s, %d crédits)" % (last_who, last_amount))
T1 = credits_total()
ok(T0 - T1 == last_amount + 30 + 25, "crédits détruits : le total des crédits du jeu baisse exactement des prix payés (%d)" % (last_amount + 55))
ok(not db.query(User).filter_by(pseudo="club").first() and all(u.pseudo != "club" for u in db.query(User).all()), "aucun compte « club » n'a reçu de crédits")
bs = batches()
ok(len(bs) == 3 and bs[-1].day == "2026-11-10" and bs[-1].count == 5, "puis le lot du mardi est créé")
msgs = club_msgs()
ok(any("Résultats des enchères du club" in m and last_who in m and str(last_amount) in m for m in msgs[nmsg:]), "résultat annoncé dans le chat (gagnants, prix)")
ok(c.get("/club-auctions").json()["results"], "les derniers gagnants sont dans la section")

print("6) MOINS D'ÉMIS, NUMÉROS JAMAIS REPRIS")
def check_pick(label):
    s0 = SessionLocal(); AU.settle_due(s0); s0.close()   # (les enchères de la veille se terminent d'abord, comme dans la tâche)
    before = state(); tick(); b = batches()[-1]; L = lots(b)
    chosen = {db.get(NB.NumberedSeries, l.series_id).subject for l in L}
    others = [s for s, x in before.items() if s not in chosen and x["available"]]
    ok(len(chosen) == len(L) and (not others or max(before[s]["emitted"] for s in chosen) <= min(before[s]["emitted"] for s in others)), label)
    return b
for d in range(11, 14):
    at("2026-11-%02dT17:00:00" % d); check_pick("lot du %d : les personnes choisies ont le moins d'exemplaires émis" % d)
all_lots = db.query(CA.ClubAuctionLot).all()
won = [(l.series_id, l.number) for l in all_lots if l.status == "won"]
ok(len(won) == len(set(won)) and all(l.number != 1 for l in all_lots), "jamais le n° 1, jamais deux fois le même numéro gagné")
openl = [(l.series_id, l.number) for l in all_lots if l.status == "open"]
ok(len(openl) == len(set(openl)) and not set(openl) & set(won), "aucun numéro en vente deux fois ni déjà attribué")
ok(c.post("/admin/series-mint", json={"series": str(openl[0][0]), "pseudo": "ana", "number": openl[0][1]}, headers=A).status_code == 400, "series-mint refuse un numéro aux enchères du club")

print("7) RATTRAPAGE APRÈS 17h00")
at("2026-11-14T20:15:00"); tick()
b = batches()[-1]
ok(b.day == "2026-11-14" and b.created_at == datetime(2026, 11, 14, 20, 15) and all(l.base_end == datetime(2026, 11, 15, 16, 0) for l in lots(b)), "serveur arrêté à 17h00 : lot créé à 20h15, fin toujours le lendemain 16h00")
at("2026-11-15T10:00:00"); tick()
ok(batches()[-1].day == "2026-11-14", "le matin suivant : rien (prochain lot à 17h00)")

print("8) PAUSE")
c.post("/admin/club-auctions-settings", json={"paused": True}, headers=A)
at("2026-11-15T17:05:00"); tick()
ok(batches()[-1].day == "2026-11-14", "en pause : pas de lot")
ok(c.get("/admin/club-auctions", headers=A).json()["next_lot_at"] is None and c.get("/club-auctions").json()["paused"] is True, "en pause : pas de prochain lot annoncé")
c.post("/admin/club-auctions-settings", json={"paused": False}, headers=A)
at("2026-11-15T18:00:00"); tick()
ok(batches()[-1].day == "2026-11-15", "reprise après 17h00 : le lot du jour est rattrapé")

print("9) RÉGLAGES, ANNULATION, PROGRAMME")
c.post("/admin/club-auctions-settings", json={"per_day": 3, "start_price": 35}, headers=A)
at("2026-11-16T17:00:00"); tick()
b = batches()[-1]; L = lots(b)
ok(len(L) == 3 and all(db.get(AU.Auction, l.auction_id).start_price == 35 for l in L), "réglages : 3 enchères par jour à 35 crédits")
r = c.post("/admin/club-auctions-cancel", json={"auction_id": L[0].auction_id}, headers=A).json()
db.expire_all()
ok(r["status"] == "ok" and db.get(AU.Auction, L[0].auction_id) is None and db.get(CA.ClubAuctionLot, L[0].auction_id).status == "cancelled" and copy_of(L[0]).status == "reserve", "annuler une enchère sans offre : l'exemplaire reste en réserve")
bid("ana", L[1].auction_id, 35)
ok(c.post("/admin/club-auctions-cancel", json={"auction_id": L[1].auction_id}, headers=A).status_code == 400, "refusé s'il y a déjà une enchère")
prog = c.get("/admin/club-auctions", headers=A).json()
fc = prog["forecast"]
ok(fc["people"] == 32 and fc["per_day"] == 3 and fc["days"] >= -(-fc["remaining"] // 3) and fc["last_lot_day"], "programme : date du dernier lot au rythme actuel (%s, %d jours)" % (fc["last_lot_day"], fc["days"]))
ok(len(prog["series"]) == 32 and all("remaining_for_auctions" in x and "emitted" in x for x in prog["series"]), "programme : émis / restants par personne")
ok(prog["today"] and prog["today"]["count"] == 3 and len(prog["open"]) >= 2, "programme : lot du jour et enchères en cours")
r = c.post("/admin/club-auctions-settings", json={"start_at": "demain"}, headers=A)
ok(r.status_code == 400, "date de démarrage illisible : refusée")
c.post("/admin/club-auctions-settings", json={"per_day": 5, "start_price": 20}, headers=A)
db.expire_all()
logs = [l.summary for l in db.query(AdminLog).order_by(AdminLog.id).all()]
ok(any("Enchères du club : en pause" in l for l in logs) and any("lot lancé à la main" in l for l in logs) and any("Séries Édition Noire" in l for l in logs), "actions résumées dans le journal de l'administration")

print("10) MOINS DE 5 PERSONNES, SÉRIES ÉPUISÉES")
at("2026-11-17T16:00:30"); tick()                      # tout ce qui reste se termine
keep = ["Lucas", "Hugo", "Léo"]
for r in CA.series_state(db):
    if r["subject"] not in keep:
        for cp in db.query(NB.NumberedCopy).filter_by(series_id=r["id"]).all():
            if cp.number != 1: cp.status = "attribue"
db.commit()
at("2026-11-17T17:00:00"); tick()
b = batches()[-1]; L = lots(b)
ok(b.day == "2026-11-17" and len(L) == 3 and {db.get(NB.NumberedSeries, l.series_id).subject for l in L} == set(keep), "seulement 3 personnes avec des numéros restants : 3 enchères")
ok(all(not r["available"] for s, r in state().items() if s not in keep), "une série épuisée n'est jamais choisie")
for r in CA.series_state(db):
    for cp in db.query(NB.NumberedCopy).filter_by(series_id=r["id"]).all():
        if cp.number != 1 and cp.status == "reserve" and not db.query(AU.Auction).filter_by(card_id=cp.card_id).first(): cp.status = "attribue"
db.commit()
at("2026-11-18T16:00:30"); tick()
for r in CA.series_state(db):
    for cp in db.query(NB.NumberedCopy).filter_by(series_id=r["id"]).all():
        if cp.number != 1: cp.status = "attribue"
db.commit()
at("2026-11-18T17:00:00"); tick()
b = batches()[-1]
ok(b.day == "2026-11-18" and b.count == 0 and b.note, "plus aucune carte : lot vide enregistré, rien de créé")
db.expire_all()
ok(any("VIDE" in l.summary for l in db.query(AdminLog).all()), "et c'est signalé dans le journal de l'administration")
ok(c.post("/admin/club-auctions-launch", json={}, headers=A).status_code == 400, "lancer un lot : refusé, plus rien à vendre")
ok(all(r["number_one"] == "reserve" for r in CA.series_state(db)), "les n° 1 sont toujours dans la réserve")
ok(c.post("/admin/series-mint", json={"series": "Édition Noire — Lucas", "pseudo": "ana", "number": 1}, headers=A).json().get("number") == 1, "le n° 1 se donne avec series-mint")

print("11) HEURE D'ÉTÉ / D'HIVER (calcul de weekly.py)")
del os.environ["FC_FAKE_NOW"]
real = CA.datetime
class FakeDT(datetime):
    U = None
    @classmethod
    def utcnow(cls): return cls.U
CA.datetime = FakeDT
try:
    FakeDT.U = datetime(2027, 7, 15, 15, 0); p = CA.paris_now()
    ok(p == datetime(2027, 7, 15, 17, 0), "été : 15h00 UTC = 17h00 à Paris")
    FakeDT.U = datetime(2026, 12, 15, 15, 0); p = CA.paris_now()
    ok(p == datetime(2026, 12, 15, 16, 0) and not CA.due_today(db, p), "hiver : 15h00 UTC = 16h00 à Paris, pas encore l'heure du lot")
    FakeDT.U = datetime(2026, 12, 15, 16, 0); p = CA.paris_now()
    ok(p == datetime(2026, 12, 15, 17, 0) and CA.due_today(db, p), "hiver : 16h00 UTC = 17h00 à Paris, le lot est dû")
    ok(WK.from_paris(datetime(2027, 3, 29, 16, 0)) == datetime(2027, 3, 29, 14, 0) and WK.from_paris(datetime(2026, 10, 26, 16, 0)) == datetime(2026, 10, 26, 15, 0), "fin à 16h00 Paris = 14h00 UTC en été, 15h00 UTC en hiver")
finally:
    CA.datetime = real

db.close()
print("\nRÉSULTAT :", "TOUT EST VERT" if not FAILS else "%d échec(s)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
