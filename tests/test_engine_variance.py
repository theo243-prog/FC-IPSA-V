"""
Test : moteur de match « moins aléatoire » (part acquise des buts + exposant 3). Même nombre moyen de buts, moins de variance,
le niveau des cartes pèse davantage, cartes égales toujours ~40 / 20 / 39, Poisson pur sous 2 buts attendus, récit fidèle au score.
Hasard fixé (random.seed) : le test donne toujours le même résultat. Lancé par tests/run_tests.py.
"""
import random
from app import duel_engine as DE
FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
N = 20000
SLOTS = {"1-2-1": ["GB", "DEF", "MC", "MC", "ATT"], "2-1-1": ["GB", "DEF", "DEF", "MC", "ATT"], "1-1-2": ["GB", "DEF", "MC", "ATT", "ATT"]}
def team(formation, note):
    return [{"slot": s, "player": "J%d" % i, "tier": "commune", "poste": s, "base_note": note, "effective": note, "out_of_position": False, "captain": False} for i, s in enumerate(SLOTS[formation])]


def wdl(note_a, note_b, old=False, formation="1-2-1"):
    """Victoires / nuls / défaites de A en %, avec le moteur actuel ou l'ancien (exposant 1,5, skew 0,5, Poisson pur)."""
    saved = (DE.XG_EXPONENT, DE.FORMATION_SKEW)
    if old:
        DE.XG_EXPONENT, DE.FORMATION_SKEW = 1.5, 0.5
    try:
        att_a, def_a, *_ = DE.team_powers(team(formation, note_a), None)
        att_b, def_b, *_ = DE.team_powers(team(formation, note_b), None)
        xa, xb = DE.expected_goals(att_a, def_b), DE.expected_goals(att_b, def_a)
    finally:
        DE.XG_EXPONENT, DE.FORMATION_SKEW = saved
    draw = DE.poisson_random if old else DE.draw_goals
    w = d = 0
    for _ in range(N):
        a, b = draw(xa), draw(xb); w += a > b; d += a == b
    return 100 * w / N, 100 * d / N, 100 * (N - w - d) / N


print("1) CONSTANTES")
ok(DE.XG_EXPONENT == 3.0 and DE.FORMATION_SKEW == 0.25 and DE.BASE_XG == 3.0 and DE.FIXED_GOALS_SHARE == 0.5, "exposant 3, skew 0,25, xG de base 3, part acquise 0,5")

print("2) MÊME MOYENNE, MOINS DE VARIANCE")
random.seed(1)
for xg in (2.0, 2.8, 3.6, 5.0):
    g = [DE.draw_goals(xg) for _ in range(N)]; m = sum(g) / N; v = sum((x - m) ** 2 for x in g) / N
    ok(abs(m - xg) / xg < 0.03 and v < xg * 0.9, "xg %.1f : moyenne %.3f (écart %.1f %%), variance %.2f contre %.1f pour un Poisson pur" % (xg, m, 100 * abs(m - xg) / xg, v, xg))
ok(all(DE.draw_goals(2.8) >= 1 for _ in range(2000)), "xg 2,8 : au moins 1 but à chaque fois (part acquise)")

print("3) SOUS 2 BUTS ATTENDUS : POISSON PUR")
for xg in (0.4, 1.2, 1.99):
    random.seed(42); a = [DE.draw_goals(xg) for _ in range(500)]
    random.seed(42); b = [DE.poisson_random(xg) for _ in range(500)]
    ok(a == b, "xg %.2f : exactement les mêmes tirages qu'un Poisson pur" % xg)

print("4) BUTS PAR FORMATION INCHANGÉS (cartes égales)")
for f, want in (("2-1-1", 1.4), ("1-2-1", 2.0), ("1-1-2", 2.6)):
    att, de, *_ = DE.team_powers(team(f, 85), None)
    ok(abs(DE.expected_goals(att, de) - want) < 0.1, "%s contre %s : %.2f buts attendus par équipe (≈ %.1f)" % (f, f, DE.expected_goals(att, de), want))
att_o, def_o, *_ = DE.team_powers(team("1-1-2", 85), None); att_p, def_p, *_ = DE.team_powers(team("2-1-1", 85), None)
ok(abs(DE.expected_goals(att_o, def_p) - 1.9) < 0.1 and abs(DE.expected_goals(att_p, def_o) - 1.9) < 0.1, "1-1-2 contre 2-1-1 : %.2f et %.2f (≈ 1,9)" % (DE.expected_goals(att_o, def_p), DE.expected_goals(att_p, def_o)))

print("5) RÉSULTATS")
random.seed(7); w, d, l = wdl(85, 85)
ok(abs(w - 40) < 3 and abs(d - 20) < 3 and abs(l - 39) < 3, "cartes égales : %.1f / %.1f / %.1f (≈ 40 / 20 / 39)" % (w, d, l))
random.seed(7); wn, dn, ln = wdl(90, 80); random.seed(7); wo, do, lo = wdl(90, 80, old=True)
ok(wn > wo + 10 and abs(wn - 70) < 4 and ln < 17, "favori 90 contre 80 : %.1f %% de victoires (ancien moteur %.1f %%), %.1f %% de défaites" % (wn, wo, ln))

print("6) LE RÉCIT RACONTE EXACTEMENT LE SCORE")
random.seed(3); good = True
for _ in range(300):
    sa, sb = random.randint(0, 7), random.randint(0, 7)
    A = {"pseudo": "a", "formation": "1-2-1", "tactic": "pressing", "members": team("1-2-1", 85)}
    B = {"pseudo": "b", "formation": "1-1-2", "tactic": "contre", "members": [dict(m, player="K%d" % i) for i, m in enumerate(team("1-1-2", 85))]}
    ev = DE.build_events(A, B, sa, sb, 2.0, 2.0, None)
    goals = [e for e in ev if e.get("kind") == "goal"]
    good &= sum(e["side"] == "challenger" for e in goals) == sa and sum(e["side"] == "defender" for e in goals) == sb
ok(good, "300 scores au hasard (jusqu'à 7-7) : le récit compte exactement les buts de chaque équipe")
print("BILAN (moteur de match) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
