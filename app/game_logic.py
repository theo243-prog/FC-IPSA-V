"""
Toutes les règles du jeu, isolées ici pour que les routes de l'API restent
simples. Rien ici ne touche au HTTP — uniquement de la logique + la base.
"""
import random
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import User, Card, OwnedCard, Tier, Player

PACK_REGEN_SECONDS = 8 * 3600          # 8h pour régénérer un pack gratuit
MAX_STORED_PACKS = 3                   # jamais plus de 3 packs gratuits en stock

CREDIT_WEIGHTS = {1: 40, 2: 25, 3: 18, 4: 12, 5: 5}         # plus le nombre est grand, plus c'est rare
TIER_WEIGHTS = {"commune": 72, "rare": 20, "epique": 6, "legendaire": 2}  # probas par carte tirée dans un pack
# (une rareté dont aucune carte n'existe encore est ignorée au tirage, les autres se rééquilibrent)

# Nombre de cartes à partir duquel une rareté atteint sa probabilité "pleine".
# En dessous, sa probabilité est réduite proportionnellement : avec peu de cartes
# épiques/légendaires, chacune ne tombe jamais plus souvent qu'avec le nombre de référence.
TIER_REF_COUNT = {"epique": 6, "legendaire": 4}

DUPLICATE_SELL_VALUE = {"commune": 1, "rare": 3, "epique": 4, "legendaire": 5}

# Types de packs. "guaranteed" = raretés garanties ; les autres cartes (jusqu'à 3) suivent les probas classiques.
PACK_TYPES = {
    "classique": {"label": "Pack classique", "price": 10, "guaranteed": [],
                  "token_field": "shop_pack_tokens",
                  "description": "3 cartes aux probabilités classiques"},
    "rare": {"label": "Pack rare", "price": 20, "guaranteed": ["rare", "rare"],
             "token_field": "rare_pack_tokens",
             "description": "2 cartes rares garanties + 1 carte aux probabilités classiques"},
    "epique": {"label": "Pack épique", "price": 50, "guaranteed": ["epique"],
               "token_field": "epic_pack_tokens",
               "description": "1 carte épique garantie + 2 cartes aux probabilités classiques"},
    "legendaire": {"label": "Pack légendaire", "price": 100, "guaranteed": ["legendaire"],
                   "token_field": "legendary_pack_tokens",
                   "description": "1 carte légendaire garantie + 2 cartes aux probabilités classiques"},
    # Récompense des victoires en 1v1 : pas en vente (price None), probabilités boostées.
    "match": {"label": "Pack match", "price": None, "guaranteed": [],
              "token_field": "match_pack_tokens",
              "weights": {"commune": 45, "rare": 35, "epique": 14, "legendaire": 6},
              "description": "3 cartes avec des chances boostées d'obtenir des rares, épiques et légendaires"},
}

CRAFT_THRESHOLD = 10   # nombre de DOUBLONS (en plus du premier) nécessaires pour le craft
LEGENDARY_BONUS = 12   # points de stats ajoutés par rapport à la carte rare, pour une légendaire auto-créée


def _roll_weighted(weights: dict) -> str:
    total = sum(weights.values())
    r = random.uniform(0, total)
    upto = 0.0
    for key, w in weights.items():
        upto += w
        if r <= upto:
            return key
    return next(iter(weights))  # filet de sécurité, ne devrait jamais arriver


def regen_user_packs(db: Session, user: User) -> None:
    """Met à jour le nombre de packs gratuits en stock en fonction du temps écoulé."""
    ps = user.pack_state
    now = datetime.utcnow()

    if ps.stored_packs >= MAX_STORED_PACKS:
        ps.last_regen_at = now  # on ne fait pas "stocker" du temps au-delà du cap
        db.commit()
        return

    elapsed = (now - ps.last_regen_at).total_seconds()
    gained = int(elapsed // PACK_REGEN_SECONDS)
    if gained > 0:
        ps.stored_packs = min(MAX_STORED_PACKS, ps.stored_packs + gained)
        ps.last_regen_at = ps.last_regen_at + timedelta(seconds=gained * PACK_REGEN_SECONDS)
        if ps.stored_packs >= MAX_STORED_PACKS:
            ps.last_regen_at = now
        db.commit()


def seconds_until_next_pack(user: User) -> int | None:
    """None si le joueur est déjà au max (3), sinon le nombre de secondes avant le prochain."""
    ps = user.pack_state
    if ps.stored_packs >= MAX_STORED_PACKS:
        return None
    elapsed = (datetime.utcnow() - ps.last_regen_at).total_seconds()
    remaining = PACK_REGEN_SECONDS - elapsed
    return max(0, int(remaining))


def get_or_create_owned(db: Session, user: User, card: Card) -> OwnedCard:
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card.id).first()
    if not owned:
        owned = OwnedCard(user_id=user.id, card_id=card.id, quantity=0)
        db.add(owned)
        db.flush()
    return owned


