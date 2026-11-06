"""
Test : cartes spéciales du vendredi, « la plus utilisée » par groupe de rareté (commune, rare, épique, légendaire, édition limitée),
meilleur buteur et meilleur passeur inchangés, notification et classement de la semaine ; notes des éditions limitées à 85.
Lancé par tests/run_tests.py.
"""
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import weekly as WK, game_logic as GL, push
from app.models import User, Card, Player, Tier, Duel, CardUsage
c = TestClient(app); FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
card = lambda n, t: db.query(Card).join(Player).filter(Player.name == n, Card.tier == Tier(t)).first()
special = lambda n: card(n, "speciale")

print("1) NOTES DES ÉDITIONS LIMITÉES")
ok(GL.CARD_NOTE["halloween"] == 85 and GL.CARD_NOTE["noel"] == 85 and GL.CARD_NOTE["rare"] == 85, "Halloween et Noël : note 85, comme la rare")
ok(all(GL.CARD_NOTE[s] == 85 for s in GL.CUSTOM_EDITION_SLOTS), "les 12 éditions personnalisées (ed1 à ed12) : note 85 aussi")
ok(GL.card_note(db.query(Player).first(), "ed5") == 85, "card_note d'une édition personnalisée : 85")
ok(GL.TIER_FAN_BONUS["halloween"] == 0.08 and GL.TIER_FAN_BONUS["ed1"] == 0.08 and GL.TIER_MASCOT_BONUS["noel"] == 0.08 and GL.TIER_MASCOT_BONUS["ed1"] == 0.08, "Fan et mascotte d'édition limitée : +8 % (Halloween, Noël, éditions personnalisées)")

print("2) GROUPES DE RARETÉ")
ok([WK.tier_group(t) for t in ("commune", "rare", "epique", "legendaire", "halloween", "noel", "ed3")] == ["commune", "rare", "epique", "legendaire", "edition", "edition", "edition"], "chaque rareté va dans son groupe ; Halloween, Noël et ed3 dans « édition limitée »")
ok(all(WK.tier_group(t) is None for t in ("gold", "secrete", "speciale", "saison", None)), "gold, secrète, spéciale et trophée de saison sont ignorées")

# des cartes de toutes les raretés utiles (la base de test n'a que des communes et des rares)
for n in ("Lucas", "Hugo", "Léo", "Enzo", "Mathis", "Nathan", "Tom"):
    p = db.query(Player).filter_by(name=n).first()
    for t in ("epique", "legendaire", "halloween", "noel", "ed3", "secrete", "gold"):
        if card(n, t) is None: db.add(Card(player_id=p.id, tier=Tier(t), vitesse=0, tir=0))
u1 = User(pseudo="ana", password_hash="x", credits=0); u2 = User(pseudo="bob", password_hash="x", credits=0); db.add_all([u1, u2]); db.commit()

NOW = datetime.utcnow()
def use(name, tier, n=1):
    for _ in range(n): db.add(CardUsage(at=NOW, source="club", user_id=u1.id, player_name=name, tier=tier))
def duel(ch, de, events):
    side = lambda ps: {"players": [{"player": n, "tier": t} for n, t in ps]}
    db.add(Duel(challenger_id=u1.id, defender_id=u2.id, stake=0, formation_challenger="1-2-1", formation_defender="1-2-1", score_challenger=0, score_defender=0,
                elo_challenger_before=1000, elo_defender_before=1000, elo_challenger_after=1000, elo_defender_after=1000, created_at=NOW,
                lineups_json=json.dumps({"challenger": side(ch), "defender": side(de)}), events_json=json.dumps(events)))
goal = lambda s, a=None: {"kind": "goal", "side": "challenger", "scorer": s, "assist": a}
use("Lucas", "commune", 3); use("Hugo", "commune", 1)                     # commune : Lucas 3, Hugo 2 (1 ici + 1 en 1v1)
duel([("Hugo", "rare"), ("Nathan", "rare")], [("Hugo", "rare"), ("Léo", "ed3")], [goal("Tom", "Enzo"), goal("Tom", "Enzo")])
duel([("Lucas", "legendaire")], [("Mathis", "secrete")], [goal("Nathan")])
use("Nathan", "rare", 1)                                                  # rare : Hugo 2, Nathan 2 (puis 3 avec le dernier match)
use("Léo", "ed3", 3); use("Enzo", "halloween"); use("Enzo", "noel")       # édition : Léo 4 (ed3), Enzo 2 (Halloween + Noël)
use("Mathis", "secrete", 10); use("Mathis", "gold", 10); use("Tom", "speciale", 9); use("Tom", "saison", 9)   # raretés ignorées
duel([("Nathan", "rare")], [("Hugo", "commune")], [])                    # Nathan rare 3 : il passe devant Hugo en rare
db.commit()

