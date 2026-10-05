"""
Migration ponctuelle : nouvelles raretés (gold, secrete, speciale), notes des cartes spéciales, emplacement Loup,
moments mémorables, tâche du vendredi 17h, et mascotte au nouveau format. Les cartes secrètes de tous les joueurs,
fans et de la mascotte sont créées. Ne supprime aucune donnée existante.

    python -m app.migrate_add_raretes_v3
"""
from sqlalchemy import text
from .database import Base, engine, SessionLocal
from . import models  # noqa: F401 — enregistre MatchMoment et JobRun auprès de Base.metadata
from .game_logic import ensure_secret_cards


def migrate():
    if engine.dialect.name == "postgresql":
        # AUTOCOMMIT : ALTER TYPE ... ADD VALUE ne doit pas tourner dans une transaction classique
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            type_name = conn.execute(text(
                "SELECT t.typname FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid "
                "JOIN pg_type t ON a.atttypid = t.oid WHERE c.relname = 'cards' AND a.attname = 'tier'"
            )).scalar()
            if not type_name:
                raise RuntimeError("Colonne cards.tier introuvable")
            for value in ("gold", "secrete", "speciale"):
                conn.execute(text('ALTER TYPE "' + type_name + '" ADD VALUE IF NOT EXISTS \'' + value + '\''))
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE cards ADD COLUMN IF NOT EXISTS note INTEGER"))
        conn.execute(text("ALTER TABLE match_proposals ADD COLUMN IF NOT EXISTS mascot_card_id VARCHAR REFERENCES cards(id)"))
        # la mascotte n'est plus un « Fan » : elle a son propre emplacement
        conn.execute(text("UPDATE players SET poste = 'MASCOTTE' WHERE UPPER(poste) LIKE 'FAN/MASCOTTE%'"))
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        created = ensure_secret_cards(db)
    finally:
        db.close()
    print("OK : nouvelles raretés prêtes, %d carte(s) secrète(s) créée(s)." % created)


if __name__ == "__main__":
    migrate()
