"""
Test : mode draft (accès réservé aux comptes choisis, tirage secret de 10 joueurs et 2 fans, enchères ouvertes à 500 pièces, composition
d'une minute, match, récompenses du 1v1 avec les mêmes compteurs du jour, classement par mois, forfait). Lancé par tests/run_tests.py.
"""
import json, random
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import draft as D, missions, duel_engine as DE
from app.models import User, Player, Card, Tier
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
U = lambda p: (db.expire_all(), db.query(User).filter_by(pseudo=p).first())[1]
def mk(p):
    t = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}).json()["token"]
    return {"Authorization": "Bearer " + t}
H = {p: mk(p) for p in ("ana", "bob", "carl")}
for name in ("Supporter Un", "Supporter Deux"):
    f = Player(name=name, poste="FAN"); db.add(f); db.flush(); db.add(Card(player_id=f.id, tier=Tier.commune, vitesse=0, tir=0))
db.commit()
T = [datetime(2026, 11, 20, 12, 0, 0)]
D._now = lambda: T[0]
def tick(s): T[0] += timedelta(seconds=s)
G = lambda p, rid: c.get("/draft/%s" % rid, headers=H[p]).json()

print("1) ACCÈS RÉSERVÉ")
ok(c.get("/draft", headers=H["ana"]).status_code == 403 and c.get("/me", headers=H["ana"]).json()["draft_access"] is False, "fermé par défaut : 403, et /me renvoie draft_access faux")
ok(c.post("/admin/draft-settings", json={"allowed": ["ana", "fantome"]}, headers=A).status_code == 400, "un pseudo inconnu dans la liste : refusé")
ok(c.post("/admin/draft-settings", json={"allowed": ["ana", "bob"]}, headers=A).status_code == 200, "liste des comptes autorisés : ana et bob")
ok(c.get("/draft", headers=H["ana"]).status_code == 200 and c.get("/me", headers=H["bob"]).json()["draft_access"] and c.get("/draft", headers=H["carl"]).status_code == 403,
   "ana et bob y ont accès, carl non (le serveur refuse, pas seulement le site)")

print("2) LE TIRAGE")
shapes = set()
for seed in range(300):
    n = D.line_counts(random.Random(seed)); shapes.add(tuple(n.values()))
    if sum(n.values()) != 10 or not (1 <= n["GB"] <= 3) or not all(2 <= n[k] <= 4 for k in ("DEF", "MC", "ATT")):
        ok(False, "répartition invalide : %s" % n); break
ok(len(shapes) >= 6, "10 joueurs, 1 à 3 gardiens, 2 à 4 par ligne, répartition qui change d'une partie à l'autre (%d répartitions vues)" % len(shapes))
lots = D.generate_pool(db, random.Random(3)); cards = {k.id: k for k in db.query(Card).all()}
pl = [cards[l["card_id"]] for l in lots if l["kind"] == "joueur"]
ok(len(pl) == 10 and len({k.player_id for k in pl}) == 10 and sum(l["kind"] == "fan" for l in lots) == 2, "10 joueurs de 10 personnes différentes et 2 fans")

print("3) LA PARTIE")
r = c.post("/draft/create", json={"invite": "carl"}, headers=H["ana"])
ok(r.status_code == 400 and "accès" in r.json()["detail"], "inviter quelqu'un qui n'a pas accès : refusé")
room = c.post("/draft/create", json={"invite": "bob"}, headers=H["ana"]).json(); rid = room["id"]
ok(room["status"] == "waiting" and c.post("/draft/create", json={}, headers=H["ana"]).status_code == 400, "partie créée (invitation à bob) ; une seule partie à la fois")
c.post("/admin/draft-settings", json={"allowed": ["ana", "bob", "carl"]}, headers=A)
ok(c.post("/draft/%s/join" % rid, headers=H["carl"]).status_code == 403, "partie réservée à bob : carl ne peut pas la rejoindre")
ok(any(o["id"] == rid and o["invited"] for o in c.get("/draft", headers=H["bob"]).json()["open_rooms"]), "bob voit l'invitation dans le salon")
s = c.post("/draft/%s/join" % rid, headers=H["bob"]).json()
ok(s["status"] == "bidding" and s["coins"] == {"me": 500, "opp": 500} and s["lot"]["number"] == 1 and s["lot"]["opener"] == "opp", "bob rejoint : enchères, 500 pièces chacun, ana parle en premier")
room_db = db.get(D.DraftRoom, rid); db.refresh(room_db); st0 = D._st(room_db)
if st0["lots"][0]["kind"] == "fan":                                  # (pour un test stable : les premières cartes sont des joueurs, les fans à la fin ;
    k = next(i for i, l in enumerate(st0["lots"]) if l["kind"] == "joueur"); st0["lots"][0], st0["lots"][k] = st0["lots"][k], st0["lots"][0]   #  sinon le 2e fan part d'office
