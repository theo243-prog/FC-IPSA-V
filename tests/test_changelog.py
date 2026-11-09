"""
Test : historique des changements du jeu (bouton « 📜 Nouveautés »). Liste du code valide (identifiants uniques, dates, catégories,
ordre décroissant), route publique, fusion avec les notes de l'administration, suppression d'une note, 403 sans clé admin.
Lancé par tests/run_tests.py.
"""
import re
from datetime import date

from fastapi.testclient import TestClient
from app.main import app
from app import changelog as CL, changelog_data as CD, admin_tools
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)

print("1) LA LISTE DU CODE (app/changelog_data.py)")
E = CD.ENTRIES
ids = [e.get("id") for e in E]
ok(all(isinstance(i, str) and i.strip() for i in ids) and len(set(ids)) == len(ids), "identifiants présents et uniques (%d entrées)" % len(E))
ok(not any(str(i).startswith("note-") for i in ids), "aucun identifiant ne commence par « note- » (réservé aux notes de l'administration)")
def valid_date(s):
    try: return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)) and date.fromisoformat(s) is not None
    except Exception: return False
ok(all(valid_date(e.get("date", "")) for e in E), "dates valides (AAAA-MM-JJ)")
ok(all(e.get("category") in CL.CATEGORIES for e in E), "catégories valides (%s)" % ", ".join(CL.CATEGORIES))
ok(all(isinstance(e.get("title"), str) and e["title"].strip() and "\n" not in e["title"] and len(e["title"]) <= 120 for e in E), "un titre d'une ligne pour chaque entrée")
ok(all(isinstance(e.get("text"), str) and e["text"].strip() and len(e["text"]) <= 800 for e in E), "un texte pour chaque entrée (800 caractères au plus)")
ok(all(E[i]["date"] >= E[i + 1]["date"] for i in range(len(E) - 1)), "la plus récente en premier")
ok(all(set(e) == {"id", "date", "title", "text", "category"} for e in E), "chaque entrée n'a que id, date, title, text, category")

print("2) ROUTE PUBLIQUE")
r = c.get("/changelog"); j = r.json()
ok(r.status_code == 200 and len(j["items"]) == len(E), "GET /changelog sans compte : la liste du code")
ok(j["latest"] == (E[0]["date"] if E else None), "« latest » = la date la plus récente")

print("3) NOTES DE L'ADMINISTRATION")
body = {"title": "Maintenance ce soir", "text": "Le site sera coupé 10 minutes à 22 h.", "category": "autre"}
ok(c.post("/admin/changelog-add", json=body).status_code == 403, "ajouter sans clé admin : 403")
ok(c.post("/admin/changelog-add", json=body, headers={"X-Admin-Key": "mauvaise"}).status_code == 403, "ajouter avec une mauvaise clé : 403")
ok(c.get("/admin/changelog").status_code == 403, "voir les notes sans clé admin : 403")
ok(c.post("/admin/changelog-add", json={**body, "category": "secret"}, headers=A).status_code == 400, "catégorie inconnue : refusée")
ok(c.post("/admin/changelog-add", json={**body, "title": "   "}, headers=A).status_code == 400, "titre vide : refusé")
r = c.post("/admin/changelog-add", json=body, headers=A); n = r.json().get("note", {})
ok(r.status_code == 200 and n.get("id", "").startswith("note-") and valid_date(n.get("date", "")), "note ajoutée (%s, datée du %s)" % (n.get("id"), n.get("date")))
n2 = c.post("/admin/changelog-add", json={"title": "Pass ×2 ce week-end", "text": "Les points du Pass comptent double.", "category": "économie"}, headers=A).json()["note"]
j = c.get("/changelog").json(); items = j["items"]
ok(len(items) == len(E) + 2, "la route publique fusionne le code et les 2 notes")
ok(items[0]["id"] == n2["id"] and items[1]["id"] == n["id"], "notes du jour en tête, la plus récente d'abord")
ok(all(items[i]["date"] >= items[i + 1]["date"] for i in range(len(items) - 1)), "liste fusionnée triée par date décroissante")
ok(j["latest"] == n2["date"], "« latest » suit les notes")
ok([x["id"] for x in c.get("/admin/changelog", headers=A).json()] == [n2["id"], n["id"]], "l'administration voit ses notes avec leur identifiant")
ok("Maintenance ce soir" in admin_tools.summarize("/admin/changelog-add", body) and "note-1" in admin_tools.summarize("/admin/changelog-delete", {"note_id": "note-1"}), "résumé dans le journal de l'administration")

print("4) SUPPRIMER UNE NOTE")
ok(c.post("/admin/changelog-delete", json={"note_id": n["id"]}).status_code == 403, "supprimer sans clé admin : 403")
r = c.post("/admin/changelog-delete", json={"note_id": n["id"]}, headers=A)
ok(r.status_code == 200 and n["id"] not in [x["id"] for x in c.get("/changelog").json()["items"]], "note supprimée : elle disparaît de la liste publique")
ok(c.post("/admin/changelog-delete", json={"note_id": n["id"]}, headers=A).status_code == 404, "supprimer deux fois : 404")
ok(c.post("/admin/changelog-delete", json={"note_id": n2["id"].removeprefix("note-")}, headers=A).status_code == 200, "le numéro seul marche aussi")
if E: ok(c.post("/admin/changelog-delete", json={"note_id": E[0]["id"]}, headers=A).status_code == 400, "une entrée du code ne se supprime pas d'ici")
ok(len(c.get("/changelog").json()["items"]) == len(E), "il ne reste que la liste du code")

print("BILAN (historique des changements) :", "TOUT EST VERT" if not FAILS else "%d ÉCHEC(S)" % len(FAILS))
raise SystemExit(1 if FAILS else 0)
