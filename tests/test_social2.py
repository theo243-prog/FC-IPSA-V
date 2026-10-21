"""
Test : titres et cadres, chat, échanges de cartes, pronostics.
Lancer (depuis le dossier fc-format-a5-admin-update) :
    rm -f /tmp/fc_test.db && ADMIN_KEY=k DATABASE_URL=sqlite:////tmp/fc_test.db PYTHONPATH=. python -m app.seed_data && \
    ADMIN_KEY=k DATABASE_URL=sqlite:////tmp/fc_test.db PYTHONPATH=. python tests/test_social2.py
"""
import time
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import profiles as PR, seasons as S, chat as CH, swaps as SW, prono as PN, cosmetics as CO, game_logic as GL
from app.models import User, Card, Player, OwnedCard, Tier, UpcomingMatch
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
def mk(p):
    r = c.post("/auth/register", json={"pseudo": p, "password": "test1234"}); return {"Authorization": "Bearer " + r.json()["token"]}
U = lambda p: db.query(User).filter_by(pseudo=p).first()
def fresh(): db.expire_all()
card = lambda n, t: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
def own(p, n, t, q):
    u = U(p); o = db.query(OwnedCard).filter_by(user_id=u.id, card_id=card(n, t).id).first()
    if o: o.quantity = q
    else: db.add(OwnedCard(user_id=u.id, card_id=card(n, t).id, quantity=q))
    db.commit()
def credits(p): fresh(); return U(p).credits
def setc(p, v): U(p).credits = v; db.commit()
for nm, tr in (("Nolan", "legendaire"), ("Mathis", "epique")): c.post("/admin/create-card", json={"player_name": nm, "tier": tr}, headers=A)
GL.ensure_secret_cards(db)
Ha, Hb, Hc, Hd = mk("ana"), mk("ben"), mk("cléo"), mk("dan")

