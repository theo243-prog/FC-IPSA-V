"""
Toutes les règles du jeu, isolées ici pour que les routes de l'API restent
simples. Rien ici ne touche au HTTP — uniquement de la logique + la base.
"""
import math
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import User, Card, OwnedCard, Tier, Team, TeamSlot, Duel, Player

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

    if getattr(user, "is_test", False):
        # compte de test : aucune limite, rien n'est décompté
        source = "test"
    elif use_shop_token:
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


# ---------------------------------------------------------------------
# Notes affichées sur les cartes (déplacé ici depuis main.py pour être
# réutilisable par le moteur de duel sans import circulaire)
# ---------------------------------------------------------------------

POSTE_CATEGORY = {
    "GB": "gardien",
    "DEF": "defenseur", "DD": "defenseur", "DC": "defenseur", "DG": "defenseur",
    "MC": "milieu", "MDC": "milieu", "MOC": "milieu",
    "ATT": "attaquant", "AD": "attaquant", "BU": "attaquant",
}
CATEGORY_LABEL = {"attaquant": "ATT", "milieu": "MIL", "defenseur": "DEF", "gardien": "GB"}
TIER_NOTE_BONUS = {"commune": 0, "rare": 10, "legendaire": 20}


def get_display_note(player: Player, tier: str = "commune"):
    poste = player.poste or ""
    bonus = TIER_NOTE_BONUS.get(tier, 0)
    if poste in POSTE_CATEGORY:
        cat = POSTE_CATEGORY[poste]
        return {"label": CATEGORY_LABEL[cat], "value": getattr(player, "note_" + cat) + bonus}
    if poste == "X":
        return {"label": "NOTE", "value": player.note_milieu + bonus}
    return None  # FAN & co : pas de note affichée


# ---------------------------------------------------------------------
# Matchs 1v1 (équipes, formations, simulation, Elo)
# ---------------------------------------------------------------------

FORMATIONS = {
    "4-4-2": {"GB": 1, "DEF": 4, "MC": 4, "ATT": 2},
    "4-3-3": {"GB": 1, "DEF": 4, "MC": 3, "ATT": 3},
    "3-4-3": {"GB": 1, "DEF": 3, "MC": 4, "ATT": 3},
    "5-3-2": {"GB": 1, "DEF": 5, "MC": 3, "ATT": 2},
}

DUEL_COOLDOWN_SECONDS = 3600  # 1h entre deux duels pour la même paire de joueurs


def validate_team_slots(db: Session, user: User, formation: str, slots: list) -> list:
    """
    Vérifie qu'une composition d'équipe est valide :
    - formation reconnue, bon nombre de cartes par emplacement
    - 11 cartes, toutes possédées (quantity > 0), toutes des joueurs distincts,
      aucune carte FAN (pas de note)
    Retourne la liste des Card correspondantes (même ordre) si tout est bon,
    lève ValueError(message) sinon.
    """
    if formation not in FORMATIONS:
        raise ValueError("Formation inconnue : " + formation)
    required = FORMATIONS[formation]
    if len(slots) != 11:
        raise ValueError("Une équipe doit avoir exactement 11 cartes")

    counts = {"GB": 0, "DEF": 0, "MC": 0, "ATT": 0}
    cards = []
    seen_players = set()
    for entry in slots:
        card_id = entry["card_id"]
        category = entry["slot_category"]
        if category not in counts:
            raise ValueError("Emplacement invalide : " + str(category))
        owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card_id).first()
        if not owned or owned.quantity < 1:
            raise ValueError("Tu ne possèdes pas une des cartes sélectionnées")
        card = owned.card
        if get_display_note(card.player, card.tier.value) is None:
            raise ValueError(card.player.name + " est une carte supporter, sans note : elle ne peut pas jouer")
        if card.player_id in seen_players:
            raise ValueError("Deux cartes du même joueur (" + card.player.name + ") dans la même équipe")
        seen_players.add(card.player_id)
        counts[category] += 1
        cards.append((card, category))

    for category, needed in required.items():
        if counts[category] != needed:
            raise ValueError("La formation " + formation + " demande " + str(needed) + " " + category + ", tu en as " + str(counts[category]))

    return cards


def team_strengths(cards_with_slots: list) -> dict:
    """cards_with_slots: liste de (Card, slot_category). Renvoie force d'attaque et de défense."""
    att_values = []
    def_values = []
    for card, category in cards_with_slots:
        note = get_display_note(card.player, card.tier.value)["value"]
        if category in ("ATT", "MC"):
            att_values.append(note)
        if category in ("DEF", "GB"):
            def_values.append(note)
    attack = sum(att_values) / len(att_values) if att_values else 50
    defense = sum(def_values) / len(def_values) if def_values else 50
    return {"attack": attack, "defense": defense}


def poisson_random(lam: float) -> int:
    """Tire un entier selon une loi de Poisson de moyenne lam (algorithme de Knuth)."""
    lam = max(0.05, lam)
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1


