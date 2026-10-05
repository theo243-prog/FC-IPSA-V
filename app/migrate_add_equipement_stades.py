"""
Migration ponctuelle : stades (colonnes de la table matches) et cartes Équipement (table proposal_equipment).
Ne supprime ni ne modifie aucune donnée existante.

    python -m app.migrate_add_equipement_stades
"""
from sqlalchemy import text
from .database import Base, engine
from . import models  # noqa: F401 — enregistre ProposalEquipment auprès de Base.metadata


def migrate():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS stade TEXT"))
        conn.execute(text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS stade_created BOOLEAN DEFAULT FALSE"))
    Base.metadata.create_all(bind=engine)
    print("OK : stades et cartes Équipement prêts.")


if __name__ == "__main__":
    migrate()
