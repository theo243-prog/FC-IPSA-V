"""
Peuple la base avec 30 joueurs et leurs cartes de départ (commune + rare).
À lancer une seule fois : `python -m app.seed_data`

Les cartes légendaires ne sont PAS créées ici : elles seront ajoutées au
fil de la saison (but marqué, homme du match...) via un futur outil admin.
"""
from .database import Base, engine, SessionLocal
from .models import Player, Card, Tier

# 30 prénoms provisoires — à remplacer par les vrais noms de l'équipe
PLAYERS = [
    ("Théo", "MDC"),
    ("Soël", "DD"),
    ("Nathalie", "FAN/Responsable com"),
    ("Alexi", "MC"),
    ("Emrys", "MOC"),
    ("Maël", "DC"),
    ("Côme", "AD"),
    ("Marco", "FAN"),
    ("Lucas", "X"),
    ("Thibaud", "GB"),
    ("Nicolas", "DG"),
    ("Mathis", "BU"),
    ("Léo", "X"),
    ("Gaëtan", "X"),
    ("Timothee", "X"),
    ("Clément", "X"),
    ("Eliott", "X"),
    ("Vincent", "X"),
    ("Yann", "X"),
    ("Matteo", "X"),
    ("Brice", "X"),
    ("Martin", "X"),
    ("Mathieu", "X"),
    ("Florent", "X"),
    ("Nathan", "X"),
    ("Fleur", "FAN"),
    ("Gabriel", "FAN"),
    ("Candice", "FAN"),
    ("Mathéo", "X"),
]

# Stats de base par poste, avant le bonus de rareté (vitesse, tir)
POSTE_BASE = {
    "GB":  (45, 30),
    "DEF": (60, 40),
    "MIL": (65, 60),
    "ATT": (68, 72),
}

RARE_BONUS = 15  # points ajoutés aux stats de base pour la carte rare


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Player).count() > 0:
            print("Des joueurs existent déjà, rien à faire.")
            return

        for name, poste in PLAYERS:
            base_v, base_t = POSTE_BASE[poste]
            player = Player(name=name, poste=poste)
            db.add(player)
            db.flush()  # pour récupérer player.id

            db.add(Card(player_id=player.id, tier=Tier.commune, vitesse=base_v, tir=base_t))
            db.add(Card(
                player_id=player.id, tier=Tier.rare,
                vitesse=min(99, base_v + RARE_BONUS),
                tir=min(99, base_t + RARE_BONUS),
            ))

        db.commit()
        print(f"{len(PLAYERS)} joueurs créés avec leurs cartes commune + rare.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