def expected_goals(attack: float, opponent_defense: float) -> float:
    diff = (attack - opponent_defense) / 35.0
    return max(0.15, 1.35 + diff)


def elo_update(elo_a: int, elo_b: int, result_a: float, k: int = 32):
    """result_a : 1 si A gagne, 0.5 nul, 0 si A perd. Retourne (nouveau_elo_a, nouveau_elo_b)."""
    expected_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    expected_b = 1 - expected_a
    new_a = round(elo_a + k * (result_a - expected_a))
    new_b = round(elo_b + k * ((1 - result_a) - expected_b))
    return new_a, new_b


def resolve_duel(db: Session, challenger: User, defender: User) -> dict:
    """Résout un duel entre les équipes SAUVEGARDÉES des deux joueurs. Lève ValueError en cas de problème."""
    if challenger.id == defender.id:
        raise ValueError("Impossible de te défier toi-même")

    challenger_team = db.query(Team).filter_by(user_id=challenger.id).first()
    defender_team = db.query(Team).filter_by(user_id=defender.id).first()
    if not challenger_team:
        raise ValueError("Enregistre d'abord ta propre équipe avant de défier quelqu'un")
    if not defender_team:
        raise ValueError("Cette personne n'a pas encore d'équipe enregistrée")

    cooldown_cutoff = datetime.utcnow() - timedelta(seconds=DUEL_COOLDOWN_SECONDS)
    recent = (
        db.query(Duel)
        .filter(
            Duel.created_at >= cooldown_cutoff,
            (
                ((Duel.challenger_id == challenger.id) & (Duel.defender_id == defender.id))
                | ((Duel.challenger_id == defender.id) & (Duel.defender_id == challenger.id))
            ),
        )
        .first()
    )
    if recent:
        wait_seconds = int(DUEL_COOLDOWN_SECONDS - (datetime.utcnow() - recent.created_at).total_seconds())
        raise ValueError("Vous vous êtes déjà affrontés récemment, réessaie dans " + str(max(1, wait_seconds // 60)) + " min")

    stake = defender_team.stake
    if challenger.credits < stake:
        raise ValueError("Pas assez de crédits pour cette mise (" + str(stake) + ")")
    if defender.credits < stake:
        raise ValueError("Cette personne n'a plus assez de crédits pour jouer ce match")

    challenger_slots = [{"card_id": s.card_id, "slot_category": s.slot_category} for s in challenger_team.slots]
    defender_slots = [{"card_id": s.card_id, "slot_category": s.slot_category} for s in defender_team.slots]
    try:
        challenger_cards = validate_team_slots(db, challenger, challenger_team.formation, challenger_slots)
    except ValueError:
        raise ValueError("Ta propre équipe n'est plus valide (carte vendue/échangée ?) — mets-la à jour")
    try:
        defender_cards = validate_team_slots(db, defender, defender_team.formation, defender_slots)
    except ValueError:
        raise ValueError("L'équipe de l'adversaire n'est plus valide (carte vendue/échangée) — défi impossible")

    s_challenger = team_strengths(challenger_cards)
    s_defender = team_strengths(defender_cards)

    xg_challenger = expected_goals(s_challenger["attack"], s_defender["defense"])
    xg_defender = expected_goals(s_defender["attack"], s_challenger["defense"])
    score_challenger = poisson_random(xg_challenger)
    score_defender = poisson_random(xg_defender)

    if score_challenger > score_defender:
        result_challenger = 1.0
    elif score_challenger < score_defender:
        result_challenger = 0.0
    else:
        result_challenger = 0.5

    new_elo_challenger, new_elo_defender = elo_update(challenger.elo, defender.elo, result_challenger)

    elo_before_challenger, elo_before_defender = challenger.elo, defender.elo
    challenger.elo = new_elo_challenger
    defender.elo = new_elo_defender

    if result_challenger == 1.0:
        challenger.credits += stake          # gagne la mise de l'adversaire (net +stake)
        defender.credits -= stake
    elif result_challenger == 0.0:
        challenger.credits -= stake
        defender.credits += stake
    # match nul : personne ne paie, personne ne gagne

    duel = Duel(
        challenger_id=challenger.id, defender_id=defender.id, stake=stake,
        formation_challenger=challenger_team.formation, formation_defender=defender_team.formation,
        score_challenger=score_challenger, score_defender=score_defender,
        elo_challenger_before=elo_before_challenger, elo_defender_before=elo_before_defender,
        elo_challenger_after=new_elo_challenger, elo_defender_after=new_elo_defender,
    )
    db.add(duel)
    db.commit()

    return {
        "score_challenger": score_challenger, "score_defender": score_defender,
        "result": "victoire" if result_challenger == 1.0 else ("défaite" if result_challenger == 0.0 else "nul"),
        "stake": stake,
        "elo_challenger_before": elo_before_challenger, "elo_challenger_after": new_elo_challenger,
        "elo_defender_before": elo_before_defender, "elo_defender_after": new_elo_defender,
        "defender_pseudo": defender.pseudo,
    }


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
