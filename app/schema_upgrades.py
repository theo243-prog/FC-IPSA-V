"""
Mises à jour automatiques de la structure de la base au démarrage du serveur.

`Base.metadata.create_all` crée les tables qui manquent mais n'ajoute pas une colonne à une table qui existe déjà.
Chaque colonne ajoutée après coup est donc déclarée ici : au démarrage, on l'ajoute si elle est absente.
Sans effet (et sans risque) si elle existe déjà ; aucune donnée n'est modifiée ni supprimée.
Aucune commande à lancer et aucun changement de « Start Command » dans Railway.
"""
from sqlalchemy import inspect, text

# valeurs ajoutées à l'énumération des raretés (cartes.tier) : les éditions limitées
NEW_TIER_VALUES = ["halloween", "noel"]

# (table, colonne, type SQL)
NEW_COLUMNS = [
    ("players", "tier_photos", "TEXT"),      # photos propres à une rareté (JSON)
    ("pack_states", "ultra_pack_tokens", "INTEGER NOT NULL DEFAULT 0"),      # jetons du pack ultra
]


def ensure_schema(engine) -> list:
    added = []
    insp = inspect(engine)
    for table, column, sql_type in NEW_COLUMNS:
        if table not in insp.get_table_names():
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE "%s" ADD COLUMN "%s" %s' % (table, column, sql_type)))
            added.append(table + "." + column)
        except Exception as exc:               # un autre processus vient de l'ajouter : sans importance
            if column not in {c["name"] for c in inspect(engine).get_columns(table)}:
                raise exc
    added += _ensure_tier_values(engine)
    if added:
        print("Ajouts à la base :", ", ".join(added))
    return added


def _ensure_tier_values(engine) -> list:
    """PostgreSQL range les raretés dans un type énuméré : on y ajoute les nouvelles valeurs si elles manquent
    (opération sans risque, qui ne touche à aucune carte). Inutile avec SQLite."""
    if engine.dialect.name != "postgresql" or "cards" not in inspect(engine).get_table_names():
        return []
    added = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        type_name = conn.execute(text(
            "SELECT t.typname FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid JOIN pg_type t ON a.atttypid = t.oid "
            "WHERE c.relname = 'cards' AND a.attname = 'tier'")).scalar()
        if not type_name:
            return []
        have = {r[0] for r in conn.execute(text("SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid WHERE t.typname = :n"), {"n": type_name})}
        for value in NEW_TIER_VALUES:
            if value not in have:
                conn.execute(text('ALTER TYPE "%s" ADD VALUE IF NOT EXISTS \'%s\'' % (type_name, value)))
                added.append("rareté " + value)
    return added