print("1) TITRES ET CADRES")
cat = c.get("/cosmetics", headers=Ha).json(); ok(not any(t["unlocked"] for t in cat["titles"]) and not any(f["unlocked"] for f in cat["frames"]) and len(cat["titles"]) == 33 and len(cat["frames"]) == 6, f"un compte neuf : {len(cat['titles'])} titres et {len(cat['frames'])} cadres, tous verrouillés")
ok(c.post("/cosmetics", json={"title": "packs", "frame": None}, headers=Ha).status_code == 400 and c.post("/cosmetics", json={"title": None, "frame": "bronze"}, headers=Ha).status_code == 400, "choisir un titre ou un cadre verrouillé : refusé (400)")
ua = U("ana").id
for bid, lv in [("packs", 1), ("packs", 2), ("collection", 1), ("matchs", 1), ("matchs", 2)]: db.add(PR.UserBadge(user_id=ua, badge_id=bid, level=lv, seen=True))
db.commit(); cat = c.get("/cosmetics", headers=Ha).json(); tl = {t["id"]: t for t in cat["titles"]}; fr = {f["id"]: f for f in cat["frames"]}
ok(tl["packs"]["unlocked"] and tl["packs"]["label"] == "Ouvreur de packs" and tl["matchs"]["unlocked"] and not tl["collection"]["unlocked"] and not tl["packs_max"]["unlocked"], "5 niveaux : « Ouvreur de packs » débloqué, pas « Collectionneur » ni le titre maître")
ok(fr["bronze"]["unlocked"] and not fr["argent"]["unlocked"] and not fr["champion"]["unlocked"], "…et le cadre Bronze, pas le suivant")
r = c.post("/cosmetics", json={"title": "packs", "frame": "bronze"}, headers=Ha); ok(r.status_code == 200 and r.json()["title"] == "Ouvreur de packs", "choix enregistré")
lb = {x["pseudo"]: x for x in c.get("/leaderboard").json()}; pf = c.get("/users/ana/profile").json()
ok(lb["ana"]["title"] == "Ouvreur de packs" and lb["ana"]["frame"] == "bronze" and pf["title"] == "Ouvreur de packs" and pf["frame"] == "bronze" and lb["ben"]["title"] is None, "classement et profil affichent ce choix")
db.add(S.SeasonResult(season="2026-07", rank=1, user_id=ua, pseudo="ana", elo=1100, matches=6, wins=5, credits=0, closed_at=datetime.utcnow())); db.commit()
cat = c.get("/cosmetics", headers=Ha).json(); ok(any(t["id"] == "champion" and t["unlocked"] for t in cat["titles"]) and any(f["id"] == "champion" and f["unlocked"] for f in cat["frames"]), "gagner une saison débloque titre et cadre « Champion »")
for k, v in (("prono_placed", 5), ("prono_exact", 3)): PR.bump(db, U("ana"), k, v)
db.commit(); cat = c.get("/cosmetics", headers=Ha).json(); ok(all(any(t["id"] == i and t["unlocked"] for t in cat["titles"]) for i in ("prono", "oracle")), "pronostics réglés et scores exacts débloquent « Pronostiqueur » et « Oracle »")
ok(c.post("/admin/unlock-cosmetics", json={"pseudo": "cléo", "enabled": True}).status_code == 403 and c.post("/admin/unlock-cosmetics", json={"pseudo": "inconnu"}, headers=A).status_code == 404, "tout débloquer : 403 sans clé, 404 pseudo inconnu")
r = c.post("/admin/unlock-cosmetics", json={"pseudo": "cléo", "enabled": True}, headers=A); cc = c.get("/cosmetics", headers=Hc).json()
from app import pass_catalog as PC
inv = c.get("/pass/inventory", headers=Hc).json()["items"]; kinds = {i["kind"] for i in inv}
ok(len(inv) == len(PC.ITEMS) and kinds == set(PC.KINDS) and len(inv) == 232, f"« tout débloquer » donne aussi les {len(inv)} objets de tous les Pass ({len(kinds)} sortes : badges, bannières, cadres, couleurs de pseudo, titres, autocollants, fonds d'image)")
pick = lambda k, n: [i["id"] for i in inv if i["kind"] == k][n]
ok(c.post("/pass/equip", json={"banner": pick("banner", -1), "name_color": pick("name_color", 0), "badge": pick("badge", 5), "share_bg": pick("share_bg", -1)}, headers=Hc).status_code == 200, "on peut équiper des objets de thèmes différents (bannière, couleur de pseudo, badge, fond d'image)")
ok(sum(1 for t in cc["titles"] + cc["frames"] if t.get("pass")) >= 60, "les titres et cadres des Pass sont dans la liste « Titre et cadre »")
ok(r.status_code == 200 and all(t["unlocked"] for t in cc["titles"]) and all(f["unlocked"] for f in cc["frames"]), f"commande « tout débloquer » : les {len(cc['titles'])} titres et les {len(cc['frames'])} cadres sont choisissables sur ce compte")
ok(c.post("/cosmetics", json={"title": "oracle", "frame": "legende"}, headers=Hc).status_code == 200 and c.get("/users/cléo/profile").json()["frame"] == "legende" and c.get("/users/cléo/profile").json()["title"] == "Oracle", "on peut choisir un titre et un cadre que le compte n'a pas gagnés : ils s'affichent (profil)")
ok(c.post("/admin/unlock-cosmetics", json={"pseudo": "cléo", "enabled": False}, headers=A).status_code == 200 and not c.get("/pass/inventory", headers=Hc).json()["items"] and not any(t["unlocked"] for t in c.get("/cosmetics", headers=Hc).json()["titles"]) and c.post("/cosmetics", json={"title": "champion", "frame": None}, headers=Hc).status_code == 400, "retirer : retour au déblocage normal (rien de débloqué, choisir un titre verrouillé est refusé)")
ok(any("Déblocage manuel des cosmétiques retiré pour cléo" == x["action"] for x in c.get("/admin/log", headers=A).json()), "l'action figure dans le journal")
ok(c.post("/cosmetics", json={"title": None, "frame": None}, headers=Ha).status_code == 200 and c.get("/users/ana/profile").json()["frame"] is None and c.get("/cosmetics").status_code == 401, "tout retirer : possible ; sans compte : 401")

