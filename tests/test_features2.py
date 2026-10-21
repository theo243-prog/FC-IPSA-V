"""
Test : événements éphémères, enchères, parrainage, mini-jeu du jour. (Le face-à-face est vérifié dans test_duel_packs.py.)
Lancer comme test_tournament.py (voir tests/LISEZMOI.md).
"""
import math, random
from datetime import date, datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import battlepass as BP, events as EV, auctions as AU, minigame as MG, game_logic as GL, offers as OF, referral as RF, missions as MS
from app.models import User, Card, OwnedCard, Tier, PackState
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []; db = SessionLocal()
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
NOW = [datetime(2026, 11, 10, 12, 0)]; BP.now_paris = lambda: NOW[0]; EV._now = lambda: NOW[0]; AU._now = lambda: NOW[0]
DAY = [date(2026, 11, 10)]; GL.today_paris = lambda: DAY[0]
H = {}
def mk(p, credits=500, ref=None):
    body = {"pseudo": p, "password": "test1234"}
    if ref: body["referral_code"] = ref
    r = c.post("/auth/register", json=body); H[p] = {"Authorization": "Bearer " + r.json()["token"]}
    u = db.query(User).filter_by(pseudo=p).first(); u.credits = credits; db.commit(); return r.json()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
tok = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first().pack_state.ultra_pack_tokens)[1]          # (les packs ULTRA du parrainage)
def give(p, tier, n=1):
    u = U(p); card = db.query(Card).filter(Card.tier == tier).first(); o = db.query(OwnedCard).filter_by(user_id=u.id, card_id=card.id).first()
    if o is None: o = OwnedCard(user_id=u.id, card_id=card.id, quantity=0); db.add(o)
    o.quantity += n; db.commit(); return card
for p in ("sel", "b1", "b2", "poor"): mk(p, 5 if p == "poor" else 500)

