"""
Test : photos renommées (« Prénom », « Prénom Celeb », « Prénom Halloween / Noel », « non utile ») sans que les cartes perdent leur photo.
Lancé par tests/run_tests.py.
"""
import json, os, unicodedata
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import Player, JobRun
from app import photo_renames as PR
from app.numbered import NumberedSeries
c = TestClient(app); A = {"X-Admin-Key": "k"}; FAILS = []
def ok(cond, msg):
    print(("  OK   " if cond else "  ÉCHEC ") + msg)
    if not cond: FAILS.append(msg)
db = SessionLocal()
PHOTOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "photos")
on_disk = {unicodedata.normalize("NFC", f) for f in os.listdir(PHOTOS)}

print("1) LES FICHIERS")
DELETED_LATER = {"Lucas.webp"}                     # supprimé ensuite par Théo sur GitHub (25/11/2026, Lucas.png reste)
ok(all(unicodedata.normalize("NFC", v) in on_disk for v in PR.RENAMES.values() if v not in DELETED_LATER), "chaque nouveau nom existe dans frontend/photos (%d fichiers, sauf ceux supprimés ensuite)" % len(PR.RENAMES))
ok(not [k for k in PR.RENAMES if unicodedata.normalize("NFC", k) in on_disk and k.lower() != PR.RENAMES[k].lower()], "aucun ancien nom n'est resté dans le dossier")
ok(len({v.lower() for v in PR.RENAMES.values()}) == len(PR.RENAMES), "deux anciennes photos ne prennent jamais le même nom")
ok("tim-orteille.png" in on_disk and "brice-but.png" in on_disk and "leo-secrete.webp" in on_disk, "les autres photos (gold, secrètes) gardent leur nom")

print("2) LES LIENS EN BASE")
db.query(JobRun).filter_by(name=PR.LOCK).delete(); db.commit()     # (le démarrage du test l'a déjà posé sur une base vide)
lucas = db.query(Player).filter_by(name="Lucas").first(); hugo = db.query(Player).filter_by(name="Hugo").first()
lucas.photo_url = "/photos/tibo.png"; lucas.tier_photos = json.dumps({"rare": "/photos/tibo-celeb.webp", "halloween": "/photos/leo-halloween.webp", "secrete": "/photos/leo-secrete.webp"})
hugo.photo_url = "/photos/Mat" + "te\u0301o Fun.png"                  # (accent décomposé, comme parfois depuis un Mac)
s = NumberedSeries(title="Édition Noire", subject="Test photo", total=5, photo_url="/photos/come%20fun.png"); db.add(s); db.commit()
n = PR.run_once(db); db.expire_all()
tp = json.loads(lucas.tier_photos)
ok(lucas.photo_url == "/photos/Thibaud.png", "photo d'une personne : tibo.png -> Thibaud.png")
ok(tp == {"rare": "/photos/Thibaud Celeb.webp", "halloween": "/photos/Léo Halloween.webp", "secrete": "/photos/leo-secrete.webp"}, "photos par rareté suivies, la secrète ne change pas : %s" % tp)
ok(hugo.photo_url == "/photos/Mattéo non utile.png", "accent écrit autrement : reconnu (%s)" % hugo.photo_url)
ok(db.get(NumberedSeries, s.id).photo_url == "/photos/Côme Celeb.png", "image d'une série numérotée suivie")
ok(n == 5, "5 adresses changées (%d)" % n)
lucas.photo_url = "/photos/tibo.png"; db.commit()
ok(PR.run_once(db) == 0 and db.query(Player).filter_by(name="Lucas").first().photo_url == "/photos/tibo.png", "une seule fois (verrou)")
ok(PR.new_path("https://exemple.fr/tibo.png") is None and PR.new_path(None) is None, "une adresse extérieure ne change jamais")

print(); print("BILAN (photos renommées) :", "TOUT EST VERT" if not FAILS else f"{len(FAILS)} ÉCHEC(S) : {FAILS}")