print("2) LE CHAT")
r = c.post("/chat", json={"text": "  Salut   tout le monde ! "}, headers=Hb); ok(r.status_code == 200 and r.json()["text"] == "Salut tout le monde !" and r.json()["mine"], "un message est publié (espaces nettoyés)")
ok(c.post("/chat", json={"text": "deux"}, headers=Hb).status_code == 429, "un 2e message immédiat : 429")
time.sleep(1.6)
ok(c.post("/chat", json={"text": "   "}, headers=Hb).status_code == 400 and c.post("/chat", json={"text": "x" * 301}, headers=Hb).status_code == 400 and c.post("/chat", json={"text": "x" * 300}, headers=Hb).status_code == 200, "vide ou > 300 caractères refusé ; 300 pile accepté")
ok(c.get("/chat").status_code == 401 and c.post("/chat", json={"text": "a"}).status_code == 401, "sans compte : 401")
d = c.get("/chat", headers=Ha).json(); evs = [m for m in d["messages"] if m["kind"] == "event"]
ok(any("ana a rejoint le club" in e["text"] for e in evs) and d["last_id"] == d["messages"][-1]["id"], "les arrivées sont annoncées ; on connaît le dernier numéro")
lastid = d["last_id"]; time.sleep(1.6); c.post("/chat", json={"text": "nouveau"}, headers=Hc)
ok([m["text"] for m in c.get("/chat", params={"after_id": lastid}, headers=Ha).json()["messages"]] == ["nouveau"] and c.get("/me", headers=Ha).json()["chat_last_id"] >= lastid + 1, "« après le numéro N » ne renvoie que les nouveaux ; /me donne le dernier numéro")
c.post("/admin/grant-packs", json={"pseudo": "dan", "count": 1, "pack_type": "legendaire"}, headers=A); r = c.post("/pack/open", json={"pack_type": "legendaire"}, headers=Hd)
ev = [m["text"] for m in c.get("/chat", headers=Ha).json()["messages"] if m["kind"] == "event"]; ok(r.status_code == 200 and any(t.startswith("👑 dan a ouvert une légendaire :") for t in ev), "ouvrir une légendaire est annoncé")
own("dan", "Léo", "commune", 101); sec = card("Léo", "secrete"); r = c.post("/collection/unlock-secret", json={"card_id": sec.id}, headers=Hd); ev = [m["text"] for m in c.get("/chat", headers=Ha).json()["messages"] if m["kind"] == "event"]
ok(r.status_code == 200 and "🔮 dan a débloqué la carte secrète de Léo !" in ev, "débloquer une secrète est annoncé")
PR.bump(db, U("ben"), "open_packs", 500, maximum=True); db.commit(); c.get("/me", headers=Hb); ev = [m["text"] for m in c.get("/chat", headers=Ha).json()["messages"] if m["kind"] == "event"]
ok(any("ben a obtenu « Ouvreur de packs » niveau Diamant" in t for t in ev), "un niveau Diamant de succès est annoncé")
u1, u2 = U("ana"), U("ben"); real = S.standings
S.standings = lambda db_, key: [{"user_id": u1.id, "pseudo": "ana", "elo": 1120, "matches": 6, "wins": 5, "draws": 0, "losses": 1, "eligible": True, "rank": 1}, {"user_id": u2.id, "pseudo": "ben", "elo": 1080, "matches": 6, "wins": 3, "draws": 0, "losses": 3, "eligible": True, "rank": 2}]
S.close_season(db, "2026-06"); S.standings = real
ev = [m["text"] for m in c.get("/chat", headers=Ha).json()["messages"] if m["kind"] == "event"]; ok(any(t.startswith("🏆 ana a gagné la saison de juin 2026 !") and "🥈 ben" in t for t in ev), "le podium de saison est annoncé")
bm = next(m["id"] for m in c.get("/chat", headers=Hb).json()["messages"] if m["text"] == "Salut tout le monde !")
ok(c.delete(f"/chat/{bm}", headers=Ha).status_code == 404 and c.delete(f"/chat/{bm}", headers=Hb).status_code == 200, "on supprime ses messages, pas ceux des autres")
time.sleep(1.6); c.post("/chat", json={"text": "à supprimer"}, headers=Hb); did = next(m["id"] for m in c.get("/chat", headers=Hb).json()["messages"] if m["text"] == "à supprimer")
ok(c.post("/admin/chat-delete", json={"id": did}).status_code == 403 and c.post("/admin/chat-delete", json={"id": did}, headers=A).status_code == 200, "l'administrateur supprime un message (403 sans clé)")
ok(c.post("/admin/chat-mute", json={"pseudo": "ben", "hours": 2}, headers=A).status_code == 200 and c.post("/chat", json={"text": "muet ?"}, headers=Hb).status_code == 403 and c.get("/chat", headers=Hb).json()["muted_until"], "un joueur muet ne peut plus écrire mais lit")
ok(c.post("/admin/chat-unmute", json={"pseudo": "ben"}, headers=A).status_code == 200 and (time.sleep(1.6), c.post("/chat", json={"text": "me revoilà"}, headers=Hb).status_code)[1] == 200, "redonner la parole fonctionne")
ok(c.post("/admin/chat-mute", json={"pseudo": "ben", "hours": 0}, headers=A).status_code == 422 and c.post("/admin/chat-mute", json={"pseudo": "inconnu", "hours": 1}, headers=A).status_code == 404 and c.post("/admin/chat-delete", json={"id": 999999}, headers=A).status_code == 404, "durée absurde : 422 ; inconnus : 404")

