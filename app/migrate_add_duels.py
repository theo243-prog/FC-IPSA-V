"""
Migration ponctuelle :
- ajoute la colonne elo sur users
- crée les tables teams / team_slots / duels si elles n'existent pas
Ne supprime et ne touche à aucune donnée existante.

    python -m app.migrate_add_duels
"""
from sqlalchemy import text
from .database import Base, engine
from . import models  # noqa: F401 — enregistre Team/TeamSlot/Duel auprès de Base.metadata


def migrate():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS elo INTEGER NOT NULL DEFAULT 1000"))
    Base.metadata.create_all(bind=engine)
    print("OK : elo + tables de matchs 1v1 en place.")


if __name__ == "__main__":
    migrate()
