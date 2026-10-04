"""
Migration ponctuelle pour le 1v1 à 5 joueurs :
- jetons de "pack match" (récompense des victoires)
- nouvelles colonnes sur duels (tactiques, chronologie, compositions)
- nouvelles tables match_proposals / proposal_slots
Ne supprime ni ne modifie aucune donnée existante.

    python -m app.migrate_add_duel_v2
"""
from sqlalchemy import text
from .database import Base, engine
from . import models  # noqa: F401 — enregistre les nouvelles tables auprès de Base.metadata

COLUMNS = [
    ("pack_states", "match_pack_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("duels", "tactic_challenger", "VARCHAR"),
    ("duels", "tactic_defender", "VARCHAR"),
    ("duels", "events_json", "TEXT"),
    ("duels", "lineups_json", "TEXT"),
]


def migrate():
    with engine.begin() as conn:
        for table, column, decl in COLUMNS:
            conn.execute(text("ALTER TABLE " + table + " ADD COLUMN IF NOT EXISTS " + column + " " + decl))
    Base.metadata.create_all(bind=engine)  # crée match_proposals / proposal_slots s'ils manquent
    print("OK : base prête pour le 1v1 à 5 joueurs.")


if __name__ == "__main__":
    migrate()