print("3) ÉCHANGES DE CARTES")
for p in ("ana", "ben"): own(p, "Théo", "commune", 1)
own("ana", "Hugo", "rare", 3); own("ben", "Mathis", "commune", 2); own("ben", "Enzo", "rare", 1); own("ana", "Mathis", "commune", 1)
X, Y, Z = card("Hugo", "rare"), card("Mathis", "commune"), card("Enzo", "rare")
sw = lambda H, to, g, w: c.post("/swaps", json={"to": to, "give_card_id": g.id, "want_card_id": w.id}, headers=H)
dl = c.get("/swaps/doubles/ben", headers=Ha).json(); ok(dl and "Mathis" in {x["player_name"] for x in dl} and all(x["quantity"] >= 2 for x in dl), "on voit les doublons de ben")
ok(sw(Ha, "ana", X, Y).status_code == 400 and sw(Ha, "inconnu", X, Y).status_code == 404 and sw(Ha, "ben", X, X).status_code == 400, "refusés : avec soi-même, joueur inconnu, même carte")
ok(sw(Ha, "ben", X, Z).status_code == 400 and "pas cette carte en double" in sw(Ha, "ben", X, Z).json()["detail"], "refusé : carte que ben n'a pas en double")
ok(sw(Ha, "ben", card("Théo", "commune"), Y).status_code == 400, "refusé : donner une carte qu'on n'a qu'en 1 exemplaire")
tp = Player(name="Vainqueur (test)", poste="TROPHEE"); db.add(tp); db.flush(); tc = Card(player_id=tp.id, tier=Tier.saison, vitesse=0, tir=0); db.add(tc); db.flush(); db.add(OwnedCard(user_id=ua, card_id=tc.id, quantity=2)); db.commit()
ok(sw(Ha, "ben", tc, Y).status_code == 400 and "trophées" in sw(Ha, "ben", tc, Y).json()["detail"], "refusé : un trophée de saison")
r = sw(Ha, "ben", X, Y); sid = r.json()["id"]; ok(r.status_code == 200 and sw(Ha, "ben", X, Y).status_code == 400, "proposition ouverte ; la même une 2e fois refusée")
ma, mb = c.get("/swaps", headers=Ha).json(), c.get("/swaps", headers=Hb).json()
ok(len(ma["outgoing"]) == 1 and len(mb["incoming"]) == 1 and mb["incoming"][0]["from"] == "ana" and mb["incoming"][0]["give"]["player_name"] == "Hugo" and mb["incoming"][0]["want"]["player_name"] == "Mathis", "ana la voit envoyée, ben la voit reçue avec les deux cartes")
ok(c.post(f"/swaps/{sid}/accept", headers=Ha).status_code == 404 and c.post(f"/swaps/{sid}/accept").status_code == 401, "seul ben peut accepter")
def q(p, n, t): fresh(); o = db.query(OwnedCard).filter_by(user_id=U(p).id, card_id=card(n, t).id).first(); return o.quantity if o else 0
r = c.post(f"/swaps/{sid}/accept", headers=Hb); ok(r.status_code == 200 and q("ana", "Hugo", "rare") == 2 and q("ben", "Hugo", "rare") == 1 and q("ben", "Mathis", "commune") == 1 and q("ana", "Mathis", "commune") == 2, "accepté : les quantités sont échangées, chacun garde au moins 1 exemplaire")
ok(c.post(f"/swaps/{sid}/accept", headers=Hb).status_code == 400, "accepter deux fois : refusé")
rec = c.get("/swaps", headers=Hc).json()["recent"]; ok(rec and rec[0]["from"] == "ana", "l'échange figure dans « derniers échanges du club »")
ev = [m["text"] for m in c.get("/chat", headers=Ha).json()["messages"] if m["kind"] == "event"]; ok(any("ana et ben ont échangé des cartes : Hugo (Rare) contre Mathis (Commune)" in t for t in ev), "annonce dans le chat avec les raretés")
own("ben", "Mathis", "commune", 2); own("ana", "Hugo", "rare", 2); sid2 = sw(Ha, "ben", X, Y).json()["id"]; ok(c.post(f"/swaps/{sid2}/decline", headers=Hb).status_code == 200 and c.post(f"/swaps/{sid2}/accept", headers=Hb).status_code == 400, "ben refuse : la proposition se ferme")
sid3 = sw(Ha, "ben", X, Y).json()["id"]; ok(c.delete(f"/swaps/{sid3}", headers=Hb).status_code == 404 and c.delete(f"/swaps/{sid3}", headers=Ha).status_code == 200, "seul ana peut annuler")
sid4 = sw(Ha, "ben", X, Y).json()["id"]; own("ana", "Hugo", "rare", 1); r = c.post(f"/swaps/{sid4}/accept", headers=Hb); ok(r.status_code == 400 and "plus cette carte en double" in r.json()["detail"], "doublon disparu au moment d'accepter : refusé proprement")
c.delete(f"/swaps/{sid4}", headers=Ha); own("ana", "Hugo", "rare", 3); sid5 = sw(Ha, "ben", X, Y).json()["id"]; s5 = db.get(SW.CardSwap, sid5); s5.created_at = datetime.utcnow() - timedelta(days=8); db.commit(); c.get("/swaps", headers=Hb)
ok(c.post(f"/swaps/{sid5}/accept", headers=Hb).status_code == 400 and db.get(SW.CardSwap, sid5).status == "expired", "une proposition de plus de 7 jours expire")
names = ("Lucas", "Tom", "Rayan", "Yanis", "Maxime", "Antoine")
for nm in names: own("ana", nm, "commune", 2); own("ben", nm, "rare", 2)
n_ok = sum(1 for nm in names if sw(Ha, "ben", card(nm, "commune"), card(nm, "rare")).status_code == 200)
ok(n_ok == 5, f"au plus {SW.MAX_OPEN} propositions ouvertes à la fois : {n_ok} acceptées, la 6e refusée")

