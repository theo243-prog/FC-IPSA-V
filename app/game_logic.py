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
# Probas par carte tirée dans un pack classique. Les cartes secrètes n'y sont JAMAIS (fusion uniquement) et les
# spéciales n'existent que dans les packs match.
TIER_WEIGHTS = {"commune": 68, "rare": 19, "gold": 6, "epique": 5, "legendaire": 2}
# (une rareté dont aucune carte n'existe encore est ignorée au tirage, les autres se rééquilibrent)

# Nombre de cartes à partir duquel une rareté atteint sa probabilité "pleine".
# En dessous, sa probabilité est réduite proportionnellement : avec peu de cartes
# épiques/légendaires, chacune ne tombe jamais plus souvent qu'avec le nombre de référence.
TIER_REF_COUNT = {"gold": 6, "speciale": 3, "epique": 6, "legendaire": 4}

# Les spéciales ont les mêmes valeurs que les épiques.
DUPLICATE_SELL_VALUE = {"commune": 1, "rare": 3, "gold": 4, "secrete": 5, "speciale": 4, "epique": 4, "legendaire": 5}

# Ordre de rareté, de la plus commune à la plus rare.
TIER_ORDER = ["commune", "rare", "gold", "secrete", "speciale", "epique", "legendaire"]

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
    # Récompense des victoires en 1v1 : pas en vente (price None). Un peu mieux que le pack classique pour CHAQUE rareté
    # (rare 27 contre 19, gold 7 contre 6, épique 6 contre 5, légendaire 3 contre 2), et le seul où sortent les spéciales.
    "match": {"label": "Pack match", "price": None, "guaranteed": [],
              "token_field": "match_pack_tokens",
              "weights": {"commune": 52, "rare": 27, "gold": 7, "speciale": 5, "epique": 6, "legendaire": 3},
              "description": "3 cartes avec un peu plus de chances de rares que le pack classique, et le seul pack où sortent les cartes spéciales"},
}

# Plus aucun craft automatique : les doublons ne servent qu'à être revendus ou à remplir la jauge de la carte secrète.

# Fusion vers la carte SECRÈTE d'un joueur / fan / mascotte : 100 « points » de doublons.
# Un doublon commune vaut 1 point, un doublon rare en vaut 5.
SECRET_FUSION_COST = 100
RARE_FUSION_VALUE = 5


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

    return {"credits_won": credits_won, "cards_won": cards_won, "new_flags": new_flags,
            "crafted": [], "source": source, "pack_type": effective}


# ---------------------------------------------------------------------
# Notes des cartes : UNE seule note par carte, déterminée par sa rareté
# (plus de notes par poste). Réutilisée par le moteur de duel.
# ---------------------------------------------------------------------

CARD_NOTE = {"commune": 75, "rare": 85, "secrete": 90, "legendaire": 95}
SPECIAL_BASE_NOTE = 80      # note d'une carte spéciale à sa création ; +1 à chaque nouvelle récompense
TIER_FAN_BONUS = {"commune": 0.05, "rare": 0.10, "epique": 0.12, "secrete": 0.13, "legendaire": 0.15}  # bonus % apporté par le Fan
TIER_MASCOT_BONUS = dict(TIER_FAN_BONUS)       # la mascotte (Le Loup) a son propre emplacement, mêmes bonus que le Fan

# Cartes Équipement : un bonus d'équipe en 1v1, qui s'ajoute à ceux du Fan et du Loup. Un seul équipement par équipe.
TIER_EQUIPMENT_BONUS = {"commune": 0.01, "rare": 0.02, "epique": 0.03, "legendaire": 0.05}
MAX_EQUIPMENT = 1

# Les cartes "qui ne sont pas des joueurs" sont repérées par leur poste (comme les Fans) :
#   FAN... -> supporter / mascotte ; EQUIPEMENT -> équipement ; STADE -> stade ; autre -> joueur.
def card_kind(player) -> str:
    poste = (player.poste or "").upper()
    if poste == "MASCOTTE" or poste.startswith("FAN/MASCOTTE"):     # (l'ancien format FAN/Mascotte est reconnu aussi)
        return "mascotte"
    if poste.startswith("FAN"):
        return "fan"
    if poste == "EQUIPEMENT":
        return "equipement"
    if poste == "STADE":
        return "stade"
    if poste == "MOMENT":
        return "moment"
    return "joueur"


