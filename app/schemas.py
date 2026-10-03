"""
Migration ponctuelle :
- ajoute les colonnes de stats de saison + notes par poste sur players
- crée les tables matches / match_goals / match_assists si elles n'existent pas
Ne supprime et ne touche à aucune donnée existante.

    python -m app.migrate_add_stats_and_matches
"""
from sqlalchemy import text
from .database import Base, engine
from . import models  # noqa: F401 — nécessaire pour enregistrer Match/MatchGoal/MatchAssist

NEW_PLAYER_COLUMNS = [
    ("matches_joues", "INTEGER NOT NULL DEFAULT 0"),
    ("buts", "INTEGER NOT NULL DEFAULT 0"),
    ("passes_decisives", "INTEGER NOT NULL DEFAULT 0"),
    ("cartons_jaunes", "INTEGER NOT NULL DEFAULT 0"),
    ("cartons_rouges", "INTEGER NOT NULL DEFAULT 0"),
    ("homme_du_match_count", "INTEGER NOT NULL DEFAULT 0"),
    ("note_attaquant", "INTEGER NOT NULL DEFAULT 50"),
    ("note_milieu", "INTEGER NOT NULL DEFAULT 50"),
    ("note_defenseur", "INTEGER NOT NULL DEFAULT 50"),
    ("note_gardien", "INTEGER NOT NULL DEFAULT 50"),
]


def migrate():
    with engine.begin() as conn:
        for name, decl in NEW_PLAYER_COLUMNS:
            conn.execute(text(f"ALTER TABLE players ADD COLUMN IF NOT EXISTS {name} {decl}"))
    Base.metadata.create_all(bind=engine)  # crée matches/match_goals/match_assists s'ils manquent
    print("OK : stats de saison + tables de matchs en place.")


if __name__ == "__main__":
    migrate()
