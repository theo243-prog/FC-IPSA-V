"""
Toutes les règles du jeu, isolées ici pour que les routes de l'API restent
simples. Rien ici ne touche au HTTP — uniquement de la logique + la base.
"""
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import User, Card, OwnedCard, Tier

PACK_REGEN_SECONDS = 8 * 3600          # 8h pour régénérer un pack gratuit
MAX_STORED_PACKS = 3                   # jamais plus de 3 packs gratuits en stock

CREDIT_WEIGHTS = {1: 40, 2: 25, 3: 18, 4: 12, 5: 5}         # plus le nombre est grand, plus c'est rare
TIER_WEIGHTS = {"commune": 80, "rare": 18, "legendaire": 2}  # probas par carte tirée dans un pack

DUPLICATE_SELL_VALUE = {"commune": 1, "rare": 3, "legendaire": 5}

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


def open_pack_for_user(db: Session, user: User, use_shop_token: bool = False) -> dict:
    """
    Ouvre un pack : consomme un pack gratuit (ou un jeton de shop si demandé et
    disponible), tire les crédits puis les 3 cartes, applique les crafts.
    Lève ValueError("no_pack_available") si le joueur n'a rien à ouvrir.
    """
    regen_user_packs(db, user)
    ps = user.pack_state

    if use_shop_token:
        if ps.shop_pack_tokens <= 0:
            raise ValueError("no_pack_available")
        ps.shop_pack_tokens -= 1
        source = "shop"
    else:
        if ps.stored_packs <= 0:
            raise ValueError("no_pack_available")
        ps.stored_packs -= 1
        source = "free"

    credits_won = int(_roll_weighted(CREDIT_WEIGHTS))
    user.credits += credits_won

    available_tiers = dict(TIER_WEIGHTS)
    if db.query(Card).filter_by(tier=Tier.legendaire).count() == 0:
        available_tiers.pop("legendaire", None)  # aucune légendaire n'existe encore cette saison

    cards_won = []
    for _ in range(3):
        tier = Tier(_roll_weighted(available_tiers))
        pool = db.query(Card).filter_by(tier=tier).all()
        card = random.choice(pool)
        owned = get_or_create_owned(db, user, card)
        owned.quantity += 1
        cards_won.append(card)

    db.commit()
    crafted = apply_crafts(db, user)

    return {"credits_won": credits_won, "cards_won": cards_won, "crafted": crafted, "source": source}


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