def is_fan(player) -> bool:
    return card_kind(player) == "fan"


def is_mascot(player) -> bool:
    return card_kind(player) == "mascotte"


def has_secret_card(player) -> bool:
    """Chaque joueur, fan et la mascotte ont leur carte secrète (pas les équipements, stades ni moments gold)."""
    return card_kind(player) in ("joueur", "fan", "mascotte")


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

# Carte épique (buteurs) : 85 au premier but de la saison, puis +2 par but supplémentaire (un but = +2 sur la carte).
EPIC_BASE_NOTE = 85
EPIC_NOTE_PER_EXTRA_GOAL = 2


def card_note(player: Player, tier: str, card=None) -> int:
    """La note d'une carte : fixe selon la rareté ; l'épique grimpe avec les buts du joueur ;
    la spéciale vaut 80 au départ puis +1 à chaque nouvelle récompense (valeur stockée sur la carte)."""
    if tier == "epique":
        return EPIC_BASE_NOTE + EPIC_NOTE_PER_EXTRA_GOAL * max(0, (player.buts or 0) - 1)
    if tier == "speciale":
        return (card.note if card is not None and card.note else SPECIAL_BASE_NOTE)
    return CARD_NOTE.get(tier, 75)


def get_display_note(player: Player, tier: str = "commune", card=None):
    """Note affichée sur la carte. Seuls les joueurs ont une note : Fans et équipements donnent un bonus,
    les stades n'ont ni note ni bonus."""
    if card_kind(player) != "joueur":
        return None
    return {"label": "NOTE", "value": card_note(player, tier, card)}


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


# ---------------------------------------------------------------------
# Cartes SECRÈTES : une par joueur / fan / mascotte, jamais dans les packs.
# Elles se débloquent en fusionnant des doublons de communes (1 point) et de rares (5 points) du même joueur.
# ---------------------------------------------------------------------

def ensure_secret_cards(db: Session) -> int:
    """Crée la carte secrète manquante de chaque joueur / fan / mascotte. Retourne le nombre créé."""
    created = 0
    for player in db.query(Player).all():
        if not has_secret_card(player):
            continue
        if db.query(Card).filter_by(player_id=player.id, tier=Tier.secrete).first() is None:
            db.add(Card(player_id=player.id, tier=Tier.secrete, vitesse=0, tir=0))
            created += 1
    if created:
        db.commit()
    return created


def fusion_points(commune_qty: int, rare_qty: int) -> int:
    """Points de fusion : seuls les DOUBLONS comptent (le premier exemplaire de chaque carte reste au joueur)."""
    return max(0, commune_qty - 1) + RARE_FUSION_VALUE * max(0, rare_qty - 1)


def fusion_state(db: Session, user: User, card: Card) -> dict:
    """Progression d'un joueur vers la carte secrète `card`."""
    qty = {}
    for tier in (Tier.commune, Tier.rare):
        c = db.query(Card).filter_by(player_id=card.player_id, tier=tier).first()
        o = db.query(OwnedCard).filter_by(user_id=user.id, card_id=c.id).first() if c else None
        qty[tier.value] = o.quantity if o else 0
    points = fusion_points(qty["commune"], qty["rare"])
    return {"points": points, "needed": SECRET_FUSION_COST, "ready": points >= SECRET_FUSION_COST,
            "commune_dupes": max(0, qty["commune"] - 1), "rare_dupes": max(0, qty["rare"] - 1)}


