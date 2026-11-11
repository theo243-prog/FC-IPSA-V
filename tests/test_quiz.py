"""
Test : banque du quiz foot (100 questions : 41 faciles, 29 moyennes, 30 difficiles) et tirage du jour (depuis le 12/11/2026 :
2 faciles, 2 moyennes, 1 difficile ; avant : 5 faciles, comme avant). Lancé par tests/run_tests.py.
"""
from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app import minigame as MG, game_logic as GL
FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)

print("1) LA BANQUE DE QUESTIONS")
ok(len(MG.BANK) == 100 and (len(MG.BANK_EASY), len(MG.BANK_MEDIUM), len(MG.BANK_HARD)) == (41, 29, 30), "100 questions : 41 faciles, 29 moyennes, 30 difficiles")
ok(len({q[0] for q in MG.BANK}) == 100, "aucune question en double")
ok(all(len(q) == 4 and len(q[2]) == 2 and q[1] not in q[2] and len({q[1], *q[2]}) == 3 and q[3] for q in MG.BANK), "chaque question : 1 bonne réponse, 2 mauvaises différentes, une explication")

print("2) LE TIRAGE DU JOUR")
days = [(date(2026, 11, 12) + timedelta(days=i)).isoformat() for i in range(60)]
mixes = [[q["difficulty"] for q in MG.questions_for(d)] for d in days]
ok(all(m == ["facile", "facile", "moyen", "moyen", "difficile"] for m in mixes), "depuis le 12/11 : 2 faciles, 2 moyennes puis 1 difficile, dans cet ordre")
ok(all(len({q["q"] for q in MG.questions_for(d)}) == 5 for d in days), "5 questions différentes chaque jour")
ok(MG.questions_for("2026-11-20") == MG.questions_for("2026-11-20"), "les mêmes questions pour tout le monde, toute la journée")
ok(all(q["difficulty"] == "facile" and any(q["q"] == e[0] for e in MG.BANK_EASY) for q in MG.questions_for("2026-11-11")), "avant le 12/11 : l'ancien tirage (5 faciles), pour ne pas changer un quiz commencé")
seen = {q["q"] for d in days for q in MG.questions_for(d)}
ok(len(seen) >= 80, "en 60 jours, au moins 80 questions différentes sortent (%d)" % len(seen))

print("3) LA QUESTION ENVOYÉE AU SITE")
c = TestClient(app)
t = c.post("/auth/register", json={"pseudo": "quizz", "password": "test1234"}).json()["token"]; H = {"Authorization": "Bearer " + t}
real_today = GL.today_paris
quiz_day = next(date(2026, 11, 12) + timedelta(days=i) for i in range(4) if MG.kind_for((date(2026, 11, 12) + timedelta(days=i)).isoformat()) == "quiz")
GL.today_paris = lambda: quiz_day
r = c.post("/minigame/answer", json={"choice": 0}, headers=H).json()
ok(r["question"]["difficulty"] == "facile" and "answer" not in r["question"] and set(r["question"]) == {"index", "text", "choices", "difficulty"}, "la question suivante a sa difficulté, jamais sa bonne réponse")
GL.today_paris = real_today

print(); print("BILAN (quiz) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