st0["lots"] = st0["lots"][:1] + sorted(st0["lots"][1:], key=lambda l: l["kind"] == "fan")                   #  et décale l'historique)
D._save(room_db, st0); db.commit(); secret = st0["lots"]
txt = json.dumps(G("bob", rid))
ok("lots" not in json.loads(txt) and all(l["card_id"] not in txt for l in secret[1:]), "les cartes à venir restent secrètes (jamais envoyées au navigateur)")

print("4) LES ENCHÈRES")
ok(c.post("/draft/%s/bid" % rid, json={"amount": 10}, headers=H["bob"]).status_code == 400, "miser quand ce n'est pas son tour : refusé")
c.post("/draft/%s/bid" % rid, json={"amount": 0}, headers=H["ana"])
ok(c.post("/draft/%s/bid" % rid, json={"amount": 3}, headers=H["bob"]).status_code == 400, "surenchère de moins de 5 : refusée")
ok(c.post("/draft/%s/bid" % rid, json={"amount": 600}, headers=H["bob"]).status_code == 400, "miser plus que ses pièces : refusé")
c.post("/draft/%s/bid" % rid, json={"amount": 10}, headers=H["bob"])
s = c.post("/draft/%s/pass" % rid, headers=H["ana"]).json()
ok(s["picks"]["opp"] and s["picks"]["opp"][0]["price"] == 10 and s["coins"]["opp"] == 490 and s["lot"]["number"] == 2 and s["lot"]["opener"] == "opp",
   "ana passe : bob prend la carte pour 10 ; carte 2, c'est bob qui parle en premier (alternance)")
s = c.post("/draft/%s/pass" % rid, headers=H["bob"]).json()
ok(len(s["picks"]["opp"]) == 1 and s["log"][0]["how"] == "given" and s["log"][0]["to"] == "opp" and s["log"][0]["price"] == 0, "passer sans mise : la carte va à l'adversaire pour 0")
tick(13); s = G("ana", rid); G("bob", rid)
ok(s["lot"]["number"] == 4 and s["log"][0]["how"] == "timeout", "12 secondes sans réponse : le joueur passe")
# ana mise tout ce qu'elle a quand c'est à elle de parler, puis on passe jusqu'au bout
spent = False; guard = 0
while True:
    s = G("ana", rid); G("bob", rid); guard += 1
    if s["status"] != "bidding" or guard > 60: break
    who = "ana" if s["lot"]["turn"] == "me" else "bob"
    mine = s["coins"]["me"] if who == "ana" else s["coins"]["opp"]
    if who == "ana" and not spent and s["lot"]["card"]["kind"] == "joueur":
        r = c.post("/draft/%s/bid" % rid, json={"amount": max(mine, s["lot"]["min_bid"])}, headers=H["ana"]); spent = True
        after = r.json()
        ok(after["coins"]["me"] == 0, "ana mise tout (elle tombe à 0 pièce, c'est permis)")
    elif who == "bob" and spent and s["lot"]["high"] is None and s["coins"]["opp"] >= 5 and not getattr(D, "_t_once", False):
        n_lot = s["lot"]["number"]
        r = c.post("/draft/%s/bid" % rid, json={"amount": 5}, headers=H["bob"]).json(); D._t_once = True
        got = next((l for l in r["log"] if l["lot"] == n_lot), None)      # (les cartes suivantes peuvent partir d'office juste après : on lit CETTE carte)
        ok(got is not None and got["how"] == "bid" and got["to"] == "me" and got["price"] == 5, "ana à 0 ne peut plus surenchérir : la carte va tout de suite à bob")
    else:
        c.post("/draft/%s/pass" % rid, headers=H[who])
room_db = db.get(D.DraftRoom, rid); db.refresh(room_db); st = D._st(room_db)
ok(s["status"] == "lineup" and all(sum(p["kind"] == "joueur" for p in st["picks"][x]) == 5 and sum(p["kind"] == "fan" for p in st["picks"][x]) <= 1 for x in D.SIDES)
   and min(st["coins"].values()) >= 0, "fin des enchères : 5 joueurs et au plus 1 fan par équipe, jamais de pièces négatives")

print("5) COMPOSITION ET MATCH")
mine = [p["card_id"] for p in st["picks"]["host"] if p["kind"] == "joueur"]
bad = c.post("/draft/%s/lineup" % rid, json={"formation": "1-2-1", "tactic": "pressing", "slots": [{"card_id": mine[0], "slot_category": "GB"}] * 5}, headers=H["ana"])
ok(bad.status_code == 400, "composition invalide (pas ses 5 joueurs) : refusée")
lu = {"formation": "1-2-1", "tactic": "pressing", "captain_card_id": mine[0],
      "slots": [{"card_id": cid, "slot_category": cat} for cid, cat in zip(mine, ["GB", "DEF", "MC", "MC", "ATT"])]}
s = c.post("/draft/%s/lineup" % rid, json=lu, headers=H["ana"]).json()
ok(s["status"] == "lineup" and s["lineup"]["mine"]["formation"] == "1-2-1" and not s["lineup"]["submitted_opp"], "ana a validé ; bob n'a encore rien envoyé")
before = {p: (U(p).pack_state.match_pack_tokens, U(p).pack_state.shop_pack_tokens) for p in ("ana", "bob")}
tick(61); s = G("ana", rid); sb = G("bob", rid)
m = s["match"]
ok(s["status"] == "done" and m["events"] and 3.5 <= m["starts_in"] <= 4.0 and sb["match"]["score_challenger"] == m["score_challenger"],
   "1 minute passée : équipe automatique pour bob, match joué, départ dans 4 s sur les deux écrans (même score)")