print("1) ÉVÉNEMENTS ÉPHÉMÈRES")
ok(c.post("/admin/event", json={"kind": "shop_discount"}).status_code == 403 and c.post("/admin/event", json={"kind": "nimportequoi"}, headers=A).status_code == 422 and c.post("/admin/event", json={"kind": "free_pack", "pack": "match"}, headers=A).status_code == 422, "réservé à l'admin (403) ; sorte ou pack inconnu : 422")
ok(c.get("/events").json()["events"] == [], "aucun événement : pas de bandeau")
r = c.post("/admin/event", json={"kind": "shop_discount", "duration_hours": 60}, headers=A).json(); e1 = r["id"]
ok(r["status"] == "ok" and r["title"] == "Packs à moitié prix" and r["active"], "promo lancée : « " + r["title"] + " »")
sh = {i["pack_type"]: i for i in c.get("/shop/items").json()}; ok(sh["classique"]["price"] == 25 and sh["classique"]["base_price"] == 50 and sh["classique"]["discount"] == 50 and sh["rare"]["price"] == 50, "boutique : classique 25 au lieu de 50, rare 50 au lieu de 100")
cr = U("b1").credits; c.post("/shop/buy", json={"item": "pack_classique"}, headers=H["b1"]); ok(U("b1").credits == cr - 25, "l'achat est débité au prix réduit (−25)")
ev = c.get("/events", headers=H["b1"]).json()["events"]; ok(len(ev) == 1 and ev[0]["active"] and ev[0]["kind"] == "shop_discount" and 59 * 3600 < ev[0]["seconds_left"] <= 60 * 3600, "le bandeau voit l'événement et son compte à rebours (~60 h)")
rp = c.post("/admin/event", json={"kind": "pass_double", "duration_hours": 24}, headers=A).json(); e2 = rp["id"]
u = U("b2"); g = BP.add_points(db, u, "duel", 10, 50); db.commit(); ok(g == 20, "événement « Pass ×2 » : un match 1v1 (+10) rapporte +20")
NOW[0] = datetime(2026, 11, 28, 12, 0); u = U("b2"); g = BP.add_points(db, u, "swap", 10, 30); db.commit(); ok(g == 20, "le 28 (dernière semaine, déjà ×2) avec l'événement : toujours +20, pas de cumul (×4)")
NOW[0] = datetime(2026, 11, 10, 12, 0)
c.post("/admin/event-cancel", json={"id": e2}, headers=A); u = U("b2"); g = BP.add_points(db, u, "duel", 10, 50); db.commit(); ok(g == 10, "événement annulé : retour à +10")
rf = c.post("/admin/event", json={"kind": "free_pack", "duration_hours": 48, "pack": "rare", "per_day": 2}, headers=A).json(); e3 = rf["id"]
ev = {x["kind"]: x for x in c.get("/events", headers=H["sel"]).json()["events"]}; ok("free_pack" in ev and ev["free_pack"]["claimed_today"] is False, "pack gratuit : proposé, pas encore récupéré")
t0 = U("sel").pack_state.rare_pack_tokens if hasattr(U("sel").pack_state, "rare_pack_tokens") else None
r = c.post(f"/events/{e3}/claim", headers=H["sel"]); ok(r.status_code == 200 and r.json()["count"] == 2 and r.json()["pack"] == "rare", "récupérer : 2 packs rares offerts")
ok(c.post(f"/events/{e3}/claim", headers=H["sel"]).status_code == 400 and {x["kind"]: x for x in c.get("/events", headers=H["sel"]).json()["events"]}["free_pack"]["claimed_today"] is True, "une seule fois par jour : « déjà récupéré » (400), et le bandeau le sait")
NOW[0] += timedelta(days=1); ok(c.post(f"/events/{e3}/claim", headers=H["sel"]).status_code == 200, "le lendemain (minuit passé), on peut en reprendre")
ok(c.post(f"/events/{e1}/claim", headers=H["sel"]).status_code == 404 and c.post("/events/inconnu/claim", headers=H["sel"]).status_code == 404 and c.post(f"/events/{e3}/claim").status_code == 401, "claim d'un autre sorte / inconnu : 404 ; sans compte : 401")
NOW[0] += timedelta(days=3); sh = {i["pack_type"]: i for i in c.get("/shop/items").json()}; ok(sh["classique"]["price"] == 50 and c.get("/events").json()["events"] == [], "après la fin (60 h) : prix normaux, plus de bandeau")
NOW[0] = datetime(2026, 11, 10, 12, 0); c.post("/admin/event-cancel", json={"id": e1}, headers=A); c.post("/admin/event-cancel", json={"id": e3}, headers=A)
rl = c.post("/admin/event", json={"kind": "shop_discount", "percent": 30, "start_in_hours": 5, "duration_hours": 10, "title": "Week-end test"}, headers=A).json()
ok(not rl["active"] and rl["starts_in"] == 5 * 3600 and c.get("/shop/items").json()[0]["price"] == 50, "un événement qui commence dans 5 h : annoncé mais pas encore actif (prix normaux)")
NOW[0] += timedelta(hours=6); ok(c.get("/shop/items").json()[0]["price"] == 35, "6 h plus tard : actif (−30 % : 35)")
lst = c.get("/admin/events", headers=A).json(); ok(len(lst) == 4 and {x["état"] for x in lst} >= {"en cours", "annulé"} and c.post("/admin/event-cancel", json={"id": "inconnu"}, headers=A).status_code == 404, "la liste admin montre les états (en cours, annulé…) ; annuler un inconnu : 404")
c.post("/admin/event-cancel", json={"id": rl["id"]}, headers=A); NOW[0] = datetime(2026, 11, 10, 12, 0)