def unlock_secret(db: Session, user: User, card_id: str) -> dict:
    """Débloque une carte secrète en consommant des doublons : d'abord les communes, puis les rares
    (5 points chacune) pour compléter. Lève ValueError("not_secret" | "already_owned" | "not_enough")."""
    card = db.get(Card, card_id)
    if card is None or card.tier != Tier.secrete:
        raise ValueError("not_secret")
    owned_secret = get_or_create_owned(db, user, card)
    if owned_secret.quantity > 0:
        raise ValueError("already_owned")
    state = fusion_state(db, user, card)
    if not state["ready"]:
        raise ValueError("not_enough")
    need = SECRET_FUSION_COST
    used = {"commune": 0, "rare": 0}
    commune_card = db.query(Card).filter_by(player_id=card.player_id, tier=Tier.commune).first()
    rare_card = db.query(Card).filter_by(player_id=card.player_id, tier=Tier.rare).first()
    if commune_card:
        o = db.query(OwnedCard).filter_by(user_id=user.id, card_id=commune_card.id).first()
        take = min(need, max(0, (o.quantity if o else 0) - 1))
        if take:
            o.quantity -= take; used["commune"] = take; need -= take
    if need > 0 and rare_card:
        o = db.query(OwnedCard).filter_by(user_id=user.id, card_id=rare_card.id).first()
        take = -(-need // RARE_FUSION_VALUE)                       # on arrondit au-dessus
        o.quantity -= take; used["rare"] = take; need = 0
    owned_secret.quantity = 1
    db.commit()
    return {"card_id": card.id, "player": card.player.name, "used": used}


# ---------------------------------------------------------------------
# Règles exposées au site (page d'aide) : les % de tirage sont calculés EN DIRECT, avec les cartes qui existent.
# ---------------------------------------------------------------------

def _percent(weights: dict) -> dict:
    total = sum(weights.values())
    return {k: round(100 * w / total, 1) for k, w in weights.items()} if total else {}


def pack_odds(db: Session) -> dict:
    """Pour chaque type de pack : les cartes garanties et la chance de chaque rareté pour les autres cartes."""
    counts = tier_card_counts(db)
    packs = {}
    for key, spec in PACK_TYPES.items():
        base = spec.get("weights") or TIER_WEIGHTS
        packs[key] = {
            "label": spec["label"], "price": spec["price"], "description": spec["description"],
            "guaranteed": list(spec["guaranteed"]), "available": pack_available(counts, key),
            "odds": _percent(classic_tier_weights(counts, base)),          # réel (rareté sans carte ignorée, rareté récente réduite)
            "nominal": _percent(base),                                      # théorique, avec toutes les raretés présentes
        }
    return {"counts": counts, "packs": packs, "never_in_packs": ["secrete"],
            "sell_values": DUPLICATE_SELL_VALUE, "secret_fusion": {"cost": SECRET_FUSION_COST, "rare_value": RARE_FUSION_VALUE},
            "tier_order": TIER_ORDER, "free_packs_max": MAX_STORED_PACKS, "free_pack_hours": PACK_REGEN_SECONDS // 3600}


# ---------------------------------------------------------------------
# Postes : une faute de frappe ne doit pas casser une carte.
# ---------------------------------------------------------------------
VALID_POSTES = ("ATT", "MC", "DEF", "GB", "X", "FAN")
RESERVED_POSTES = ("MASCOTTE", "EQUIPEMENT", "STADE", "MOMENT")


def normalize_poste(raw: str) -> str:
    """Met un poste au bon format (majuscules, sans espaces en trop) ou lève ValueError avec un message clair.
    Accepte ATT, MC, DEF, GB, X, FAN, et FAN/<rôle> (ex. « FAN/Responsable com »)."""
    text = " ".join((raw or "").split())
    head, _, role = text.partition("/")
    head = head.strip().upper()
    if head in RESERVED_POSTES:
        raise ValueError("« %s » est réservé : les mascottes, équipements et stades se créent avec leur propre commande" % head)
    if head not in VALID_POSTES:
        raise ValueError("Poste « %s » invalide : choisis parmi ATT, MC, DEF, GB, X (pas encore défini) ou FAN" % (raw or "").strip())
    if role.strip():
        if head != "FAN":
            raise ValueError("Seul FAN accepte un rôle (ex. FAN/Responsable com)")
        return "FAN/" + role.strip()
    return head


# ---------------------------------------------------------------------
# Photos : une photo par défaut pour le joueur, et au besoin une photo différente pour une rareté donnée.
# La photo d'une rareté peut être enregistrée AVANT que la carte existe (ex. la carte spéciale du vendredi).
# ---------------------------------------------------------------------

def tier_photos(player) -> dict:
    import json
    try:
        data = json.loads(player.tier_photos) if player.tier_photos else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def photo_for(player, tier: str):
    """La photo à afficher sur la carte (joueur, rareté) : celle de la rareté si elle existe, sinon celle du joueur."""
    return tier_photos(player).get(tier) or player.photo_url or None


def set_tier_photo(player, tier: str, url: str) -> None:
    """Enregistre (url non vide) ou retire (url vide) la photo propre à une rareté."""
    import json
    data = tier_photos(player)
    if url:
        data[tier] = url
    else:
        data.pop(tier, None)
    player.tier_photos = json.dumps(data, ensure_ascii=False) if data else None
