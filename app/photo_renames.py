"""
Photos renommées (branche `renommer-photos`, 25/11/2026, choisi par Théo) : les fichiers de frontend/photos/ des personnes du club
suivent tous la même forme : « Prénom.ext » (photo normale), « Prénom Celeb.ext » (les anciennes « Fun » et « -celeb »),
« Prénom Halloween.ext » / « Prénom Noel.ext » (éditions limitées ; « Prénom Halloween fond.ext » = la version avec son décor),
« Prénom non utile.ext » (fond blanc, plus utilisée). Les autres images (objets, écussons, cartes gold comme brice-but ou tim-orteille,
secrètes) gardent leur nom.

Les cartes gardent leur photo : au démarrage, UNE seule fois (verrou job_runs « photos_renommees_2026_11 »), chaque adresse
enregistrée en base qui pointe vers un ancien nom est remplacée par le nouveau : photo d'une personne (`Player.photo_url`), photos par
rareté (`Player.tier_photos`) et images des séries numérotées (`NumberedSeries.photo_url`). Ancien nom → nouveau nom : RENAMES.
"""
import json
import unicodedata
from datetime import datetime
from urllib.parse import unquote

RENAMES = {
    "Alexi Sérieux.png": "Alexi.png", "Alexi Fun.png": "Alexi Celeb.png", "alexi-noel.png": "Alexi Noel.png",
    "Arthur Fun.png": "Arthur Celeb.png",
    "Clément Fun.png": "Clément Celeb.png",
    "Eliott Fun.png": "Eliott Celeb.png", "eliott-noel.png": "Eliott Noel.png",
    "Emrys Fun.png": "Emrys Celeb.png", "emrys-noel.png": "Emrys Noel.png",
    "Eva Fun.png": "Eva Celeb.png", "eva-hall.png": "Eva Halloween.png", "eva-hal.png": "Eva Halloween fond.png",
    "Gaëtan Fun.png": "Gaëtan Celeb.png", "gaetan-halloween.webp": "Gaëtan Halloween.webp",
    "Ilan Sérieux.png": "Ilan.png", "Ilan Fun.png": "Ilan Celeb.png",
    "Léo Sérieux.png": "Léo.png", "leo-celeb.png": "Léo Celeb.png", "leo-celeb.webp": "Léo Celeb.webp", "leo-halloween.webp": "Léo Halloween.webp",
    "Martin (2).webp": "Martin.webp", "Martin Fun.png": "Martin Celeb.png", "martin-halloween.webp": "Martin Halloween.webp",
    "martin-noel.webp": "Martin Noel.webp",
    "Mathieu Fun.png": "Mathieu Celeb.png",
    "Mathys Fun.png": "Mathys Celeb.png", "mathys-noel.png": "Mathys Noel.png",
    "mathis.png": "Mathis.png",
    "matheo.png": "Mathéo.png", "matheo.webp": "Mathéo.webp", "matheo-celeb.png": "Mathéo Celeb.png", "matheo-celeb.webp": "Mathéo Celeb.webp",
    "matheo-noel.png": "Mathéo Noel.png",
    "mattéo.png": "Mattéo.png", "mattéo-celeb.png": "Mattéo Celeb.png", "matteo-halloween.webp": "Mattéo Halloween.webp",
    "Mattéo Fun.png": "Mattéo non utile.png", "Mattéo Sérieux.png": "Mattéo non utile 2.png",
    "Nath.webp": "Nathan.webp", "nath-noel.png": "Nathan Noel.png",
    "Nico Fun.png": "Nico Celeb.png", "nico-noel.png": "Nico Noel.png",
    "Soël Sérieux.png": "Soël.png", "Soêl Fun.png": "Soël Celeb.png", "soel-hall.png": "Soël Halloween.png", "soel-hal.png": "Soël Halloween fond.png",
    "Théo Fun.png": "Théo Celeb.png", "theo-noel.png": "Théo Noel.png",
    "Timothée Sérieux.png": "Timothée.png", "Timothée Fun.png": "Timothée Celeb.png", "tim-hall.png": "Timothée Halloween.png",
    "tim-hal.png": "Timothée Halloween fond.png",
    "Vincent Fun.png": "Vincent Celeb.png", "vincent-halloween.webp": "Vincent Halloween.webp",
    "Yann Fun.png": "Yann Celeb.png",
    "brice.png": "Brice.png", "brice-celeb.png": "Brice Celeb.png",
    "candice.png": "Candice.png", "candice-fun.png": "Candice Celeb.png",
    "come.png": "Côme.png", "come fun.png": "Côme Celeb.png",
    "fleur.png": "Fleur.png", "fleur-noel.png": "Fleur Noel.png",
    "gab.png": "Gabriel.png", "greg.png": "Grégoire.png",
    "lucas.png": "Lucas.png", "lucas.webp": "Lucas.webp", "lucas-halloween.webp": "Lucas Halloween.webp",
    "mael.png": "Maël.png", "mael-celeb.png": "Maël Celeb.png",
    "marco.png": "Marco.png", "marco-celeb.png": "Marco Celeb.png",
    "tibo.png": "Thibaud.png", "tibo.webp": "Thibaud non utile.webp", "tibo-celeb.png": "Thibaud Celeb.png", "tibo-celeb.webp": "Thibaud Celeb.webp",
    "tibo-noel.png": "Thibaud Noel.png",
}
LOCK = "photos_renommees_2026_11"

_NFC = lambda s: unicodedata.normalize("NFC", s)
_MAP = {_NFC(k): v for k, v in RENAMES.items()}


def new_path(path):
    """« /photos/tibo.png » -> « /photos/Thibaud.png » ; toute autre adresse est renvoyée telle quelle (None si inchangée)."""
    if not path or not isinstance(path, str):
        return None
    p = _NFC(unquote(path.strip()))
    for prefix in ("/photos/", "photos/"):
        if p.startswith(prefix) and p[len(prefix):] in _MAP:
            return "/photos/" + _MAP[p[len(prefix):]]
    return None


def apply(db) -> int:
    """Remplace les anciens noms dans la base. Renvoie le nombre d'adresses changées. Sans verrou : à appeler par run_once."""
    from .models import Player
    from .numbered import NumberedSeries
    n = 0
    for pl in db.query(Player).all():
        np = new_path(pl.photo_url)
        if np:
            pl.photo_url = np; n += 1
        if pl.tier_photos:
            try:
                tp = json.loads(pl.tier_photos)
            except Exception:
                tp = None
            if isinstance(tp, dict):
                changed = False
                for k, v in list(tp.items()):
                    nv = new_path(v)
                    if nv:
                        tp[k] = nv; changed = True; n += 1
                if changed:
                    pl.tier_photos = json.dumps(tp, ensure_ascii=False)
    for s in db.query(NumberedSeries).all():
        np = new_path(s.photo_url)
        if np:
            s.photo_url = np; n += 1
    return n


def run_once(db) -> int:
    """Une seule fois par base (verrou job_runs)."""
    from .models import JobRun
    if db.get(JobRun, LOCK) is not None:
        return 0
    db.add(JobRun(name=LOCK, last_run_at=datetime.utcnow())); db.flush()
    n = apply(db)
    db.commit()
    return n