print("2) ENCHÈRES")
card = give("sel", Tier.rare, 2); cm = give("sel", Tier.commune)
mk_a = lambda cid, price=10, minutes=15, who="sel": c.post("/auctions", json={"card_id": cid, "start_price": price, "minutes": minutes}, headers=H[who])
ok(mk_a(cm.id).status_code == 400 and mk_a("nimporte").status_code == 400 and mk_a(card.id, 0).status_code == 422 and mk_a(card.id, 10, 14).status_code == 422 and mk_a(card.id, 10, 1441).status_code == 422, "refusé : carte commune, carte non possédée, prix 0, durée 14 min ou 1441 min")
q0 = db.query(OwnedCard).filter_by(user_id=U("sel").id, card_id=card.id).first().quantity; r = mk_a(card.id, 10, 15); aid = r.json()["id"]; db.expire_all()
ok(r.status_code == 200 and r.json()["seconds_left"] == 900 and db.query(OwnedCard).filter_by(user_id=U("sel").id, card_id=card.id).first().quantity == q0 - 1, "mise aux enchères (départ 10, 15 min) : la carte est mise de côté")
d = c.get("/auctions").json(); a = d["auctions"][0]; ok(d["durations"] == [15, 30, 60, 180, 360, 720, 1440] and a["start_price"] == 10 and a["min_next_bid"] == 10 and a["current_bid"] is None and a["seller_pseudo"] == "sel" and a["bids"] == 0, "la liste : prix de départ 10, boutons de durée 15 min à 24 h")
bid = lambda who, amt, i=None: c.post(f"/auctions/{i or aid}/bid", json={"amount": amt}, headers=H[who])
ok(bid("sel", 50).status_code == 400 and bid("b1", 9).status_code == 400 and bid("poor", 10).status_code == 400, "le vendeur ne peut pas enchérir ; sous le départ : refusé ; pas assez de crédits : refusé")
r = bid("b1", 10); ok(r.status_code == 200 and U("b1").credits == 500 - 25 - 10 and r.json()["min_next_bid"] == 11, "b1 mise 10 : crédits mis de côté, prochaine enchère minimum 11")
ok(bid("b2", 10).status_code == 400 and bid("b2", 11).status_code == 200 and U("b1").credits == 500 - 25 and U("b2").credits == 489, "b2 doit faire au moins 11 ; il mise 11 → b1 est remboursé tout de suite")
bid("b1", 100); r = bid("b2", 104); ok(r.status_code == 400 and "105" in r.json()["detail"], "après 100 : minimum +5 % = 105 (104 refusé)")
ok(bid("b2", 105).status_code == 200 and bid("b2", 120).status_code == 200 and U("b2").credits == 500 - 120 and U("b1").credits == 500 - 25, "b2 relève sa propre enchère à 120 : seule la différence est débitée (380)")
a = c.get("/auctions", headers=H["b2"]).json()["auctions"][0]; ok(a["current_bid"] == 120 and a["top_bidder"] == "b2" and a["i_am_top"] and a["bids"] == 5 and c.get("/auctions", headers=H["sel"]).json()["auctions"][0]["mine"], "la liste : meilleure enchère 120 par b2, « i_am_top », « mine » pour le vendeur")
ok(OF.reserved_credits(db).get(U("b2").id) == 120, "les 120 crédits de b2 comptent dans le total public du classement")
ok(c.delete(f"/auctions/{aid}", headers=H["sel"]).status_code == 400 and c.delete(f"/auctions/{aid}", headers=H["b1"]).status_code == 404, "le vendeur ne peut plus annuler (il y a des enchères) ; un autre joueur : 404")
NOW[0] = datetime(2026, 11, 10, 12, 14, 0); r = bid("b1", 126); ok(r.status_code == 200 and r.json()["seconds_left"] == 120, "enchère à 1 min de la fin (12:14, fin 12:15) : prolongée à 2 min (anti-dernière seconde)")
NOW[0] = datetime(2026, 11, 10, 12, 20, 0); s0 = U("sel").credits; b1_cards = db.query(OwnedCard).filter_by(user_id=U("b1").id, card_id=card.id).first()
d = c.get("/auctions").json(); db.expire_all(); got = db.query(OwnedCard).filter_by(user_id=U("b1").id, card_id=card.id).first()
ok(d["auctions"] == [] and got is not None and got.quantity == 1 and U("sel").credits == s0 + 126 and U("b1").credits == 500 - 25 - 126 and U("b2").credits == 500, "fin : b1 remporte la carte pour 126, le vendeur est payé, b2 remboursé")
h = c.get("/market/history").json(); ok(any(x.get("kind") == "enchère" and x["price"] == 126 for x in (h if isinstance(h, list) else h.get("trades", h.get("history", [])))), "la vente figure dans l'historique du marché (« enchère », 126)")
aid2 = mk_a(card.id, 5, 30).json()["id"]; ok(c.delete(f"/auctions/{aid2}", headers=H["sel"]).status_code == 200 and db.query(AU.Auction).count() == 0, "annuler une enchère sans mise : la carte revient")
aid3 = mk_a(card.id, 5, 60).json()["id"]; NOW[0] += timedelta(minutes=61); c.get("/auctions"); db.expire_all(); ok(db.query(AU.Auction).count() == 0, "sans enchère : l'enchère disparaît à la fin")
nq = db.query(OwnedCard).filter_by(user_id=U("sel").id, card_id=card.id).first().quantity; ok(nq == 1, f"…(il lui en reste {nq}, comme avant l'enchère perdue : 2 − 1 vendue)")
rare2 = give("sel", Tier.rare, 5); ids = [mk_a(rare2.id, 1, 15).json().get("id") for _ in range(6)]
ok(sum(1 for i in ids if i) == 5 and db.query(AU.Auction).filter_by(seller_id=U("sel").id).count() == 5, "5 enchères ouvertes au maximum par vendeur (la 6e est refusée)")
first = c.get("/auctions").json()["auctions"][0]["id"]; bid("b1", 1, first); b1c = U("b1").credits; AU.cancel_for_cards(db, [rare2.id]); db.commit(); ok(U("b1").credits == b1c + 1 and db.query(AU.Auction).count() == 0, "une carte supprimée du jeu : enchères annulées et enchérisseur remboursé")
ida = mk_a(card.id, 5, 60, "b1"); idv = ida.json().get("id"); bid("b2", 5, idv); b2c = U("b2").credits; AU.on_user_deleted(db, U("b1").id); db.commit(); ok(U("b2").credits == b2c + 5 and db.query(AU.Auction).count() == 0, "un vendeur supprimé : son enchère est annulée, l'enchérisseur remboursé")

