"""
Migration ponctuelle : ajoute les jetons de pack rare / épique / légendaire.
Ne supprime ni ne modifie aucune donnée existante (les jetons actuels
deviennent les jetons de pack classique).

    python -m app.migrate_add_pack_tokens
"""
from sqlalchemy import text
from .database import engine

NEW_COLUMNS = ["rare_pack_tokens", "epic_pack_tokens", "legendary_pack_tokens"]


def migrate():
    with engine.begin() as conn:
        for name in NEW_COLUMNS:
            conn.execute(text(
                "ALTER TABLE pack_states ADD COLUMN IF NOT EXISTS " + name + " INTEGER NOT NULL DEFAULT 0"
            ))
    print("OK : jetons de pack rare/épique/légendaire en place.")


if __name__ == "__main__":
    migrate()
