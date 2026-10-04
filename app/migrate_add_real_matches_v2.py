"""
Migration ponctuelle :
- matches : de quoi annuler proprement un match réel (joueurs présents, cartons, cartes épiques créées)
- upcoming_matches : table des prochains matchs réels
Ne supprime ni ne modifie aucune donnée existante.

    python -m app.migrate_add_real_matches_v2
"""
from sqlalchemy import text
from .database import Base, engine
from . import models  # noqa: F401 — enregistre UpcomingMatch auprès de Base.metadata

COLUMNS = ["lineup_json", "yellow_json", "red_json", "epics_json"]


def migrate():
    with engine.begin() as conn:
        for column in COLUMNS:
            conn.execute(text("ALTER TABLE matches ADD COLUMN IF NOT EXISTS " + column + " TEXT"))
    Base.metadata.create_all(bind=engine)
    print("OK : matchs réels à venir et annulation de match en place.")


if __name__ == "__main__":
    migrate()