print("4) PRONOSTICS")
now = PN.now_paris(); fut = now + timedelta(days=2)
mid1 = c.post("/admin/add-upcoming-match", json={"date": fut.strftime("%Y-%m-%d") + " 15:00", "opponent": "Rivaux FC", "location": "Stade"}, headers=A).json()["id"]
past = c.post("/admin/add-upcoming-match", json={"date": (now - timedelta(days=1)).strftime("%Y-%m-%d") + " 20:00", "opponent": "Passé FC"}, headers=A).json()["id"]
nt = c.post("/admin/add-upcoming-match", json={"date": fut.strftime("%Y-%m-%d"), "opponent": "SansHeure"}, headers=A).json()["id"]
lst = {m["id"]: m for m in c.get("/prono", headers=Ha).json()["matches"]}; ok(lst[mid1]["open"] and not lst[past]["open"] and lst[nt]["closes_at"].endswith("T12:00:00"), "match à venir ouvert ; passé fermé ; sans heure : fermeture à 12:00")
bet = lambda H, m, a, b, s: c.post("/prono", json={"upcoming_id": m, "score_us": a, "score_them": b, "stake": s}, headers=H)
for p in ("ana", "ben", "cléo", "dan"): setc(p, 100)
ok(bet(Ha, past, 1, 0, 5).status_code == 400 and bet(Ha, mid1, 1, 0, 51).status_code == 422 and bet(Ha, mid1, 31, 0, 5).status_code == 422 and bet(Ha, mid1, 1, 0, 0).status_code == 422 and bet(Ha, "inconnu", 1, 0, 5).status_code == 404, "refusés : match fermé, mise hors 1-50, score > 30, match inconnu")
setc("ana", 3); ok(bet(Ha, mid1, 2, 1, 10).status_code == 400, "refusé : pas assez de crédits"); setc("ana", 100)
bet(Ha, mid1, 2, 1, 10); ok(credits("ana") == 90, "mise de 10 : 100 → 90")
bet(Ha, mid1, 2, 1, 20); ok(credits("ana") == 80, "mise changée à 20 : l'ancienne rendue puis la nouvelle prise")
ok(c.delete(f"/prono/{mid1}", headers=Ha).status_code == 200 and credits("ana") == 100 and c.delete(f"/prono/{mid1}", headers=Ha).status_code == 404, "annuler rend la mise")
bet(Ha, mid1, 2, 1, 10); bet(Hb, mid1, 1, 0, 20); bet(Hc, mid1, 0, 2, 10); bet(Hd, mid1, 3, 0, 10)
ok(c.post("/admin/prono-bonus", json={"upcoming_id": mid1, "bonus": 10}).status_code == 403 and c.post("/admin/prono-bonus", json={"upcoming_id": mid1, "bonus": 10}, headers=A).status_code == 200, "bonus du club (403 sans clé)")
info = {m["id"]: m for m in c.get("/prono", headers=Ha).json()["matches"]}[mid1]; ok(info["pool"] == 60 and info["bets"] == 4, f"cagnotte {info['pool']} (50 de mises + 10 de bonus)")
before = {p: credits(p) for p in ("ana", "ben", "cléo", "dan")}
rm = c.post("/admin/record-match", json={"date": fut.strftime("%Y-%m-%d"), "opponent": "Rivaux FC", "score_us": 2, "score_them": 1}, headers=A); ok(rm.status_code == 200, "match enregistré (2-1)" + ("" if rm.status_code == 200 else " : " + rm.text[:150]))
ga = {p: credits(p) - before[p] for p in before}; ok(ga == {"ana": 42, "ben": 12, "cléo": 0, "dan": 6}, f"cagnotte 60 : exact 70 % = 42 ; bon résultat 18 partagés (ben 12, dan 6) ; cléo 0 : {ga}")
mb_ = {b["upcoming_id"]: b for b in c.get("/prono/mine", headers=Ha).json()}[mid1]; ok(mb_["status"] == "won" and mb_["payout"] == 42 and mb_["exact"] and mb_["result"] == "2-1", "« gagné +42, score exact »")
ok({b["upcoming_id"]: b for b in c.get("/prono/mine", headers=Hc).json()}[mid1]["status"] == "lost", "cléo : « perdu »")
rk = c.get("/prono/ranking").json(); ok(rk[0]["pseudo"] == "ana" and rk[0]["net"] == 32 and rk[0]["exact"] == 1, "classement des pronostiqueurs : ana n°1 (+32)")
ev = [m["text"] for m in c.get("/chat", headers=Ha).json()["messages"] if m["kind"] == "event"]; ok(any("ana a trouvé le score exact" in t and "2-1" in t for t in ev), "score exact annoncé dans le chat")
ok(db.get(UpcomingMatch, mid1) is None and PR._counter(db, U("ana").id, "prono_exact") == 4 and PR._counter(db, U("ben").id, "prono_placed") == 1, "match retiré des « à venir » ; compteurs à jour")
m2 = c.post("/admin/add-upcoming-match", json={"date": fut.strftime("%Y-%m-%d") + " 16:00", "opponent": "Rembourse FC"}, headers=A).json()["id"]; setc("ana", 100); setc("ben", 100)
bet(Ha, m2, 1, 0, 30); bet(Hb, m2, 0, 0, 10); c.post("/admin/record-match", json={"date": fut.strftime("%Y-%m-%d"), "opponent": "Rembourse FC", "score_us": 0, "score_them": 3}, headers=A)
ok(credits("ana") == 100 and credits("ben") == 100 and {b["upcoming_id"]: b for b in c.get("/prono/mine", headers=Ha).json()}[m2]["status"] == "refunded", "personne n'a le bon résultat : tout le monde est remboursé")
m3 = c.post("/admin/add-upcoming-match", json={"date": fut.strftime("%Y-%m-%d") + " 17:00", "opponent": "Annulé FC"}, headers=A).json()["id"]; bet(Ha, m3, 1, 1, 25); b0 = credits("ana")
c.post("/admin/delete-upcoming-match", json={"upcoming_id": m3}, headers=A); ok(credits("ana") == b0 + 25, "match supprimé sans résultat : remboursement")
m4 = c.post("/admin/add-upcoming-match", json={"date": fut.strftime("%Y-%m-%d") + " 18:00", "opponent": "Seul FC"}, headers=A).json()["id"]; setc("ben", 100); bet(Hb, m4, 2, 2, 40)
c.post("/admin/record-match", json={"date": fut.strftime("%Y-%m-%d"), "opponent": "Seul FC", "score_us": 1, "score_them": 1}, headers=A); ok(credits("ben") == 100, "un seul parieur avec le bon résultat reprend sa mise")
ok(c.get("/prono").status_code == 401, "sans compte : 401")

from app import battlepass as BPX
db.expire_all(); pa = db.query(BPX.PassProgress).filter_by(user_id=U("ana").id).first(); pb = db.query(BPX.PassProgress).filter_by(user_id=U("ben").id).first()
ok(pa is not None and pa.points >= 75 and pb is not None and pb.points >= 15, f"les pronostics (15, score exact 60) et les échanges de cartes (15) rapportent des points de Pass : ana {pa.points if pa else 0}, ben {pb.points if pb else 0}")
print("5) SUPPRESSION DE COMPTE")
uid = U("dan").id; c.post("/admin/delete-user", json={"pseudo": "dan"}, headers=A); fresh()
from app import prono as PN2
ok(db.query(CH.ChatMessage).filter_by(user_id=uid).count() == 0 and db.query(PN2.PronoBet).filter_by(user_id=uid).count() == 0 and db.query(CO.UserCosmetics).filter_by(user_id=uid).count() == 0, "supprimer un compte supprime ses messages, pronostics et titre")
print(); print("BILAN (titres, chat, échanges, pronostics) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