def apply_crafts(db: Session, user: User) -> list[dict]:
    """
    Vérifie tous les doublons du joueur et applique les crafts automatiques :
    - 10 doublons d'une carte commune -> débloque (consomme 10) la carte rare du même joueur
    - 10 doublons d'une carte rare    -> débloque (consomme 10) la carte légendaire du même joueur
      (créée à la volée si elle n'existe pas encore)
    Retourne la liste des crafts effectués, pour affichage côté frontend.
    """
    crafted = []

    # Commune -> Rare
    commune_dupes = (
        db.query(OwnedCard)
        .join(Card)
        .filter(OwnedCard.user_id == user.id, Card.tier == Tier.commune, OwnedCard.quantity >= CRAFT_THRESHOLD + 1)
        .all()
    )
    for owned in commune_dupes:
        rare_card = db.query(Card).filter_by(player_id=owned.card.player_id, tier=Tier.rare).first()
        if not rare_card:
            continue
        rare_owned = get_or_create_owned(db, user, rare_card)
        while owned.quantity >= CRAFT_THRESHOLD + 1 and rare_owned.quantity == 0:
            owned.quantity -= CRAFT_THRESHOLD
            rare_owned.quantity += 1
            crafted.append({"type": "rare_debloquee", "player": owned.card.player.name})
            break  # une seule fois : au-delà, le joueur garde ses doublons restants normalement

    # Rare -> Légendaire
    rare_dupes = (
        db.query(OwnedCard)
        .join(Card)
        .filter(OwnedCard.user_id == user.id, Card.tier == Tier.rare, OwnedCard.quantity >= CRAFT_THRESHOLD + 1)
        .all()
    )
    for owned in rare_dupes:
        legend_card = db.query(Card).filter_by(player_id=owned.card.player_id, tier=Tier.legendaire).first()
        if not legend_card:
            legend_card = Card(
                player_id=owned.card.player_id,
                tier=Tier.legendaire,
                vitesse=min(99, owned.card.vitesse + LEGENDARY_BONUS),
                tir=min(99, owned.card.tir + LEGENDARY_BONUS),
            )
            db.add(legend_card)
            db.flush()
        legend_owned = get_or_create_owned(db, user, legend_card)
        if owned.quantity >= CRAFT_THRESHOLD + 1:
            owned.quantity -= CRAFT_THRESHOLD
            legend_owned.quantity += 1
            crafted.append({"type": "legendaire_debloquee", "player": owned.card.player.name})

    if crafted:
        db.commit()
    return crafted


def tier_card_counts(db: Session) -> dict:
    """Nombre de cartes existantes par rareté, ex. {"commune": 24, "rare": 24, "epique": 1}."""
    rows = db.query(Card.tier, func.count(Card.id)).group_by(Card.tier).all()
    return {tier.value: n for tier, n in rows}


def classic_tier_weights(counts: dict, base_weights: dict = None) -> dict:
    """Probabilités de tirage : une rareté sans carte est ignorée, et les raretés récentes
    (épique, légendaire) sont réduites tant qu'elles ont peu de cartes.
    base_weights : poids de départ (classiques par défaut, boostés pour le pack match)."""
    weights = {}
    for name, weight in (base_weights or TIER_WEIGHTS).items():
        n = counts.get(name, 0)
        if n == 0:
            continue
        ref = TIER_REF_COUNT.get(name)
        if ref:
            weight = weight * min(1.0, n / ref)
        weights[name] = weight
    return weights


def pack_available(counts: dict, pack_type: str) -> bool:
    """Un pack à carte garantie n'est disponible que si la rareté garantie existe déjà."""
    return all(counts.get(t, 0) > 0 for t in set(PACK_TYPES[pack_type]["guaranteed"]))


