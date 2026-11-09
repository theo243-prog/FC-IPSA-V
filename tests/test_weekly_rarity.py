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
ok(GL.TIER_FAN_BONUS["halloween"] == 0.015 and GL.TIER_FAN_BONUS["ed1"] == 0.015 and GL.LOUP_CREDITS_BY_TIER["noel"] == 2 and GL.LOUP_CREDITS_BY_TIER["ed1"] == 2, "Fan d'édition limitée : +1,5 %, Loup d'édition : 2 crédits par match (Halloween, Noël, éditions personnalisées)")

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

print("3) ATTRIBUTION (nouvelle règle)")
from app.chat import ChatMessage
START, END = NOW - timedelta(hours=1), NOW + timedelta(hours=1)
groups = {}; used, goals, assists, nd = WK.window_stats(db, START, END, by_group=groups)
ok(nd == 3 and used["Mathis"] == 21 and used["Hugo"] == 4, "toutes raretés confondues, Mathis (secrète et gold) serait le plus utilisé : 21 utilisations")
ok(groups["commune"]["Hugo"] == 2 and groups["rare"]["Hugo"] == 2 and groups["edition"]["Enzo"] == 2 and groups["edition"]["Léo"] == 4, "les utilisations sont rangées dans le groupe de la rareté de la carte (1v1 et défi du club)")
ok(goals == {"Tom": 2, "Nathan": 1} and assists == {"Enzo": 2}, "meilleur buteur et meilleur passeur : toutes raretés confondues, comme avant")
ok(GL.SPECIAL_BASE_NOTE == 80 and GL.SPECIAL_MAX_NOTE == 90, "constantes : création à 80, plafond à 90")
dry = WK.run_weekly_specials(db, START, END, dry_run=True)
ok(dry["created"] == ["Lucas", "Nathan", "Léo", "Tom", "Enzo"] and special("Lucas") is None and db.query(ChatMessage).count() == 0, "simulation : le rapport annonce les créations, mais rien n'est créé ni annoncé")
SENT = []; real_notify = push.notify_all; push.notify_all = lambda db, kind, title, body, **kw: SENT.append(body) or 0
rep = WK.run_weekly_specials(db, START, END)
push.notify_all = real_notify
ok(dry["awards"] == rep["awards"], "la simulation donne exactement les mêmes actions que l'attribution réelle")
aw = [(a["category"], a["group"], a["player"]) for a in rep["awards"]]
ok(aw == [("most_used", "commune", "Lucas"), ("most_used", "rare", "Nathan"), ("most_used", "legendaire", "Lucas"), ("most_used", "edition", "Léo"),
          ("top_scorer", None, "Tom"), ("top_assister", None, "Enzo")], "une entrée par catégorie qui a des points (épique vide : rien) : %s" % aw)
ok(all(a["player"] != "Mathis" for a in rep["awards"]), "les cartes secrètes, gold, spéciales et de saison ne font gagner personne")
leg = next(a for a in rep["awards"] if a["group"] == "legendaire")
ok([x["action"] for x in leg["actions"]] == ["plus_one"] and leg["plus_one_note"] == 81 and leg["created"] is None, "légendaire : Lucas, dont la carte vient d'être créée (commune), prend le +1 ; seul au classement, aucune création")
db.expire_all()
ok(special("Lucas").note == 81 and all(special(n).note == 80 for n in ("Nathan", "Léo", "Tom", "Enzo")), "Lucas : créée puis +1 la même semaine (81) ; les autres : créées à 80")
ok(special("Hugo") is None and special("Mathis") is None, "aucune spéciale pour les autres")
ok(rep["created"] == ["Lucas", "Nathan", "Léo", "Tom", "Enzo"] and rep["plus_one"] == [{"player": "Lucas", "note": 81}], "résumé du rapport : 5 créations, 1 « +1 »")
lab = {a["group"]: a["label"] for a in rep["awards"]}
ok(lab["rare"] == "la plus utilisée (rare)" and lab["edition"] == "la plus utilisée (édition limitée)", "le rapport indique le groupe de rareté")
ok(len(SENT) == 1 and SENT[0].startswith("🆕 Nouvelles cartes : Lucas, Nathan, Léo, Tom, Enzo · ⬆️ +1 : Lucas (81)"), "une seule notification lisible : %s" % SENT)
msg = db.query(ChatMessage).order_by(ChatMessage.id.desc()).first()
ok(msg is not None and msg.kind == "event" and msg.user_id is None and "Nouvelles cartes : Lucas, Nathan" in msg.text, "annonce dans le chat, au nom du jeu")

