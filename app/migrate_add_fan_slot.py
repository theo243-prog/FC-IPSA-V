"""
Migration ponctuelle : ajoute la colonne fan_card_id à la table teams
(emplacement optionnel pour une carte Fan apportant un bonus %).

    python -m app.migrate_add_fan_slot
"""
from sqlalchemy import text
from .database import engine


def migrate():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE teams ADD COLUMN IF NOT EXISTS fan_card_id VARCHAR"))
    print("OK : colonne fan_card_id présente sur la table teams.")


if __name__ == "__main__":
    migrate()
