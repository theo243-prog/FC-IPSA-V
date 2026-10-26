"""
Lance toutes les suites de tests du serveur, chacune sur une base de données jetable (SQLite temporaire : ta vraie base n'est jamais touchée).

    python tests/run_tests.py                 # toutes les suites
    python tests/run_tests.py test_pass       # une seule

Les données de départ viennent de tests/seed_test_data.py (30 joueurs fictifs) : ne pas confondre avec app/seed_data.py.
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITES = ["test_pass", "test_social2", "test_tournament", "test_duel_packs", "test_backup", "test_features2", "test_club", "test_first_steps", "test_smoke_routes"]


def run(name: str):
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "test.db").replace("\\", "/")
        env = {**os.environ, "ADMIN_KEY": "k", "DATABASE_URL": "sqlite:///" + db, "PYTHONPATH": ROOT, "WELCOME_ULTRA_GIFTS": "0", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        seed = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "seed_test_data.py")], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if seed.returncode != 0:
            return False, 0, ["Les données de départ n'ont pas pu être créées :", seed.stderr[-600:]]
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", name + ".py")], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        except subprocess.TimeoutExpired:
            return False, 0, ["Trop long (plus de 15 minutes)."]
    lines = r.stdout.splitlines()
    ok = sum(1 for l in lines if l.startswith("  OK"))
    green = any("TOUT EST VERT" in l for l in lines) and r.returncode == 0
    problems = [l for l in lines if l.startswith("  ÉCHEC")] or ([] if green else (lines[-3:] + r.stderr.splitlines()[-8:]))
    return green, ok, problems


if __name__ == "__main__":
    wanted = [a.replace(".py", "") for a in sys.argv[1:]] or SUITES
    unknown = [w for w in wanted if w not in SUITES]
    if unknown:
        raise SystemExit("Suite inconnue : %s. Choix : %s" % (", ".join(unknown), ", ".join(SUITES)))
    bad = 0
    for name in wanted:
        t0 = time.time(); green, ok, problems = run(name)
        print("%-18s %s  (%d vérifications, %d s)" % (name, "VERT " if green else "ROUGE", ok, time.time() - t0), flush=True)
        for p in problems:
            print("     ", p)
        bad += 0 if green else 1
    print("\nRésultat :", "TOUT EST VERT" if not bad else "%d suite(s) en échec" % bad)
    sys.exit(1 if bad else 0)