print("4) CLASSEMENT DE LA SEMAINE ET PRÉVISION")
wk = c.get("/duel/card-stats", params={"scope": "week", "limit": 5}).json()
g = {x["group"]: x for x in wk["most_used_groups"]}
ok([x["group"] for x in wk["most_used_groups"]] == ["commune", "rare", "epique", "legendaire", "edition"] and g["edition"]["label"] == "édition limitée", "un classement par groupe de rareté, dans l'ordre")
ok([(e["card"]["player_name"], e["card"]["tier"], e["count"]) for e in g["commune"]["cards"]] == [("Lucas", "commune", 3), ("Hugo", "commune", 2)], "commune : Lucas 3, Hugo 2 (ses rares ne comptent pas ici)")
ok(g["epique"]["cards"] == [] and g["edition"]["cards"][0]["card"]["tier"] == "ed3", "épique vide ; édition limitée : la carte ed3 de Léo est affichée")
ok(wk["top_scorers"][0]["card"]["player_name"] == "Tom" and wk["top_assisters"][0]["card"]["player_name"] == "Enzo", "buteurs et passeurs : inchangés")
fc = {(f["category"], f["group"]): f for f in wk["forecast"]}
ok(fc[("most_used", "commune")]["plus_one"] == "Lucas" and fc[("most_used", "commune")]["plus_one_note"] == 82 and fc[("most_used", "commune")]["created"] == "Hugo" and fc[("most_used", "commune")]["created_rank"] == 2,
   "prévision commune : +1 pour Lucas (82), carte créée pour Hugo (2e)")
ok(fc[("most_used", "legendaire")]["plus_one"] is None and fc[("most_used", "legendaire")]["first_skipped"]["reason"] == "déjà +1 cette semaine", "prévision légendaire : Lucas a déjà son +1 (commune)")
ok(fc[("most_used", "rare")]["created"] is None and ("most_used", "epique") not in fc, "prévision rare : Hugo aura déjà la sienne, aucune création ; épique sans points : pas de prévision")
ok("most_used" in c.get("/duel/card-stats").json(), "le classement de tous les temps garde sa forme")
rep2 = WK.run_weekly_specials(db, START, END); db.expire_all()
ok([(f["plus_one"], f["created"]) for f in wk["forecast"]] == [(a["plus_one"], a["created"]) for a in rep2["awards"]], "la semaine suivante (mêmes classements), l'attribution suit exactement la prévision")
ok(special("Lucas").note == 82 and special("Hugo").note == 80 and all(special(n).note == 81 for n in ("Nathan", "Léo", "Tom", "Enzo")), "Lucas 82 (un seul +1 malgré 2 catégories), Hugo créée, les autres +1")

print("5) SCÉNARIOS DE LA RÈGLE")
P = {n: db.query(Player).filter_by(name=n).first() for n in ("Rayan", "Yanis", "Maxime", "Antoine", "Baptiste", "Théo", "Nolan", "Gabriel", "Clément", "Adrien", "Ethan", "Noah", "Valentin", "Kylian", "Romain")}
def spec(n, note):
    cd = special(n)
    if cd is None: db.add(Card(player_id=P[n].id, tier=Tier.speciale, vitesse=0, tir=0, note=note))
    else: cd.note = note
    db.commit()
def plan(*cats):
    return WK.plan_awards(db, [("most_used", g, [(P[n], 10 - i) for i, n in enumerate(names)]) for g, names in cats])
