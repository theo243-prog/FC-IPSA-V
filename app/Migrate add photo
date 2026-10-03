"""
Migration ponctuelle : ajoute la colonne photo_url à la table players.
À lancer UNE SEULE FOIS (ne touche à rien d'autre, ne supprime aucune donnée) :

    python -m app.migrate_add_photo
"""
from sqlalchemy import text
from .database import engine


def migrate():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE players ADD COLUMN IF NOT EXISTS photo_url VARCHAR"))
    print("OK : colonne photo_url présente sur la table players.")


if __name__ == "__main__":
    migrate()