def open_pack_for_user(db: Session, user: User, pack_type: str = "free") -> dict:
    """
    Ouvre un pack. pack_type : "free" (pack gratuit qui se régénère) ou un type de PACK_TYPES
    (consomme un jeton de ce type). Tire les crédits, puis 3 cartes (dont les cartes garanties
    du type de pack), applique les crafts.
    Lève ValueError("no_pack_available") / ValueError("tier_unavailable") / ValueError("unknown_pack").
    """
    effective = "classique" if pack_type == "free" else pack_type
    if effective not in PACK_TYPES:
        raise ValueError("unknown_pack")
    spec = PACK_TYPES[effective]

    regen_user_packs(db, user)
    ps = user.pack_state
    counts = tier_card_counts(db)

    # on vérifie AVANT de consommer quoi que ce soit que le pack peut tenir sa promesse
    if not pack_available(counts, effective):
        raise ValueError("tier_unavailable")

    if getattr(user, "is_test", False):
        source = "test"                      # compte de test : aucune limite, rien n'est décompté
    elif pack_type == "free":
        if ps.stored_packs <= 0:
            raise ValueError("no_pack_available")
        ps.stored_packs -= 1
        source = "free"
    else:
        field = spec["token_field"]
        if getattr(ps, field) <= 0:
            raise ValueError("no_pack_available")
        setattr(ps, field, getattr(ps, field) - 1)
        source = "shop"

    credits_won = int(_roll_weighted(CREDIT_WEIGHTS))
    user.credits += credits_won

    weights = classic_tier_weights(counts, spec.get("weights"))
    tiers_to_draw = list(spec["guaranteed"])
    while len(tiers_to_draw) < 3:
        tiers_to_draw.append(_roll_weighted(weights))
    random.shuffle(tiers_to_draw)

    cards_won = []
    new_flags = []
    for tier_name in tiers_to_draw:
        pool = db.query(Card).filter_by(tier=Tier(tier_name)).all()
        card = random.choice(pool)
        owned = get_or_create_owned(db, user, card)
        new_flags.append(owned.quantity == 0)   # première fois qu'on possède cette carte => NEW
        owned.quantity += 1
        cards_won.append(card)

    db.commit()
    crafted = apply_crafts(db, user)

    return {"credits_won": credits_won, "cards_won": cards_won, "new_flags": new_flags,
            "crafted": crafted, "source": source, "pack_type": effective}


# ---------------------------------------------------------------------
# Notes des cartes : UNE seule note par carte, déterminée par sa rareté
# (plus de notes par poste). Réutilisée par le moteur de duel.
# ---------------------------------------------------------------------

CARD_NOTE = {"commune": 75, "rare": 85, "legendaire": 95}
TIER_FAN_BONUS = {"commune": 0.05, "rare": 0.10, "epique": 0.12, "legendaire": 0.15}  # bonus % apporté par le Fan

# Cartes Équipement : un bonus d'équipe en 1v1, qui s'ajoute à celui du Fan. Jusqu'à MAX_EQUIPMENT par équipe.
TIER_EQUIPMENT_BONUS = {"commune": 0.01, "rare": 0.02, "epique": 0.03, "legendaire": 0.05}
MAX_EQUIPMENT = 3

# Les cartes "qui ne sont pas des joueurs" sont repérées par leur poste (comme les Fans) :
#   FAN... -> supporter / mascotte ; EQUIPEMENT -> équipement ; STADE -> stade ; autre -> joueur.
def card_kind(player) -> str:
    poste = (player.poste or "").upper()
    if poste.startswith("FAN"):
        return "fan"
    if poste == "EQUIPEMENT":
        return "equipement"
    if poste == "STADE":
        return "stade"
    return "joueur"


def is_fan(player) -> bool:
    return card_kind(player) == "fan"


def is_equipment(player) -> bool:
    return card_kind(player) == "equipement"


def is_stadium(player) -> bool:
    return card_kind(player) == "stade"


# Équipements créés par la commande admin /admin/create-equipment (nom, rareté).
EQUIPMENT_CATALOG = [
    ("Gourde", "commune"), ("Ballon du match", "commune"), ("Protège-tibias", "commune"),
    ("Chasuble", "commune"), ("Chaussettes trouées", "commune"), ("Banc de touche", "commune"),
    ("Galette-saucisse", "rare"), ("Enceinte JBL", "rare"), ("Trousse à pharmacie", "rare"), ("Tableau tactique", "rare"),
    ("Pack de bière", "epique"),
]

# Carte épique (buteurs) : 85 au premier but de la saison, puis +5 par but supplémentaire.
EPIC_BASE_NOTE = 85
EPIC_NOTE_PER_EXTRA_GOAL = 5


def card_note(player: Player, tier: str) -> int:
    """La note d'une carte : fixe selon la rareté, sauf l'épique qui grimpe avec les buts du joueur."""
    if tier == "epique":
        return EPIC_BASE_NOTE + EPIC_NOTE_PER_EXTRA_GOAL * max(0, (player.buts or 0) - 1)
    return CARD_NOTE.get(tier, 75)


def get_display_note(player: Player, tier: str = "commune"):
    """Note affichée sur la carte. Seuls les joueurs ont une note : Fans et équipements donnent un bonus,
    les stades n'ont ni note ni bonus."""
    if card_kind(player) != "joueur":
        return None
    return {"label": "NOTE", "value": card_note(player, tier)}


def sell_duplicate(db: Session, user: User, card_id: str) -> int:
    """Vend UN exemplaire en doublon d'une carte contre des crédits. Lève ValueError si pas de doublon."""
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card_id).first()
    if not owned or owned.quantity <= 1:
        raise ValueError("no_duplicate")
    value = DUPLICATE_SELL_VALUE[owned.card.tier.value]
    owned.quantity -= 1
    user.credits += value
    db.commit()
    return value