print("3) ATTRIBUTION")
START, END = NOW - timedelta(hours=1), NOW + timedelta(hours=1)
groups = {}; used, goals, assists, nd = WK.window_stats(db, START, END, by_group=groups)
ok(nd == 3 and used["Mathis"] == 21 and used["Hugo"] == 4, "toutes raretés confondues, Mathis (secrète et gold) serait le plus utilisé : 21 utilisations")
ok(groups["commune"]["Hugo"] == 2 and groups["rare"]["Hugo"] == 2 and groups["edition"]["Enzo"] == 2 and groups["edition"]["Léo"] == 4, "les utilisations sont rangées dans le groupe de la rareté de la carte (1v1 et défi du club)")
dry = WK.run_weekly_specials(db, START, END, dry_run=True)
ok(dry["awards"] and special("Lucas") is None, "aperçu : rien n'est créé")
SENT = []; real_notify = push.notify_all; push.notify_all = lambda db, kind, title, body, **kw: SENT.append(body) or 0
rep = WK.run_weekly_specials(db, START, END)
push.notify_all = real_notify
aw = [(a["category"], a["group"], a["player"]) for a in rep["awards"]]
ok(aw == [("most_used", "commune", "Lucas"), ("most_used", "rare", "Nathan"), ("most_used", "legendaire", "Lucas"), ("most_used", "edition", "Léo"),
          ("top_scorer", None, "Tom"), ("top_assister", None, "Enzo")], "un gagnant par groupe, puis buteur et passeur : %s" % aw)
ok(not any(a["group"] == "epique" for a in rep["awards"]), "groupe épique sans aucune utilisation : pas de carte")
ok(all(a["player"] != "Mathis" for a in rep["awards"]), "les cartes secrètes, gold, spéciales et de saison ne font gagner personne")
ok(next(a for a in rep["awards"] if a["group"] == "commune")["count"] == 3, "commune : Lucas (3) devant Hugo (2), ses cartes rares ne comptent pas dans la commune")
ok(next(a for a in rep["awards"] if a["group"] == "edition")["player"] == "Léo", "édition limitée : les éditions personnalisées comptent (Léo, ed3)")
ok(goals == {"Tom": 2, "Nathan": 1} and assists == {"Enzo": 2}, "meilleur buteur et meilleur passeur : toutes raretés confondues, comme avant")
db.expire_all()
ok(special("Lucas") is not None and special("Lucas").note == GL.SPECIAL_BASE_NOTE + 1, "Lucas, n°1 commune et légendaire : sa spéciale est créée puis +1 (note 81)")
ok(all(special(n) is not None and special(n).note == GL.SPECIAL_BASE_NOTE for n in ("Nathan", "Léo", "Tom", "Enzo")), "les autres gagnants : spéciale créée à 80")
ok(special("Hugo") is None and special("Mathis") is None, "aucune spéciale pour les non-gagnants")
lab = {a["group"]: a["label"] for a in rep["awards"]}
ok(lab["rare"] == "la plus utilisée (rare)" and lab["edition"] == "la plus utilisée (édition limitée)" and lab[None] in ("meilleur buteur", "meilleur passeur"), "le rapport indique le groupe de rareté")
ok(len(SENT) == 1 and SENT[0].startswith("Plus utilisées : Lucas (commune), Nathan (rare), Lucas (légendaire), Léo (édition limitée) · Meilleur buteur : Tom · Meilleur passeur : Enzo"), "une seule notification lisible : %s" % SENT)
rep2 = WK.run_weekly_specials(db, START, END); db.expire_all()
ok(special("Lucas").note == GL.SPECIAL_BASE_NOTE + 3, "une semaine plus tard (mêmes gagnants) : Lucas regagne +2")

print("4) CLASSEMENT DE LA SEMAINE")
wk = c.get("/duel/card-stats", params={"scope": "week", "limit": 5}).json()
g = {x["group"]: x for x in wk["most_used_groups"]}
ok([x["group"] for x in wk["most_used_groups"]] == ["commune", "rare", "epique", "legendaire", "edition"] and g["edition"]["label"] == "édition limitée", "un classement par groupe de rareté, dans l'ordre")
ok([(e["card"]["player_name"], e["card"]["tier"], e["count"]) for e in g["commune"]["cards"]] == [("Lucas", "commune", 3), ("Hugo", "commune", 2)], "commune : Lucas 3, Hugo 2 (ses rares ne comptent pas ici)")
ok([e["card"]["tier"] for e in g["rare"]["cards"]] == ["rare", "rare"] and g["rare"]["cards"][0]["card"]["player_name"] == "Nathan", "rare : Nathan en tête, et la carte affichée est bien la rare")
ok(g["epique"]["cards"] == [] and g["edition"]["cards"][0]["card"]["tier"] == "ed3", "épique vide ; édition limitée : la carte ed3 de Léo est affichée")
ok(wk["top_scorers"][0]["card"]["player_name"] == "Tom" and wk["top_assisters"][0]["card"]["player_name"] == "Enzo", "buteurs et passeurs : inchangés")
ok("most_used" in c.get("/duel/card-stats").json(), "le classement de tous les temps garde sa forme")
print("BILAN (spéciales par rareté) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