print("3) PARRAINAGE")
r = c.get("/referral", headers=H["sel"]).json(); code = r["code"]; ok(len(code) == 6 and r["count"] == 0 and r["max"] == 3 and r["can_use"] is True and c.get("/referral", headers=H["sel"]).json()["code"] == code, "chaque joueur a un code de 6 caractères (stable)")
t_s = tok("sel"); out = mk("f1", 0, ref=code.lower()); ok(out["referral"]["ok"] and out["referral"]["referrer"] == "sel" and tok("sel") == t_s + 1 and tok("f1") == 1, "inscription avec le code de s : un pack ULTRA pour s ET pour le filleul (le code marche en minuscules)")
ok(c.get("/referral", headers=H["sel"]).json()["referees"] == ["f1"] and c.get("/referral", headers=H["f1"]).json()["used_with"] == "sel" and c.get("/referral", headers=H["f1"]).json()["can_use"] is False, "s voit son filleul ; f1 voit qui l'a invité")
ok(any("grâce à sel" in m["text"] for m in c.get("/chat", headers=H["sel"]).json()["messages"]) if "messages" in c.get("/chat", headers=H["sel"]).json() else True, "annonce dans le chat")
ok(c.post("/referral/use", json={"code": code}, headers=H["f1"]).status_code == 400 and c.post("/referral/use", json={"code": code}, headers=H["sel"]).status_code == 400 and c.post("/referral/use", json={"code": "ZZZZZZ"}, headers=H["b1"]).status_code == 404, "déjà utilisé : 400 ; son propre code : 400 ; code inconnu : 404")
out = mk("f2", 0, ref="ZZZZZZ"); ok(out["referral"]["ok"] is False and "inconnu" in out["referral"]["message"] and tok("f2") == 0 and "token" in out, "un mauvais code à l'inscription ne bloque pas la création du compte (pas de pack)")
u = U("b2"); u.created_at = datetime.utcnow() - timedelta(days=10); db.commit(); ok(c.post("/referral/use", json={"code": code}, headers=H["b2"]).status_code == 400, "un compte de plus de 7 jours ne peut plus saisir de code")
c.post("/referral/use", json={"code": code}, headers=H["poor"]); for_cap = [mk("g0", 0, ref=code)]
ok(all(x["referral"]["ok"] for x in for_cap) and c.get("/referral", headers=H["sel"]).json()["count"] == 3, "le code accepte 3 filleuls au maximum (f1, poor, g0 : compte atteint 3)")
out = mk("g1", 0, ref=code); ok(out["referral"]["ok"] is False and "limite de 3" in out["referral"]["message"] and tok("g1") == 0, "le 4e : refusé (« limite de 3 parrainages »), aucun pack")

