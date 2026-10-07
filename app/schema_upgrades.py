"""
Mises à jour automatiques de la structure de la base au démarrage du serveur.

`Base.metadata.create_all` crée les tables qui manquent mais n'ajoute pas une colonne à une table qui existe déjà.
Chaque colonne ajoutée après coup est donc déclarée ici : au démarrage, on l'ajoute si elle est absente.
Sans effet (et sans risque) si elle existe déjà ; aucune donnée n'est modifiée ni supprimée.
Aucune commande à lancer et aucun changement de « Start Command » dans Railway.
"""
from sqlalchemy import inspect, text

# (table, colonne, type SQL)
NEW_COLUMNS = [
    ("players", "tier_photos", "TEXT"),      # photos propres à une rareté (JSON)
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
    if added:
        print("Colonnes ajoutées à la base :", ", ".join(added))
    return added
