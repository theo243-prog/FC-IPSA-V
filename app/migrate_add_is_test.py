"""
Migration ponctuelle : ajoute la colonne is_test à la table users.
À lancer UNE SEULE FOIS (ne touche à rien d'autre, ne supprime aucune donnée) :

    python -m app.migrate_add_is_test
"""
from sqlalchemy import text
from .database import engine


def migrate():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false"))
    print("OK : colonne is_test présente sur la table users.")


if __name__ == "__main__":
    migrate()