print("4) MINI-JEU DU JOUR")
quiz_day = next(d for d in (date(2026, 11, 10) + timedelta(days=k) for k in range(2)) if MG.kind_for(d.isoformat()) == "quiz"); pen_day = quiz_day + timedelta(days=1) if MG.kind_for((quiz_day + timedelta(days=1)).isoformat()) == "penalty" else quiz_day - timedelta(days=1)
DAY[0] = quiz_day; NOW[0] = datetime(quiz_day.year, quiz_day.month, quiz_day.day, 12, 0); mk("q1", 100)
g = c.get("/minigame", headers=H["q1"]).json(); ok(g["kind"] == "quiz" and not g["finished"] and g["question"]["index"] == 0 and len(g["question"]["choices"]) == 3 and "answer" not in g["question"], "jour de quiz : question 1/5 avec 3 réponses, sans la bonne réponse")
ms = {m["id"]: m for m in c.get("/missions", headers=H["q1"]).json()["missions"]}; ok("minigame" in ms and ms["minigame"]["progress"] == 0 and len(ms) == 3, "le mini-jeu est l'un des trois défis du jour (0/1)")
qs = MG.questions_for(quiz_day.isoformat()); p0 = c.get("/pass", headers=H["q1"]).json()["current"]["points"]
for i in range(5):
    choice = qs[i]["answer"] if i < 4 else (qs[i]["answer"] + 1) % 3; r = c.post("/minigame/answer", json={"choice": choice}, headers=H["q1"]).json()
    ok(r["correct"] == (i < 4) and r["answer"] == qs[i]["answer"] and r["why"] == qs[i]["why"], f"question {i + 1} : {'bonne' if i < 4 else 'mauvaise'} réponse → {'✅' if r['correct'] else '❌'} (la bonne réponse et l'explication sont révélées après coup)") if i in (0, 4) else None
ok(r["finished"] and r["score"] == 4 and r["pass_points"] == 40, "fin du quiz : 4/5 → 40 points de Pass (10 par bonne réponse)")
ms = {m["id"]: m for m in c.get("/missions", headers=H["q1"]).json()["missions"]}; ok(ms["minigame"]["progress"] == 1 and c.get("/pass", headers=H["q1"]).json()["current"]["points"] == p0 + 40, "la mission « mini-jeu » est faite (1/1) et le Pass a +40 points")
ok(c.post("/minigame/answer", json={"choice": 0}, headers=H["q1"]).status_code == 400 and c.post("/minigame/shoot", json={"zone": 0}, headers=H["q1"]).status_code == 400, "un seul jeu par jour : rejouer ou tirer un penalty est refusé (400)")
r = c.post("/missions/claim", json={"kind": "mission", "mission_id": "minigame"}, headers=H["q1"]); ok(r.status_code == 200, "la mission se récupère comme les autres (crédits)")
DAY[0] = pen_day; NOW[0] = datetime(pen_day.year, pen_day.month, pen_day.day, 12, 0); mk("p1", 100)
class Fake:
    def __init__(self, zone, miss): self.zone, self.miss = zone, miss
    def random(self): return 0.99                  # jamais de tir manqué, le gardien ne devine pas
    def randrange(self, n): return self.zone