ok(D._st(db.get(D.DraftRoom, rid))["lineups"]["guest"]["auto"], "l'équipe de bob a été choisie automatiquement")
after = {p: (U(p).pack_state.match_pack_tokens, U(p).pack_state.shop_pack_tokens) for p in ("ana", "bob")}
gain = {p: (after[p][0] - before[p][0], after[p][1] - before[p][1]) for p in after}
if m["result"] == "draw":
    ok(gain == {"ana": (0, 1), "bob": (0, 1)}, "match nul : un pack classique chacun")
else:
    win, lose = ("ana", "bob") if m["result"] == "me" else ("bob", "ana")
    ok(gain[win] == (1, 0) and gain[lose] == (0, 1), "victoire de %s : pack match au gagnant, pack classique au perdant" % win)
ok(all(missions.daily_count(db, U(p), "duel_packs") == 1 for p in ("ana", "bob")), "les packs comptent dans la limite des 10 packs 1v1 du jour (même compteur)")
rk = c.get("/draft-ranking", headers=H["ana"]).json()
ok(rk["season"] == "2026-11" and {r["pseudo"] for r in rk["ranking"]} == {"ana", "bob"} and all(r["played"] == 1 for r in rk["ranking"]), "classement du mois : ana et bob, 1 match chacun")
ok(U("ana").elo == 1000 and U("bob").elo == 1000, "l'Elo du 1v1 ne bouge pas")

print("6) LIMITE DU JOUR, FORFAIT, ATTENTE")
ua = U("ana"); missions.daily_add(db, ua, "duel_packs", 9); db.commit()
mp = U("ana").pack_state.match_pack_tokens
res = D._rewards(db, U("ana"), []); db.commit()
ok(res["ana"]["pack"] is None and 1 <= res["ana"]["credits"] <= 5 and U("ana").pack_state.match_pack_tokens == mp, "10 packs déjà gagnés aujourd'hui : 1 à 5 crédits à la place")
rid2 = c.post("/draft/create", json={}, headers=H["ana"]).json()["id"]
ok(any(o["id"] == rid2 for o in c.get("/draft", headers=H["carl"]).json()["open_rooms"]), "partie ouverte : visible par tous ceux qui ont accès")
c.post("/draft/%s/join" % rid2, headers=H["carl"])
for _ in range(5):
    tick(10); G("ana", rid2)                                         # carl ne donne plus signe de vie
s = G("ana", rid2)
ok(s["status"] == "done" and s["match"]["forfeit"] and s["match"]["result"] == "me" and s["match"]["rewards"]["opp"] is None, "carl parti 45 s pendant les enchères : forfait, ana gagne, rien pour carl")
rid3 = c.post("/draft/create", json={}, headers=H["bob"]).json()["id"]
tick(31); c.get("/draft", headers=H["ana"])
ok(db.get(D.DraftRoom, rid3) and (db.refresh(db.get(D.DraftRoom, rid3)) or db.get(D.DraftRoom, rid3).status == "expired"), "créateur parti pendant l'attente : la partie disparaît")
rid4 = c.post("/draft/create", json={}, headers=H["bob"]).json()["id"]
for _ in range(19):
    tick(10); G("bob", rid4)
ok(G("bob", rid4)["status"] == "expired", "personne en 3 minutes : la partie expire")

print("7) CLASSEMENT DU MOIS SUIVANT, ADMIN, SUPPRESSION")
T[0] = datetime(2026, 12, 2, 12, 0, 0)
ok(c.get("/draft-ranking", headers=H["ana"]).json()["ranking"] == [] and len(c.get("/draft-ranking?season=2026-11", headers=H["ana"]).json()["ranking"]) == 3,
   "nouveau mois : classement vide (remis à zéro), novembre reste consultable")
ok(c.get("/admin/draft", headers=A).status_code == 200 and c.post("/admin/draft-reset-ranking", json={"season": "2026-11"}, headers=A).json()["lignes_effacees"] == 3, "admin : vue et effacement du classement d'un mois")
D.on_user_deleted(db, U("carl").id); db.commit()
ok(db.query(D.DraftRoom).filter((D.DraftRoom.host_id == U("carl").id) | (D.DraftRoom.guest_id == U("carl").id)).count() == 0, "compte supprimé : ses parties sont effacées")
gb = [k for k in db.query(Card).all() if k.player.poste == "GB"][:1]; others = [k for k in db.query(Card).all() if k.player.poste == "ATT"][:4]
auto = D.auto_lineup(gb + others)
ok(any(x["slot_category"] == "GB" and x["card_id"] == gb[0].id for x in auto["slots"]), "équipe automatique : le gardien va dans les buts")

print(); print("BILAN (mode draft) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
