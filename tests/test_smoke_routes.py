"""
Filet de sécurité : appelle toutes les routes de consultation (GET sans paramètre dans l'adresse) avec un joueur puis avec l'admin :
aucune ne doit renvoyer une erreur serveur (500). Attrape les oublis d'import, de table ou de colonne.
Lancer comme test_social2.py (voir tests/LISEZMOI.md).
"""
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app); A = {"X-Admin-Key": "k"}; bad = []; n = 0
tok = c.post("/auth/register", json={"pseudo": "smoke", "password": "test1234"}).json()["token"]; H = {"Authorization": "Bearer " + tok}
for r in app.routes:
    if not hasattr(r, "methods") or "GET" not in r.methods or "{" in r.path or r.path.startswith(("/docs", "/openapi", "/redoc")):
        continue
    for who, hdr in (("joueur", H), ("admin", {**H, **A}), ("anonyme", {})):
        resp = c.get(r.path, headers=hdr); n += 1
        if resp.status_code >= 500: bad.append((who, r.path, resp.status_code, resp.text[:120]))
print("routes de consultation appelées :", n)
for b in bad: print("  ÉCHEC", b)
print("BILAN (routes de consultation) :", "TOUT EST VERT" if not bad else "%d ERREUR(S) SERVEUR" % len(bad))
