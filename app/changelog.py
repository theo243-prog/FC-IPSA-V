"""
Historique des changements du jeu (bouton « 📜 Nouveautés » du site).

Deux sources, fusionnées par GET /changelog (public, sans compte) et triées par date décroissante :
  - changelog_data.ENTRIES : la liste écrite dans le code (une entrée par changement de règle visible par les joueurs) ;
  - la table changelog_notes : les notes ajoutées depuis l'administration, pour publier une information urgente sans déployer.
Une note de l'administration a pour identifiant « note-<numéro> » (jamais en conflit avec ceux du fichier).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from .database import Base, get_db
from .common import require_admin
from . import weekly
from .changelog_data import ENTRIES

router = APIRouter()
CATEGORIES = ("règles", "cartes", "modes", "économie", "autre")


class ChangelogNote(Base):
    __tablename__ = "changelog_notes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False)                 # AAAA-MM-JJ, jour de Paris de la publication
    title = Column(String, nullable=False)
    text = Column(String, nullable=False)
    category = Column(String, nullable=False, default="autre")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def _note_out(n: ChangelogNote) -> dict:
    return {"id": "note-%d" % n.id, "date": n.date, "title": n.title, "text": n.text, "category": n.category, "source": "admin"}


def all_entries(db: Session) -> list:
    """Le fichier + les notes de l'administration, la plus récente d'abord (à date égale : les notes, puis l'ordre du fichier)."""
    notes = [_note_out(n) for n in db.query(ChangelogNote).order_by(ChangelogNote.id.desc()).all()]
    items = notes + [dict(e, source="jeu") for e in ENTRIES]
    return sorted(items, key=lambda e: e["date"], reverse=True)      # tri stable : l'ordre ci-dessus départage


@router.get("/changelog")
def changelog(db: Session = Depends(get_db)):
    items = all_entries(db)
    return {"latest": items[0]["date"] if items else None, "items": items}


class NoteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=600)
    category: str = "autre"


@router.post("/admin/changelog-add", dependencies=[Depends(require_admin)])
def add_note(payload: NoteRequest, db: Session = Depends(get_db)):
    title, text, cat = payload.title.strip(), payload.text.strip(), (payload.category or "autre").strip().lower()
    if not title or not text:
        raise HTTPException(status_code=400, detail="Le titre et le texte sont obligatoires")
    if cat not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Catégorie inconnue : " + ", ".join(CATEGORIES))
    note = ChangelogNote(date=weekly.to_paris(datetime.utcnow()).strftime("%Y-%m-%d"), title=title, text=text, category=cat)
    db.add(note)
    db.commit()
    return {"status": "ok", "note": _note_out(note)}


class DeleteNoteRequest(BaseModel):
    note_id: str                                          # « note-3 » ou « 3 »


@router.post("/admin/changelog-delete", dependencies=[Depends(require_admin)])
def delete_note(payload: DeleteNoteRequest, db: Session = Depends(get_db)):
    raw = str(payload.note_id).strip().lower().removeprefix("note-")
    if not raw.isdigit():
        raise HTTPException(status_code=400, detail="Identifiant invalide (ex. note-3). Les entrées écrites dans le code ne se suppriment pas d'ici.")
    note = db.get(ChangelogNote, int(raw))
    if not note:
        raise HTTPException(status_code=404, detail="Note introuvable")
    out = _note_out(note)
    db.delete(note)
    db.commit()
    return {"status": "ok", "deleted": out}


@router.get("/admin/changelog", dependencies=[Depends(require_admin)])
def admin_notes(db: Session = Depends(get_db)):
    """Les notes ajoutées depuis l'administration (pour retrouver l'identifiant à supprimer)."""
    return [_note_out(n) for n in db.query(ChangelogNote).order_by(ChangelogNote.id.desc()).all()]
