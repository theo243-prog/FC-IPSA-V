"""
Restaure une sauvegarde (.json.gz téléchargée depuis l'administration) dans une base VIDE.

    DATABASE_URL=postgresql://... python -m app.restore_backup fichier.json.gz

Le programme refuse de tourner si la base contient déjà des données (pour ne jamais écraser ni dupliquer). Les connexions en cours n'étaient pas sauvegardées :
tout le monde doit simplement se reconnecter.
"""
import base64
import gzip
import json
import sys
from datetime import date, datetime

from sqlalchemy import Date, DateTime, LargeBinary, func, select, text

from .database import Base, engine
from . import main                      # (importer main enregistre toutes les tables)
from .backup import FORMAT, SKIP_TABLES


def _convert(col, v):
    if v is None:
        return None
    if isinstance(col.type, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(col.type, Date):
        return date.fromisoformat(v)
    if isinstance(col.type, LargeBinary) and isinstance(v, dict) and "$b64" in v:
        return base64.b64decode(v["$b64"])
    return v


def restore(path: str) -> dict:
    with gzip.open(path, "rb") as f:
        payload = json.loads(f.read().decode("utf-8"))
    if payload.get("format") != FORMAT:
        raise SystemExit("Ce fichier n'est pas une sauvegarde FC IPSA V.")
    Base.metadata.create_all(engine)
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    with engine.begin() as conn:
        for name in tables:
            if name not in SKIP_TABLES and conn.execute(select(func.count()).select_from(tables[name])).scalar():
                raise SystemExit("La base n'est pas vide (table « %s ») : restauration refusée." % name)
        done = {}
        for name, t in tables.items():                      # dans l'ordre des dépendances
            data = payload["tables"].get(name)
            if not data:
                continue
            cols = {c.name: c for c in t.columns}
            rows = [{c: _convert(cols[c], v) for c, v in zip(data["columns"], r) if c in cols} for r in data["rows"]]
            for i in range(0, len(rows), 500):
                conn.execute(t.insert(), rows[i:i + 500])
            done[name] = len(rows)
        if engine.dialect.name == "postgresql":              # les compteurs automatiques repartent après le plus grand numéro restauré
            for name, t in tables.items():
                pk = list(t.primary_key.columns)
                if len(pk) == 1 and pk[0].autoincrement is not False and pk[0].type.python_type is int and name in done:
                    conn.execute(text("SELECT setval(pg_get_serial_sequence('%s', '%s'), COALESCE((SELECT MAX(%s) FROM %s), 1))" % (name, pk[0].name, pk[0].name, name)))
    return done


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage : python -m app.restore_backup fichier.json.gz")
    res = restore(sys.argv[1])
    print("Restauration terminée : %d tables, %d lignes." % (len(res), sum(res.values())))
