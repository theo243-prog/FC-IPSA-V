"""
Sauvegarde de la base de données.

- AUTOMATIQUE : chaque jour à partir de 4h du matin (heure de Paris), le serveur prend un « instantané » de toute la base (comptes, cartes, collections, crédits, marché,
  matchs, tournois, Pass…) et le garde dans la base elle-même, compressé. On conserve les 7 derniers instantanés automatiques et les 3 derniers manuels.
- EXPORT : depuis la page d'administration (onglet « Sauvegardes »), tu peux faire une sauvegarde tout de suite, télécharger n'importe quel instantané, ou télécharger un export
  tout frais. Le fichier (.json.gz) est à garder PRIVÉ : il contient les mots de passe chiffrés des joueurs.
- RESTAURER : python -m app.restore_backup fichier.json.gz (dans une base VIDE ; voir restore_backup.py).
Ce qui n'est pas sauvegardé : les connexions en cours (les joueurs devront simplement se reconnecter) et les instantanés eux-mêmes.
"""
import base64
import enum
import gzip
import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import Column, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import AppSetting, gen_id
from .common import require_admin
from .prono import now_paris
from .version import VERSION

router = APIRouter()
KEEP_AUTO, KEEP_MANUAL, AUTO_HOUR = 7, 3, 4
SKIP_TABLES = {"db_backups", "user_sessions"}          # les instantanés eux-mêmes ; les connexions (jetons secrets, sans intérêt à restaurer)
FORMAT = "fc-ipsa-v-sauvegarde-1"


class DbBackup(Base):
    __tablename__ = "db_backups"
    id = Column(String, primary_key=True, default=gen_id)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    kind = Column(String, nullable=False, default="auto")          # auto / manuel
    size_bytes = Column(Integer, nullable=False, default=0)
    tables = Column(Integer, nullable=False, default=0)
    rows = Column(Integer, nullable=False, default=0)
    data = Column(LargeBinary, nullable=False)


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, enum.Enum):
        return v.name
    if isinstance(v, Decimal):
        return str(v)
    return v


def dump(db: Session):
    """Toute la base en un fichier compressé : (octets, nombre de tables, nombre de lignes)."""
    payload = {"format": FORMAT, "created_at": datetime.utcnow().isoformat(), "app_version": VERSION, "tables": {}}
    n_rows = 0
    for table in Base.metadata.sorted_tables:
        if table.name in SKIP_TABLES:
            continue
        rows = [[_jsonable(v) for v in r] for r in db.execute(table.select()).fetchall()]
        payload["tables"][table.name] = {"columns": [c.name for c in table.columns], "rows": rows}
        n_rows += len(rows)
    return gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 6), len(payload["tables"]), n_rows


def create(db: Session, kind: str = "auto") -> DbBackup:
    data, n_tables, n_rows = dump(db)
    b = DbBackup(kind=kind, size_bytes=len(data), tables=n_tables, rows=n_rows, data=data)
    db.add(b); db.flush()
    prune(db)
    return b


def prune(db: Session) -> None:
    for kind, keep in (("auto", KEEP_AUTO), ("manuel", KEEP_MANUAL)):
        old = db.query(DbBackup).filter_by(kind=kind).order_by(DbBackup.created_at.desc(), DbBackup.id).offset(keep).all()
        for b in old:
            db.delete(b)


def tick(db: Session, now: datetime = None) -> None:
    """À appeler souvent : prend l'instantané du jour à partir de 4h (une seule fois par jour)."""
    now = now or now_paris()
    if now.hour < AUTO_HOUR:
        return
    today = now.date().isoformat(); row = db.get(AppSetting, "backup_last_auto_day")
    if row is not None and row.value == today:
        return
    create(db, "auto")
    if row is None:
        db.add(AppSetting(key="backup_last_auto_day", value=today))
    else:
        row.value = today
    db.commit()


def _name(created: datetime, suffix: str = "") -> str:
    return "fc-ipsa-v-sauvegarde-%s%s.json.gz" % (created.strftime("%Y-%m-%d-%Hh%M"), suffix)


def _file(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type="application/gzip", headers={"Content-Disposition": 'attachment; filename="%s"' % filename, "Cache-Control": "no-store"})


def _out(b: DbBackup) -> dict:
    return {"id": b.id, "created_at": b.created_at.isoformat(), "kind": b.kind, "size_kb": round(b.size_bytes / 1024, 1), "tables": b.tables, "rows": b.rows}


@router.get("/admin/backups", dependencies=[Depends(require_admin)])
def list_backups(db: Session = Depends(get_db)):
    """Les instantanés gardés (le plus récent en premier)."""
    return [_out(b) for b in db.query(DbBackup).order_by(DbBackup.created_at.desc(), DbBackup.id).all()]


@router.post("/admin/backup-now", dependencies=[Depends(require_admin)])
def backup_now(db: Session = Depends(get_db)):
    """Prend un instantané tout de suite (gardé avec les autres)."""
    b = create(db, "manuel"); db.commit()
    return {"status": "ok", **_out(b)}


@router.get("/admin/backup/{backup_id}/download", dependencies=[Depends(require_admin)])
def download_backup(backup_id: str, db: Session = Depends(get_db)):
    b = db.get(DbBackup, backup_id)
    if b is None:
        raise HTTPException(status_code=404, detail="Sauvegarde introuvable")
    return _file(bytes(b.data), _name(b.created_at))


@router.get("/admin/backup-export", dependencies=[Depends(require_admin)])
def export_now(db: Session = Depends(get_db)):
    """Un export tout frais (non gardé) à télécharger tout de suite."""
    data, _t, _r = dump(db)
    return _file(data, _name(datetime.utcnow(), "-export"))
