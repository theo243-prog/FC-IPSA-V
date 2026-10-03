"""
Peuple la base avec les vrais joueurs et leurs cartes de départ (commune + rare).
À lancer une seule fois : `python -m app.seed_data`

Ce script REMET LA BASE À ZÉRO (toutes les tables sont effacées puis recréées)
avant de semer les joueurs. Volontaire pour l'instant car le jeu vient de
démarrer — à ne plus utiliser une fois que les gens ont de vraies collections
en cours, sous peine de tout perdre.

Les cartes légendaires ne sont PAS créées ici : elles seront ajoutées au
fil de la saison (but marqué, homme du match...) via un futur outil admin,
ou automatiquement via le craft (10 doublons rares d'un joueur).
"""
from .database import Base, engine, SessionLocal
from .models import Player, Card, Tier

# Les vrais joueurs (et supporters/staff) du FC Format A5.
# "X" = poste pas encore défini (à corriger plus tard, voir get_base_stats).
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

# Stats de base par poste précis, avant le bonus de rareté (vitesse, tir).
# "X" (poste pas encore défini) reçoit des stats neutres en attendant —
# il suffira de changer le poste ici et de relancer le seed pour corriger.
POSTE_BASE = {
    "GB":  (45, 30),
    "DD":  (62, 42), "DC": (58, 38), "DG": (62, 42),
    "MDC": (62, 55), "MC": (65, 58), "MOC": (64, 66),
    "AD":  (68, 70), "BU": (68, 74),
    "FAN": (50, 50),
    "X":   (60, 55),
}
DEFAULT_STATS = (55, 55)  # filet de sécurité si un poste inconnu apparaît un jour


def get_base_stats(poste: str):
    if poste in POSTE_BASE:
        return POSTE_BASE[poste]
    if poste.startswith("FAN"):
        return POSTE_BASE["FAN"]
    return DEFAULT_STATS


RARE_BONUS = 15  # points ajoutés aux stats de base pour la carte rare


def seed():
    # Remet la base à zéro : utile pour remplacer les 30 noms provisoires
    # par les vrais joueurs sans conflit d'anciens IDs.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        for name, poste in PLAYERS:
            base_v, base_t = get_base_stats(poste)
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