acts = lambda e: [(a["action"], a["player"]) for a in e["actions"]]
e = plan(("commune", ["Rayan", "Yanis"]))[0]
ok(acts(e) == [("created", "Rayan")] and e["plus_one"] is None, "1er sans carte : sa carte est créée, pas de +1, on s'arrête (le 2e n'est pas regardé)")
spec("Rayan", 80); e = plan(("commune", ["Rayan", "Yanis", "Maxime"]))[0]
ok(acts(e) == [("plus_one", "Rayan"), ("created", "Yanis")] and e["plus_one_note"] == 81 and e["created_rank"] == 2, "1er avec carte, 2e sans : +1 au 1er, création pour le 2e")
spec("Yanis", 84); e = plan(("commune", ["Rayan", "Yanis", "Maxime"]))[0]
ok(acts(e) == [("plus_one", "Rayan"), ("skipped", "Yanis"), ("created", "Maxime")] and special("Yanis").note == 84, "1er et 2e avec carte, 3e sans : +1 au 1er seulement, le 2e sauté sans rien, création pour le 3e")
spec("Maxime", 80); e = plan(("commune", ["Rayan", "Yanis", "Maxime"]))[0]
ok(acts(e) == [("plus_one", "Rayan"), ("skipped", "Yanis"), ("skipped", "Maxime")] and e["created"] is None, "tous en ont une : +1 au 1er, aucune création")
spec("Antoine", 90); e = plan(("commune", ["Antoine", "Baptiste"]))[0]
ok(acts(e) == [("skipped", "Antoine"), ("created", "Baptiste")] and "90" in e["actions"][0]["reason"], "plafond : à 90, pas de +1 (mais la création pour le suivant a lieu)")
spec("Antoine", 89); e = plan(("commune", ["Antoine"]))[0]
ok(e["plus_one_note"] == 90, "89 → 90 : le dernier +1 possible")
spec("Antoine", 93); WK._apply(db, plan(("commune", ["Antoine", "Baptiste"]))); db.commit(); db.expire_all()
ok(special("Antoine").note == 93 and special("Baptiste").note == 80, "une spéciale déjà au-dessus de 90 n'est jamais baissée (93 reste 93)")
e1, e2 = plan(("commune", ["Rayan"]), ("rare", ["Rayan", "Théo"]))
ok(acts(e1) == [("plus_one", "Rayan")] and acts(e2) == [("skipped", "Rayan"), ("created", "Théo")] and e2["actions"][0]["reason"] == "déjà +1 cette semaine", "1er de deux catégories : un seul +1 (le premier), le second est sauté ; la création continue")
e1, e2, e3 = plan(("commune", ["Nolan"]), ("rare", ["Rayan", "Nolan", "Gabriel"]), ("epique", ["Nolan"]))
ok(acts(e1) == [("created", "Nolan")] and acts(e2) == [("plus_one", "Rayan"), ("skipped", "Nolan"), ("created", "Gabriel")] and acts(e3) == [("plus_one", "Nolan")],
   "carte créée dans une catégorie : déjà possédée plus loin (sautée en rare, +1 en épique où il est 1er)")
ok(WK.plan_awards(db, [("most_used", "commune", []), ("top_scorer", None, [])]) == [], "classement vide : aucune action")
seven = WK.plan_awards(db, [("most_used", g, [(P[n], 5), (P["Noah"], 1)]) for g, n in zip(("commune", "rare", "epique", "legendaire", "edition"), ("Clément", "Adrien", "Ethan", "Valentin", "Gabriel"))]
                       + [("top_scorer", None, [(P["Kylian"], 3), (P["Noah"], 1)]), ("top_assister", None, [(P["Romain"], 3), (P["Noah"], 1)])])
created = [x["created"] for x in seven if x["created"]]
ok(all(sum(a["action"] == "created" for a in x["actions"]) <= 1 for x in seven) and len(created) == 7 and len(set(created)) == 7, "au plus une création par catégorie : 7 au maximum par semaine (%s)" % created)
ok(sum(1 for x in seven if x["plus_one"]) <= 7, "et au plus 7 « +1 »")

print("6) DOUBLE EXÉCUTION")
from app.models import JobRun
db.query(JobRun).filter_by(name=WK.JOB_NAME).delete(); db.commit()
ok(WK.check_and_run(db, NOW) is None, "première fois : le créneau est seulement noté")
r1 = WK.check_and_run(db, NOW + timedelta(days=7)); db.expire_all()
notes = {cd.player.name: cd.note for cd in db.query(Card).filter_by(tier=Tier.speciale).all()}
r2 = WK.check_and_run(db, NOW + timedelta(days=7)); db.expire_all()
r3 = WK.check_and_run(db, NOW + timedelta(days=7, minutes=5)); db.expire_all()
ok(r1 is not None and (r1["created"] or r1["plus_one"]) and r2 is None and r3 is None, "la tâche tourne une fois par créneau (deuxième et troisième appels : rien)")
ok(notes == {cd.player.name: cd.note for cd in db.query(Card).filter_by(tier=Tier.speciale).all()}, "aucune note ni création en double")
print("BILAN (spéciales par rareté) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