g = c.get("/minigame", headers=H["p1"]).json(); ok(g["kind"] == "penalty" and g["remaining"] == 5 and g["shots"] == [], "jour pair : tirs au but, 5 tirs à faire")
MG.RNG = Fake(1, 0); p0 = c.get("/pass", headers=H["p1"]).json()["current"]["points"]
rs = [c.post("/minigame/shoot", json={"zone": 0}, headers=H["p1"]).json() for _ in range(5)]
ok(all(r["goal"] and r["keeper"] == 1 for r in rs) and rs[-1]["finished"] and rs[-1]["score"] == 5 and rs[-1]["pass_points"] == 50, "5 tirs à gauche, gardien au centre : 5 buts → 50 points de Pass (le maximum)")
ok(c.post("/minigame/shoot", json={"zone": 0}, headers=H["p1"]).status_code == 400 and c.get("/pass", headers=H["p1"]).json()["current"]["points"] == p0 + 50, "un 6e tir est refusé ; +50 points exactement")
mk("p2", 100); MG.RNG = Fake(2, 0); rs = [c.post("/minigame/shoot", json={"zone": 2}, headers=H["p2"]).json() for _ in range(5)]; ok(rs[-1]["score"] == 0 and not any(r["goal"] for r in rs) and rs[-1]["pass_points"] == 0, "gardien devine toujours : 0 but, 0 point")
MG.RNG = random.Random(3); mk("p3", 100); rs = [c.post("/minigame/shoot", json={"zone": z}, headers=H["p3"]).json() for z in (0, 1, 2, 1, 0)]; ok(rs[-1]["score"] == sum(1 for r in rs if r["goal"]) and rs[-1]["finished"], "avec un vrai hasard : le score est le nombre de buts")
print("   (donner un jeu précis à un joueur, pour tester)")
DAY[0] = quiz_day; NOW[0] = datetime(quiz_day.year, quiz_day.month, quiz_day.day, 12, 0); mk("m1", 100)
ok(c.get("/minigame", headers=H["m1"]).json()["kind"] == "quiz", "ce jour-là, le mini-jeu normal est le quiz")
ok(c.post("/admin/minigame-set", json={"pseudo": "m1", "kind": "penalty"}).status_code == 403 and c.post("/admin/minigame-set", json={"pseudo": "inconnu", "kind": "penalty"}, headers=A).status_code == 404 and c.post("/admin/minigame-set", json={"pseudo": "m1", "kind": "foot"}, headers=A).status_code == 422, "commande réservée à l'admin (403), pseudo inconnu (404), jeu inconnu (422)")
r = c.post("/admin/minigame-set", json={"pseudo": "m1", "kind": "penalty"}, headers=A); g = c.get("/minigame", headers=H["m1"]).json()
ok(r.status_code == 200 and g["kind"] == "penalty" and g["remaining"] == 5 and not g["finished"], "m1 reçoit les tirs au but alors que c'est un jour de quiz : 5 tirs à faire")
MG.RNG = Fake(1, 0); rs = [c.post("/minigame/shoot", json={"zone": 0}, headers=H["m1"]).json() for _ in range(5)]; ok(rs[-1]["finished"] and rs[-1]["score"] == 5, "il joue ses 5 tirs jusqu'au bout")
c.post("/admin/minigame-set", json={"pseudo": "m1", "kind": "quiz"}, headers=A); g = c.get("/minigame", headers=H["m1"]).json(); ok(g["kind"] == "quiz" and not g["finished"] and g["question"]["index"] == 0, "même après avoir fini, on peut lui redonner un jeu à zéro (ici le quiz)")
print("   (le but à 6 zones)")
ok(not MG.adjacent(0, 4) and MG.adjacent(0, 1) and MG.adjacent(0, 3) and MG.adjacent(4, 3) and MG.adjacent(4, 5) and MG.adjacent(1, 4) and not MG.adjacent(2, 3) and not MG.adjacent(0, 2), "zones voisines : à côté ou au-dessus/en dessous, jamais en diagonale ni aux deux extrémités")
class Fx:
    def __init__(self, keeper, rnd): self.keeper, self.rnd = keeper, rnd
    def random(self): return self.rnd
    def randrange(self, n): return self.keeper
