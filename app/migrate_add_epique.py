"""
Migration ponctuelle : ajoute la rareté "epique" au type énuméré des cartes.
Ne supprime ni ne modifie aucune donnée existante.

    python -m app.migrate_add_epique
"""
from sqlalchemy import text
from .database import engine


def migrate():
    if engine.dialect.name != "postgresql":
        print("Base non-PostgreSQL (SQLite local) : rien à faire.")
        return

    # AUTOCOMMIT : ALTER TYPE ... ADD VALUE ne doit pas tourner dans une transaction classique
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        # on retrouve le nom exact du type utilisé par la colonne cards.tier
        type_name = conn.execute(text(
            "SELECT t.typname FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid = c.oid "
            "JOIN pg_type t ON a.atttypid = t.oid "
            "WHERE c.relname = 'cards' AND a.attname = 'tier'"
        )).scalar()
        if not type_name:
            raise RuntimeError("Colonne cards.tier introuvable")
        conn.execute(text('ALTER TYPE "' + type_name + '" ADD VALUE IF NOT EXISTS \'epique\''))
    print("OK : rareté 'epique' disponible.")


if __name__ == "__main__":
    migrate()
