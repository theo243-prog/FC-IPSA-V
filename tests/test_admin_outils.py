"""
Test : outils d'administration. Cartes libres (événements, équipements, fans, mascottes, stades, dans n'importe quelle rareté),
bandeau du site. Lancé par tests/run_tests.py.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import game_logic as GL, duel_engine as DE
from app.models import Card, Player, Tier
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal(); A = {"X-Admin-Key": "k"}
card = lambda n: db.query(Card).join(Player).filter(Player.name == n).first()

print("1) CARTES LIBRES")
cards = [{"name": "Blessure à l'entraînement — Intel", "kind": "evenement", "tier": "gold", "photo_url": "/photos/intel.webp"},
         {"name": "Gourde dorée", "kind": "équipement", "tier": "épique"}, {"name": "Les Ultras du Nord", "kind": "fan", "tier": "rare"},
         {"name": "Petit Loup", "kind": "mascotte", "tier": "commune"}, {"name": "Stade du Moulin", "kind": "stade", "tier": "commune"},
         {"name": "Soirée de fin de saison", "kind": "evenement", "tier": "legendaire"}]
ok(c.post("/admin/create-free-cards", json={"cards": cards}).status_code == 403, "il faut la clé admin")
r = c.post("/admin/create-free-cards", json={"cards": cards}, headers=A)
ok(r.status_code == 200 and len(r.json()["cards_created"]) == 6, "6 cartes libres créées")
db.expire_all()
ev, gd, fan, wolf, st, party = (card(x["name"]) for x in cards)
ok(ev.tier == Tier.gold and ev.player.poste == "MOMENT" and GL.card_kind(ev.player) == "moment" and ev.player.photo_url == "/photos/intel.webp", "événement en gold : une carte souvenir (MOMENT) avec son image")
ok(party.tier == Tier.legendaire and GL.card_kind(party.player) == "moment", "un événement peut être de n'importe quelle rareté (ici légendaire)")
ok(gd.tier == Tier.epique and GL.card_kind(gd.player) == "equipement" and GL.equipment_fatigue_reduction([gd]) == GL.EQUIPMENT_FATIGUE_REDUCTION["epique"], "équipement épique : réduit la fatigue comme les autres")
ok(GL.card_kind(fan.player) == "fan" and GL.card_kind(wolf.player) == "mascotte" and GL.card_kind(st.player) == "stade", "fan, mascotte et stade reconnus")
ok(GL.get_display_note(ev.player, "gold", ev) is None, "un événement n'a pas de note (il ne joue pas)")
n0 = db.query(Card).count()
bad = [({"name": "Gourde dorée", "kind": "evenement", "tier": "gold"}, "existe déjà"), ({"name": "X1", "kind": "voiture", "tier": "gold"}, "type"),
       ({"name": "X2", "kind": "evenement", "tier": "platine"}, "rareté"), ({"name": "X3", "kind": "equipement", "tier": "gold"}, "équipement"),
       ({"name": "  ", "kind": "evenement", "tier": "gold"}, "nom")]
for e, word in bad:
    r = c.post("/admin/create-free-cards", json={"cards": [{"name": "Valide", "kind": "evenement", "tier": "rare"}, e]}, headers=A)
    ok(r.status_code == 400 and word in r.json()["detail"], "refus (%s) : %s" % (word, r.json().get("detail")))
db.expire_all(); ok(db.query(Card).count() == n0 and card("Valide") is None, "tout ou rien : aucune carte créée après un refus")
log = c.get("/admin/log", headers=A).json()
ok(any("carte(s) libre(s)" in (x.get("action") or "") for x in log), "l'action est au journal de l'administration")

print("2) BANDEAU DU SITE")
ok(c.get("/site-banner").json()["text"] is None, "pas de bandeau au départ")
ok(c.post("/admin/site-banner", json={"text": "Match dimanche 15h !"}).status_code == 403, "il faut la clé admin")
r = c.post("/admin/site-banner", json={"text": "Match  dimanche 15h !", "style": "fete"}, headers=A); b = c.get("/site-banner").json()
ok(r.status_code == 200 and b["text"] == "Match dimanche 15h !" and b["style"] == "fete" and b["id"], "le bandeau s'affiche pour tous, sans compte")
c.post("/admin/site-banner", json={"text": "Nouveau message", "style": "bizarre"}, headers=A); b2 = c.get("/site-banner").json()
ok(b2["id"] != b["id"] and b2["style"] == "info", "un nouveau message a un nouvel identifiant (il réapparaît chez ceux qui l'avaient fermé) ; couleur inconnue : info")
ok(c.post("/admin/site-banner", json={"text": "x" * 301}, headers=A).status_code == 400, "plus de 300 caractères : refusé")
c.post("/admin/site-banner", json={"text": "caché", "enabled": False}, headers=A); ok(c.get("/site-banner").json()["text"] is None, "case décochée : plus de bandeau")
c.post("/admin/site-banner", json={"text": ""}, headers=A); ok(c.get("/site-banner").json()["text"] is None, "message vide : plus de bandeau")

print("BILAN (outils d'administration) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