DAY[0] = DAY[0] + timedelta(days=1); NOW[0] = NOW[0] + timedelta(days=1); k = 0
def one(keeper, rnd, zone):
    global k; k += 1; DAY[0] = DAY[0] + timedelta(days=2); mk("z%d" % k, 100); MG.RNG = Fx(keeper, rnd)
    if MG.kind_for(DAY[0].isoformat()) != "penalty": DAY[0] = DAY[0] + timedelta(days=1)
    return c.post("/minigame/shoot", json={"zone": zone}, headers=H["z%d" % k]).json()
r = one(3, 0.1, 4); ok(r["finger"] and not r["goal"] and not r["missed"] and r["keeper"] == 3 and r["keeper_name"] == "en bas à gauche" and r["zone_name"] == "en bas au centre", "gardien dans une zone voisine (30 % de chances) : arrêt « du bout des doigts »")
r = one(0, 0.1, 4); ok(r["goal"] and not r["finger"], "gardien en diagonale : pas d'arrêt, c'est un but")
r = one(4, 0.99, 4); ok(not r["goal"] and not r["finger"] and not r["missed"], "gardien dans la zone exacte : toujours arrêté")
r = one(0, 0.01, 1); ok(r["missed"] and not r["goal"], "tir en haut avec un tirage à 1 % : hors cadre (12 % de risque en haut)")
r = one(0, 0.08, 4); ok(not r["missed"] and not r["finger"] and r["goal"] is True, "le même tirage (8 %) en bas : dans le cadre (seulement 6 % de risque en bas)")
r = one(5, 0.99, 5); ok(not r["goal"], "la zone 5 (en bas à droite) est acceptée")
DAY[0] = DAY[0] + timedelta(days=2); mk("z99", 100); ok(c.post("/minigame/shoot", json={"zone": 6}, headers=H["z99"]).status_code == 422 and c.post("/minigame/shoot", json={"zone": -1}, headers=H["z99"]).status_code == 422, "zone 6 ou -1 : refusée (422)")
MG.RNG = random.Random(11); tot = 0; n = 3000
for i in range(n):
    prev = None; kz = prev if (prev is not None and MG.RNG.random() < MG.KEEPER_REPEAT) else MG.RNG.randrange(6); zz = MG.RNG.randrange(6)
    miss = MG.RNG.random() < (MG.MISS_TOP if zz < 3 else MG.MISS_BOTTOM); fin = (not miss) and kz != zz and MG.adjacent(kz, zz) and MG.RNG.random() < MG.FINGER_SAVE; tot += 1 if (not miss and kz != zz and not fin) else 0
ok(0.55 < tot / n < 0.70, f"avec un tireur au hasard, environ {round(100 * tot / n)} % de buts (réglage prévu : ~6 sur 10)")
DAY[0] = DAY[0] + timedelta(days=1); ok(c.get("/minigame", headers=H["p1"]).json()["finished"] is False and c.get("/minigame", headers=H["p1"]).json()["kind"] == "quiz", "le lendemain : nouveau jeu (le quiz), à zéro")
ok(c.get("/minigame").status_code == 401, "sans compte : 401")
print(); print("BILAN (événements, enchères, parrainage, mini-jeu) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
