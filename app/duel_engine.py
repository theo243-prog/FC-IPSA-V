"""
Moteur des matchs 1v1 à 5 joueurs (1 gardien + 4 joueurs de champ).

Principe : un joueur PROPOSE un match (son équipe, sa tactique secrète, une mise de 1 à 10
crédits, retirée de ses crédits tant que le défi est ouvert). Un autre joueur le JOUE avec sa
propre équipe : le match est résolu tout de suite, raconté minute par minute, et le gagnant
remporte les deux mises + un "pack match" aux probabilités boostées.

Ce que comptent les calculs :
- la note de chaque carte (75 commune, 85 rare, 85+ épique, 95 légendaire) ;
- -10 % si la carte joue HORS de son vrai poste (les postes "X" ne sont jamais pénalisés) ;
- +10 % pour la carte capitaine ;
- le Fan optionnel : +5 % / +10 % / +12 % / +15 % à toute l'équipe selon sa rareté ;
- 1 carte Fan (supporter) et 1 carte Loup (la mascotte), chacune optionnelle : +5 % / +10 % / +12 % / +13 % / +15 % à toute l'équipe ;
- 1 seule carte Équipement : +1 % / +2 % / +3 % / +5 % à toute l'équipe (s'additionne au Fan et au Loup) ;
- la tactique (pierre-feuille-ciseaux) : +6 % à toute l'équipe pour celle qui l'emporte ;
- la disposition (2-1-1, 1-2-1, 1-1-2) qui répartit la force entre attaque et défense.
"""
import json
import random
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .game_logic import (card_note, TIER_FAN_BONUS, TIER_MASCOT_BONUS, TIER_EQUIPMENT_BONUS, MAX_EQUIPMENT,
                         card_kind, is_fan, is_equipment, is_mascot)
from .models import User, Card, OwnedCard, MatchProposal, ProposalSlot, ProposalEquipment, Duel

# ----------------------------------------------------------------- Règles ----

TEAM_SIZE = 5

# Nombre de joueurs par ligne (le gardien est toujours en plus, compris dans les 5)
FORMATIONS = {
    "2-1-1": {"GB": 1, "DEF": 2, "MC": 1, "ATT": 1},   # prudente
    "1-2-1": {"GB": 1, "DEF": 1, "MC": 2, "ATT": 1},   # équilibrée
    "1-1-2": {"GB": 1, "DEF": 1, "MC": 1, "ATT": 2},   # offensive
}
FORMATION_LABELS = {"2-1-1": "prudente", "1-2-1": "équilibrée", "1-1-2": "offensive"}
SLOT_LABELS = {"GB": "Gardien", "DEF": "Défenseur", "MC": "Milieu", "ATT": "Attaquant"}

# Pierre-feuille-ciseaux : chaque tactique en bat une autre.
TACTICS = {
    "pressing": {"label": "Pressing haut", "beats": "possession"},
    "possession": {"label": "Possession", "beats": "contre"},
    "contre": {"label": "Contre-attaque", "beats": "pressing"},
}

# vrai poste (peut avoir plusieurs codes historiques) -> emplacement
POSTE_CATEGORY = {
    "GB": "GB",
    "DEF": "DEF", "DD": "DEF", "DC": "DEF", "DG": "DEF",
    "MC": "MC", "MDC": "MC", "MOC": "MC",
    "ATT": "ATT", "AD": "ATT", "BU": "ATT",
}

OUT_OF_POSITION_MALUS = 0.10
CAPTAIN_BONUS = 0.10
TACTIC_BONUS = 0.06

STAKE_MIN, STAKE_MAX = 1, 10
MAX_OPEN_PROPOSALS = 3
DUEL_COOLDOWN_SECONDS = 3600     # 1 match par heure entre deux mêmes joueurs
ELO_K = 32

MATCH_MINUTES = 40               # 2 mi-temps de 20 minutes
HALF_TIME_MINUTE = 20

# Poids de chaque emplacement dans la ligne d'attaque / la ligne de défense (le milieu compte
# dans les deux). La force d'une ligne est la MOYENNE pondérée des notes de ses joueurs.
ATTACK_WEIGHT = {"ATT": 1.0, "MC": 0.5, "DEF": 0.0, "GB": 0.0}
DEFENSE_WEIGHT = {"ATT": 0.0, "MC": 0.5, "DEF": 1.0, "GB": 1.5}
# La disposition donne un "style" : offensive = plus de buts des deux côtés, prudente = moins.
# Elle ne rend pas l'équipe plus forte en soi (attaque x défense reste constant) : elle décide
# surtout quelles cartes comptent le plus (attaquants en 1-1-2, défenseurs/gardien en 2-1-1).
FORMATION_SKEW = 0.5
BASE_XG = 3.0                    # donne ~2 buts par équipe dans un match équilibré (1-2-1 contre 1-2-1)
XG_EXPONENT = 1.5                # plus il est grand, plus l'écart de niveau pèse sur le score


class DuelError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ------------------------------------------------------------- Utilitaires ----

def poste_category(poste):
    """Emplacement naturel d'un poste, ou None si le poste n'est pas défini (X) : pas de malus."""
    return POSTE_CATEGORY.get((poste or "").upper())


def get_config() -> dict:
    return {
        "team_size": TEAM_SIZE,
        "formations": FORMATIONS,
        "formation_labels": FORMATION_LABELS,
        "slot_labels": SLOT_LABELS,
        "tactics": TACTICS,
        "poste_category": POSTE_CATEGORY,
        "out_of_position_malus": OUT_OF_POSITION_MALUS,
        "captain_bonus": CAPTAIN_BONUS,
        "tactic_bonus": TACTIC_BONUS,
        "stake_min": STAKE_MIN,
        "stake_max": STAKE_MAX,
        "max_open_proposals": MAX_OPEN_PROPOSALS,
        "cooldown_minutes": DUEL_COOLDOWN_SECONDS // 60,
        "fan_bonus": TIER_FAN_BONUS,
        "mascot_bonus": TIER_MASCOT_BONUS,
        "equipment_bonus": TIER_EQUIPMENT_BONUS,
        "max_equipment": MAX_EQUIPMENT,
    }


def poisson_random(lam: float) -> int:
    """Tire un entier selon une loi de Poisson de moyenne lam (algorithme de Knuth)."""
    lam = max(0.05, lam)
    limit = pow(2.718281828459045, -lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= limit:
            return min(9, k - 1)


def elo_update(elo_a: int, elo_b: int, result_a: float, k: int = ELO_K):
    """result_a : 1 si A gagne, 0.5 nul, 0 si A perd. Retourne (nouvel_elo_a, nouvel_elo_b)."""
    expected_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))
    new_a = round(elo_a + k * (result_a - expected_a))
    new_b = round(elo_b + k * ((1 - result_a) - (1 - expected_a)))
    return new_a, new_b


# ------------------------------------------------------------ Validation ----

def validate_team(db: Session, user: User, formation: str, tactic: str, slots: list,
                  captain_card_id=None, fan_card_id=None, equipment_card_ids=None, mascot_card_id=None):
    """
    Vérifie une équipe. Règles : disposition connue, 5 cartes, bon nombre par emplacement, cartes
    toutes possédées, JAMAIS deux fois la même carte (même si on l'a en plusieurs exemplaires ;
    en revanche deux raretés du même joueur sont possibles), seuls de vrais joueurs sur le terrain
    (ni Fan, ni Loup, ni équipement, ni stade), au plus 1 Fan, 1 Loup et MAX_EQUIPMENT Équipement.
    Retourne (cartes [(Card, emplacement)], capitaine Card|None, fan Card|None, équipements [Card], loup Card|None).
    """
    if formation not in FORMATIONS:
        raise DuelError("Disposition inconnue : " + str(formation))
    if tactic not in TACTICS:
        raise DuelError("Tactique inconnue : " + str(tactic))
    if len(slots) != TEAM_SIZE:
        raise DuelError("Une équipe doit avoir exactement " + str(TEAM_SIZE) + " cartes")

    required = FORMATIONS[formation]
    counts = {cat: 0 for cat in required}
    seen = set()
    cards = []
    for entry in slots:
        card_id, cat = entry["card_id"], entry["slot_category"]
        if cat not in counts:
            raise DuelError("Emplacement invalide : " + str(cat))
        if card_id in seen:
            raise DuelError("Tu ne peux pas utiliser deux fois la même carte dans une équipe")
        seen.add(card_id)
        owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card_id).first()
        if not owned or owned.quantity < 1:
            raise DuelError("Tu ne possèdes pas une des cartes sélectionnées")
        card = owned.card
        kind = card_kind(card.player)
        if kind == "fan":
            raise DuelError(card.player.name + " est une carte supporter : elle ne peut jouer que comme Fan")
        if kind == "mascotte":
            raise DuelError(card.player.name + " est la mascotte : place-la dans l'emplacement Loup")
        if kind == "equipement":
            raise DuelError(card.player.name + " est un équipement : place-le dans un emplacement Équipement")
        if kind in ("stade", "moment"):
            raise DuelError(card.player.name + " est une carte de collection : elle ne peut pas jouer sur le terrain")
        counts[cat] += 1
        cards.append((card, cat))

    for cat, needed in required.items():
        if counts[cat] != needed:
            raise DuelError("La disposition " + formation + " demande " + str(needed) + " "
                            + SLOT_LABELS[cat].lower() + "(s), tu en as mis " + str(counts[cat]))

    captain = None
    if captain_card_id:
        if captain_card_id not in seen:
            raise DuelError("Le capitaine doit faire partie des 5 joueurs de l'équipe")
        captain = next(card for card, _ in cards if card.id == captain_card_id)

    fan = None
    if fan_card_id:
        owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=fan_card_id).first()
        if not owned or owned.quantity < 1:
            raise DuelError("Tu ne possèdes pas la carte Fan sélectionnée")
        if not is_fan(owned.card.player):
            raise DuelError(owned.card.player.name + " n'est pas une carte supporter")
        fan = owned.card

    equipment = []
    equipment_ids = list(equipment_card_ids or [])
    if len(equipment_ids) > MAX_EQUIPMENT:
        raise DuelError("Tu peux équiper %d cartes Équipement au maximum" % MAX_EQUIPMENT)
    if len(set(equipment_ids)) != len(equipment_ids):
        raise DuelError("Tu ne peux pas équiper deux fois la même carte Équipement")
    for equipment_id in equipment_ids:
        owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=equipment_id).first()
        if not owned or owned.quantity < 1:
            raise DuelError("Tu ne possèdes pas une des cartes Équipement sélectionnées")
        if not is_equipment(owned.card.player):
            raise DuelError(owned.card.player.name + " n'est pas une carte Équipement")
        equipment.append(owned.card)

    mascot = None
    if mascot_card_id:
        owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=mascot_card_id).first()
        if not owned or owned.quantity < 1:
            raise DuelError("Tu ne possèdes pas la carte Loup sélectionnée")
        if not is_mascot(owned.card.player):
            raise DuelError(owned.card.player.name + " n'est pas la mascotte : l'emplacement Loup est réservé à ses cartes")
        mascot = owned.card

    return cards, captain, fan, equipment, mascot


# ---------------------------------------------------------------- Calculs ----

def build_members(cards_with_slots, captain_card_id):
    """Pour chaque carte : note de base, note effective (malus hors poste, bonus capitaine)."""
    members = []
    for card, slot in cards_with_slots:
        base = card_note(card.player, card.tier.value, card)
        natural = poste_category(card.player.poste)
        out = natural is not None and natural != slot
        effective = base * (1 - OUT_OF_POSITION_MALUS if out else 1.0)
        is_captain = card.id == captain_card_id
        if is_captain:
            effective *= (1 + CAPTAIN_BONUS)
        members.append({
            "slot": slot, "player": card.player.name, "tier": card.tier.value,
            "poste": card.player.poste, "base_note": base, "effective": effective,
            "out_of_position": out, "captain": is_captain,
        })
    return members


def equipment_bonus_total(equipment_cards) -> float:
    return sum(TIER_EQUIPMENT_BONUS.get(c.tier.value, 0.0) for c in (equipment_cards or []))


def team_powers(members, fan_card, tactic_multiplier=1.0, equipment_cards=(), mascot_card=None):
    units_att = sum(ATTACK_WEIGHT[m["slot"]] for m in members)
    units_def = sum(DEFENSE_WEIGHT[m["slot"]] for m in members)
    attack_avg = sum(ATTACK_WEIGHT[m["slot"]] * m["effective"] for m in members) / units_att
    defense_avg = sum(DEFENSE_WEIGHT[m["slot"]] * m["effective"] for m in members) / units_def
    style = (units_att / units_def) ** (FORMATION_SKEW / 2)      # <1 prudente, >1 offensive
    fan_bonus = TIER_FAN_BONUS.get(fan_card.tier.value, 0.0) if fan_card else 0.0
    equipment_bonus = equipment_bonus_total(equipment_cards)
    mascot_bonus = TIER_MASCOT_BONUS.get(mascot_card.tier.value, 0.0) if mascot_card else 0.0
    mult = (1 + fan_bonus + mascot_bonus + equipment_bonus) * tactic_multiplier      # Fan, Loup et équipement s'additionnent
    return attack_avg * style * mult, defense_avg / style * mult, fan_bonus, equipment_bonus, mascot_bonus


def tactic_advantage(tactic_a: str, tactic_b: str):
    """'a' si A l'emporte, 'b' si B l'emporte, None si égalité."""
    if TACTICS[tactic_a]["beats"] == tactic_b:
        return "a"
    if TACTICS[tactic_b]["beats"] == tactic_a:
        return "b"
    return None


def expected_goals(attack: float, opponent_defense: float) -> float:
    return max(0.15, BASE_XG * (attack / opponent_defense) ** XG_EXPONENT)


# ----------------------------------------------------------------- Récit ----

SCORER_WEIGHT = {"ATT": 5.0, "MC": 3.0, "DEF": 1.0, "GB": 0.05}
ASSIST_WEIGHT = {"ATT": 3.0, "MC": 4.0, "DEF": 2.0, "GB": 0.2}


def _pick(members, slot_weights, exclude=None):
    pool = [m for m in members if m is not exclude]
    weights = [slot_weights[m["slot"]] * m["effective"] for m in pool]
    return random.choices(pool, weights=weights, k=1)[0]


def build_events(side_a, side_b, score_a, score_b, xg_a, xg_b, tactic_winner):
    """
    side_a / side_b : {"pseudo", "members", "formation", "tactic"} (a = celui qui joue le défi,
    b = celui qui l'a proposé). Retourne la liste chronologique des événements du match.
    """
    sides = {"challenger": side_a, "defender": side_b}
    # un même joueur peut être aligné par les deux équipes : on précise alors de quelle équipe on parle
    shared = {m["player"] for m in side_a["members"]} & {m["player"] for m in side_b["members"]}

    def label(member, team):
        return member["player"] + (" (" + team["pseudo"] + ")" if member["player"] in shared else "")

    total_goals = score_a + score_b
    n_chances = random.randint(3, 6)
    minutes = random.sample(range(1, MATCH_MINUTES), total_goals + n_chances)

    raw = []   # (minute, kind, side, payload)
    goal_sides = ["challenger"] * score_a + ["defender"] * score_b
    random.shuffle(goal_sides)
    for side_name, minute in zip(goal_sides, minutes[:total_goals]):
        raw.append((minute, "goal", side_name, None))
    share_a = xg_a / (xg_a + xg_b)
    for minute in minutes[total_goals:]:
        side_name = "challenger" if random.random() < share_a else "defender"
        raw.append((minute, "chance", side_name, None))
    raw.sort(key=lambda e: e[0])

    events = [{
        "minute": 0, "kind": "kickoff", "side": None, "score": [0, 0],
        "text": "🏁 Coup d'envoi ! %s (%s) affronte %s (%s) — 5 contre 5, 2 × %d minutes."
                % (side_a["pseudo"], side_a["formation"], side_b["pseudo"], side_b["formation"], HALF_TIME_MINUTE),
    }]
    if tactic_winner is None:
        adv = "Les deux équipes jouent la même tactique : pas d'avantage."
    else:
        winner_side = side_a if tactic_winner == "a" else side_b
        adv = "Avantage tactique à %s (+%d %% pour toute l'équipe) !" % (winner_side["pseudo"], round(TACTIC_BONUS * 100))
    events.append({
        "minute": 0, "kind": "tactic", "side": None, "score": [0, 0],
        "text": "🎯 Tactiques dévoilées : %s joue « %s », %s joue « %s ». %s" % (
            side_a["pseudo"], TACTICS[side_a["tactic"]]["label"],
            side_b["pseudo"], TACTICS[side_b["tactic"]]["label"], adv),
    })

    score = [0, 0]
    half_done = False
    for minute, kind, side_name, _ in raw:
        if not half_done and minute > HALF_TIME_MINUTE:
            events.append({"minute": HALF_TIME_MINUTE, "kind": "half", "side": None, "score": list(score),
                           "text": "⏸️ Mi-temps : %s %d-%d %s." % (side_a["pseudo"], score[0], score[1], side_b["pseudo"])})
            half_done = True
        team = sides[side_name]
        opp = sides["defender" if side_name == "challenger" else "challenger"]
        idx = 0 if side_name == "challenger" else 1

        if kind == "goal":
            before = score[idx] - score[1 - idx]
            scorer = _pick(team["members"], SCORER_WEIGHT)
            assist = _pick(team["members"], ASSIST_WEIGHT, exclude=scorer) if random.random() < 0.65 else None
            score[idx] += 1
            after = score[idx] - score[1 - idx]
            if score[0] + score[1] == 1:
                ctx = "ouvre le score pour %s !" % team["pseudo"]
            elif after == 0:
                ctx = "égalise pour %s !" % team["pseudo"]
            elif before == 0:
                ctx = "donne l'avantage à %s !" % team["pseudo"]
            elif after < 0:
                ctx = "réduit l'écart pour %s !" % team["pseudo"]
            else:
                ctx = "creuse l'écart pour %s !" % team["pseudo"]
            text = "⚽ BUT ! %s %s" % (label(scorer, team), ctx)
            if scorer["captain"]:
                text += " Le capitaine montre l'exemple !"
            if assist:
                text += " Passe décisive de %s." % label(assist, team)
            text += " (%d-%d)" % (score[0], score[1])
            events.append({"minute": minute, "kind": "goal", "side": side_name, "score": list(score), "text": text,
                           "scorer": scorer["player"], "scorer_tier": scorer["tier"],
                           "assist": assist["player"] if assist else None,
                           "assist_tier": assist["tier"] if assist else None})
        else:
            shooter = _pick(team["members"], SCORER_WEIGHT)
            keeper = next((m for m in opp["members"] if m["slot"] == "GB"), opp["members"][0])
            blocker = _pick([m for m in opp["members"] if m["slot"] in ("DEF", "MC")] or opp["members"], ASSIST_WEIGHT)
            text = random.choice([
                "🧤 %s sort un arrêt magnifique devant %s !" % (label(keeper, opp), label(shooter, team)),
                "🥅 Poteau ! La frappe de %s fait trembler la barre." % label(shooter, team),
                "💨 %s tente sa chance, mais le ballon passe à côté." % label(shooter, team),
                "🛡️ %s se jette et contre la frappe de %s !" % (label(blocker, opp), label(shooter, team)),
            ])
            events.append({"minute": minute, "kind": "chance", "side": side_name, "score": list(score), "text": text})

    if not half_done:
        events.append({"minute": HALF_TIME_MINUTE, "kind": "half", "side": None, "score": [score[0], score[1]],
                       "text": "⏸️ Mi-temps : %s %d-%d %s." % (side_a["pseudo"], score[0], score[1], side_b["pseudo"])})
        # la mi-temps doit rester avant les événements de la 2e période : on remet dans l'ordre
        events.sort(key=lambda e: (e["minute"], {"kickoff": 0, "tactic": 1}.get(e["kind"], 2)))
    events.append({"minute": MATCH_MINUTES, "kind": "full", "side": None, "score": list(score),
                   "text": "🏁 Coup de sifflet final ! %s %d-%d %s." % (side_a["pseudo"], score[0], score[1], side_b["pseudo"])})
    return events


def _lineup_snapshot(side, fan_card, equipment_cards=(), mascot_card=None):
    return {
        "pseudo": side["pseudo"], "formation": side["formation"], "tactic": side["tactic"],
        "players": [{
            "slot": m["slot"], "player": m["player"], "tier": m["tier"], "poste": m["poste"],
            "base_note": m["base_note"], "effective_note": round(m["effective"], 1),
            "out_of_position": m["out_of_position"], "captain": m["captain"],
        } for m in side["members"]],
        "fan": ({"player": fan_card.player.name, "tier": fan_card.tier.value,
                 "bonus_pct": round(TIER_FAN_BONUS.get(fan_card.tier.value, 0) * 100)} if fan_card else None),
        "mascot": ({"player": mascot_card.player.name, "tier": mascot_card.tier.value,
                    "bonus_pct": round(TIER_MASCOT_BONUS.get(mascot_card.tier.value, 0) * 100)} if mascot_card else None),
        "equipment": [{"player": c.player.name, "tier": c.tier.value,
                       "bonus_pct": round(TIER_EQUIPMENT_BONUS.get(c.tier.value, 0) * 100)} for c in (equipment_cards or [])],
    }


# ----------------------------------------------------------------- Défis ----

def cancel_proposal(db: Session, proposal: MatchProposal):
    """Supprime un défi et rend la mise séquestrée à son créateur (l'appelant fait le commit)."""
    proposal.creator.credits += proposal.stake
    db.delete(proposal)


def purge_card_references(db: Session, card_ids: list):
    """Annule (avec remboursement) tous les défis qui utilisent l'une de ces cartes.
    À appeler avant de supprimer une carte ou un joueur."""
    if not card_ids:
        return
    proposals = (
        db.query(MatchProposal)
        .outerjoin(ProposalSlot, ProposalSlot.proposal_id == MatchProposal.id)
        .outerjoin(ProposalEquipment, ProposalEquipment.proposal_id == MatchProposal.id)
        .filter(or_(ProposalSlot.card_id.in_(card_ids), ProposalEquipment.card_id.in_(card_ids),
                    MatchProposal.captain_card_id.in_(card_ids),
                    MatchProposal.fan_card_id.in_(card_ids),
                    MatchProposal.mascot_card_id.in_(card_ids)))
        .distinct().all()
    )
    for proposal in proposals:
        cancel_proposal(db, proposal)
    db.flush()   # les défis (et leurs emplacements) doivent disparaître avant la carte elle-même


def create_proposal(db: Session, user: User, formation, tactic, stake, slots, captain_card_id, fan_card_id,
                    equipment_card_ids=None, mascot_card_id=None):
    if not (STAKE_MIN <= stake <= STAKE_MAX):
        raise DuelError("La mise doit être comprise entre %d et %d crédits" % (STAKE_MIN, STAKE_MAX))
    open_count = db.query(MatchProposal).filter_by(creator_id=user.id).count()
    if open_count >= MAX_OPEN_PROPOSALS:
        raise DuelError("Tu as déjà %d défis ouverts : annule-en un ou attends qu'il soit joué" % MAX_OPEN_PROPOSALS)
    if user.credits < stake:
        raise DuelError("Pas assez de crédits pour miser %d" % stake)
    validate_team(db, user, formation, tactic, slots, captain_card_id, fan_card_id, equipment_card_ids, mascot_card_id)

    user.credits -= stake   # séquestre : rendu si le défi est annulé, joué ensuite
    proposal = MatchProposal(creator_id=user.id, stake=stake, formation=formation, tactic=tactic,
                             captain_card_id=captain_card_id or None, fan_card_id=fan_card_id or None,
                             mascot_card_id=mascot_card_id or None)
    db.add(proposal)
    db.flush()
    for entry in slots:
        db.add(ProposalSlot(proposal_id=proposal.id, card_id=entry["card_id"], slot_category=entry["slot_category"]))
    for equipment_id in (equipment_card_ids or []):
        db.add(ProposalEquipment(proposal_id=proposal.id, card_id=equipment_id))
    db.commit()
    return proposal


def play_proposal(db: Session, challenger: User, proposal_id: str, formation, tactic, slots,
                  captain_card_id, fan_card_id, equipment_card_ids=None, mascot_card_id=None) -> dict:
    # verrou : si deux joueurs cliquent en même temps, un seul passe, l'autre voit "n'existe plus"
    proposal = db.query(MatchProposal).filter_by(id=proposal_id).with_for_update().first()
    if not proposal:
        raise DuelError("Ce défi n'existe plus (déjà joué ou annulé)", 404)
    creator = proposal.creator
    if creator.id == challenger.id:
        raise DuelError("Tu ne peux pas jouer ton propre défi")

    cutoff = datetime.utcnow() - timedelta(seconds=DUEL_COOLDOWN_SECONDS)
    recent = (
        db.query(Duel)
        .filter(Duel.created_at >= cutoff,
                or_((Duel.challenger_id == challenger.id) & (Duel.defender_id == creator.id),
                    (Duel.challenger_id == creator.id) & (Duel.defender_id == challenger.id)))
        .order_by(Duel.created_at.desc()).first()
    )
    if recent:
        wait = int(DUEL_COOLDOWN_SECONDS - (datetime.utcnow() - recent.created_at).total_seconds())
        raise DuelError("Vous vous êtes déjà affrontés il y a peu : réessaie dans %d min" % max(1, wait // 60 + (1 if wait % 60 else 0)))

    stake = proposal.stake
    if challenger.credits < stake:
        raise DuelError("Pas assez de crédits pour cette mise (%d)" % stake)

    cards_c, captain_c, fan_c, equip_c, mascot_c = validate_team(db, challenger, formation, tactic, slots, captain_card_id,
                                                                 fan_card_id, equipment_card_ids, mascot_card_id)

    proposal_slots = [{"card_id": s.card_id, "slot_category": s.slot_category} for s in proposal.slots]
    try:
        cards_d, captain_d, fan_d, equip_d, mascot_d = validate_team(db, creator, proposal.formation, proposal.tactic,
                                                                     proposal_slots, proposal.captain_card_id, proposal.fan_card_id,
                                                                     [e.card_id for e in proposal.equipment], proposal.mascot_card_id)
    except DuelError:
        cancel_proposal(db, proposal)
        db.commit()
        raise DuelError("Ce défi n'était plus valide (l'adversaire n'a plus toutes ses cartes) : "
                        "il a été annulé et sa mise remboursée. Choisis-en un autre.")

    side_c = {"pseudo": challenger.pseudo, "formation": formation, "tactic": tactic,
              "members": build_members(cards_c, captain_c.id if captain_c else None)}
    side_d = {"pseudo": creator.pseudo, "formation": proposal.formation, "tactic": proposal.tactic,
              "members": build_members(cards_d, captain_d.id if captain_d else None)}

    winner_tactic = tactic_advantage(tactic, proposal.tactic)          # 'a' = challenger, 'b' = créateur
    mult_c = 1 + TACTIC_BONUS if winner_tactic == "a" else 1.0
    mult_d = 1 + TACTIC_BONUS if winner_tactic == "b" else 1.0
    att_c, def_c, _, _, _ = team_powers(side_c["members"], fan_c, mult_c, equip_c, mascot_c)
    att_d, def_d, _, _, _ = team_powers(side_d["members"], fan_d, mult_d, equip_d, mascot_d)

    xg_c = expected_goals(att_c, def_d)
    xg_d = expected_goals(att_d, def_c)
    score_c, score_d = poisson_random(xg_c), poisson_random(xg_d)
    events = build_events(side_c, side_d, score_c, score_d, xg_c, xg_d, winner_tactic)

    if score_c > score_d:
        outcome, result_c = "victoire", 1.0
    elif score_c < score_d:
        outcome, result_c = "défaite", 0.0
    else:
        outcome, result_c = "nul", 0.5
    elo_c_before, elo_d_before = challenger.elo, creator.elo
    challenger.elo, creator.elo = elo_update(elo_c_before, elo_d_before, result_c)

    # crédits : la mise du créateur est déjà séquestrée, celle du challenger est prélevée maintenant
    challenger.credits -= stake
    pot = 2 * stake
    pack_winner = None
    if outcome == "victoire":
        challenger.credits += pot
        pack_winner = challenger
    elif outcome == "défaite":
        creator.credits += pot
        pack_winner = creator
    else:   # nul : chacun récupère sa mise
        challenger.credits += stake
        creator.credits += stake
    if pack_winner is not None:
        pack_winner.pack_state.match_pack_tokens += 1

    lineups = {"challenger": _lineup_snapshot(side_c, fan_c, equip_c, mascot_c), "defender": _lineup_snapshot(side_d, fan_d, equip_d, mascot_d)}
    duel = Duel(
        challenger_id=challenger.id, defender_id=creator.id, stake=stake,
        formation_challenger=formation, formation_defender=proposal.formation,
        score_challenger=score_c, score_defender=score_d,
        elo_challenger_before=elo_c_before, elo_defender_before=elo_d_before,
        elo_challenger_after=challenger.elo, elo_defender_after=creator.elo,
        tactic_challenger=tactic, tactic_defender=proposal.tactic,
        events_json=json.dumps(events, ensure_ascii=False),
        lineups_json=json.dumps(lineups, ensure_ascii=False),
    )
    db.add(duel)
    db.delete(proposal)   # le défi est consommé
    db.commit()

    return {
        "duel_id": duel.id,
        "challenger": challenger.pseudo, "defender": creator.pseudo,
        "score_challenger": score_c, "score_defender": score_d,
        "result": outcome, "stake": stake,
        "credits_delta": {"victoire": stake, "défaite": -stake, "nul": 0}[outcome],
        "elo_challenger_before": elo_c_before, "elo_challenger_after": challenger.elo,
        "elo_defender_before": elo_d_before, "elo_defender_after": creator.elo,
        "pack_match_won": outcome == "victoire",
        "tactics": {"challenger": tactic, "defender": proposal.tactic,
                    "advantage": {"a": "challenger", "b": "defender"}.get(winner_tactic)},
        "events": events, "lineups": lineups,
    }


# ------------------------------------------------- Pages : profils, historique ----

def duel_board(db: Session) -> list:
    """Profils des joueurs qui jouent (au moins un match ou un défi ouvert), classés par Elo.
    Les comptes de test n'y apparaissent pas."""
    stats = {}
    for d in db.query(Duel).all():
        for uid, mine, theirs in ((d.challenger_id, d.score_challenger, d.score_defender),
                                  (d.defender_id, d.score_defender, d.score_challenger)):
            s = stats.setdefault(uid, {"played": 0, "wins": 0, "losses": 0, "draws": 0, "goals_for": 0, "goals_against": 0})
            s["played"] += 1
            s["goals_for"] += mine
            s["goals_against"] += theirs
            if mine > theirs:
                s["wins"] += 1
            elif mine < theirs:
                s["losses"] += 1
            else:
                s["draws"] += 1
    open_by_user = {}
    for p in db.query(MatchProposal).all():
        open_by_user[p.creator_id] = open_by_user.get(p.creator_id, 0) + 1

    rows = []
    for user in db.query(User).filter_by(is_test=False).all():
        s = stats.get(user.id)
        if not s and user.id not in open_by_user:
            continue
        s = s or {"played": 0, "wins": 0, "losses": 0, "draws": 0, "goals_for": 0, "goals_against": 0}
        rows.append({"pseudo": user.pseudo, "elo": user.elo, "open_proposals": open_by_user.get(user.id, 0), **s,
                     "goal_diff": s["goals_for"] - s["goals_against"]})
    rows.sort(key=lambda r: (-r["elo"], -r["wins"], -r["goal_diff"], r["pseudo"]))
    return rows


def duel_history(db: Session, limit: int = 15) -> list:
    duels = db.query(Duel).order_by(Duel.created_at.desc()).limit(limit).all()
    out = []
    for d in duels:
        if d.score_challenger > d.score_defender:
            winner = d.challenger.pseudo
        elif d.score_challenger < d.score_defender:
            winner = d.defender.pseudo
        else:
            winner = None
        out.append({
            "id": d.id, "date": d.created_at.isoformat(),
            "challenger": d.challenger.pseudo, "defender": d.defender.pseudo,
            "score_challenger": d.score_challenger, "score_defender": d.score_defender,
            "winner": winner, "stake": d.stake, "has_recap": bool(d.events_json),
        })
    return out


def duel_recap(db: Session, duel_id: str) -> dict:
    d = db.get(Duel, duel_id)
    if not d:
        raise DuelError("Match introuvable", 404)
    return {
        "duel_id": d.id, "date": d.created_at.isoformat(),
        "challenger": d.challenger.pseudo, "defender": d.defender.pseudo,
        "score_challenger": d.score_challenger, "score_defender": d.score_defender,
        "stake": d.stake,
        "elo_challenger_before": d.elo_challenger_before, "elo_challenger_after": d.elo_challenger_after,
        "elo_defender_before": d.elo_defender_before, "elo_defender_after": d.elo_defender_after,
        "tactics": {"challenger": d.tactic_challenger, "defender": d.tactic_defender},
        "events": json.loads(d.events_json) if d.events_json else [],
        "lineups": json.loads(d.lineups_json) if d.lineups_json else None,
    }


def duel_card_stats(db: Session):
    """Compte, sur tous les matchs 1v1 joués, les utilisations, buts et passes décisives par carte
    (un joueur + une rareté). Retourne trois Counter indexés par (nom du joueur, rareté)."""
    used, goals, assists = Counter(), Counter(), Counter()
    for d in db.query(Duel).filter(Duel.lineups_json.isnot(None)).all():
        try:
            lineups = json.loads(d.lineups_json)
            events = json.loads(d.events_json or "[]")
        except ValueError:
            continue
        for side in ("challenger", "defender"):
            for p in lineups.get(side, {}).get("players", []):
                used[(p["player"], p["tier"])] += 1

        def tier_of(side, name, hint):
            if hint:                       # matchs récents : la rareté est dans l'événement
                return hint
            for p in lineups.get(side, {}).get("players", []):   # anciens matchs : on la retrouve via la composition
                if p["player"] == name:
                    return p["tier"]
            return None

        for ev in events:
            if ev.get("kind") != "goal":
                continue
            tier = tier_of(ev["side"], ev["scorer"], ev.get("scorer_tier"))
            if tier:
                goals[(ev["scorer"], tier)] += 1
            if ev.get("assist"):
                tier = tier_of(ev["side"], ev["assist"], ev.get("assist_tier"))
                if tier:
                    assists[(ev["assist"], tier)] += 1
    return used, goals, assists


def list_proposals(db: Session) -> list:
    rows = db.query(MatchProposal).order_by(MatchProposal.created_at.desc()).all()
    return [{
        "id": p.id, "creator": p.creator.pseudo, "creator_elo": p.creator.elo,
        "formation": p.formation, "stake": p.stake, "created_at": p.created_at.isoformat(),
        "has_fan": bool(p.fan_card_id), "has_mascot": bool(p.mascot_card_id), "equipment_count": len(p.equipment),
    } for p in rows]


# ------------------------------------------------------------ Ménage : effacer des matchs 1v1 ----

ELO_START = 1000


def _replay_elo(user_ids, duels):
    """Rejoue les matchs dans l'ordre à partir de 1000 : retourne (elo final par joueur, [(avant, après) par match])."""
    elos = {uid: ELO_START for uid in user_ids}
    steps = []
    for d in duels:
        a, b = elos.get(d.challenger_id, ELO_START), elos.get(d.defender_id, ELO_START)
        result = 1.0 if d.score_challenger > d.score_defender else (0.0 if d.score_challenger < d.score_defender else 0.5)
        na, nb = elo_update(a, b, result)
        steps.append((a, b, na, nb))
        elos[d.challenger_id], elos[d.defender_id] = na, nb
    return elos, steps


def reset_duels(db: Session, scope: str, recompute_elo: bool, dry_run: bool) -> dict:
    """Efface des matchs 1v1 puis recalcule l'Elo de tout le monde à partir des matchs qui restent.
    scope : "test" (les matchs où au moins un compte de test a joué), "all" (tous), "none" (rien : Elo seulement)."""
    users = {u.id: u for u in db.query(User).all()}
    duels = db.query(Duel).order_by(Duel.created_at, Duel.id).all()

    def involves_test(d):
        return any(users[i].is_test for i in (d.challenger_id, d.defender_id) if i in users)
    doomed = duels if scope == "all" else ([d for d in duels if involves_test(d)] if scope == "test" else [])
    doomed_ids = {d.id for d in doomed}
    kept = [d for d in duels if d.id not in doomed_ids]

    elos, steps = _replay_elo(list(users), kept) if recompute_elo else ({uid: u.elo for uid, u in users.items()}, [])
    changes = [{"pseudo": u.pseudo, "test": bool(u.is_test), "elo_avant": u.elo, "elo_apres": elos[uid]}
               for uid, u in sorted(users.items(), key=lambda kv: kv[1].pseudo) if elos[uid] != u.elo]
    report = {"dry_run": dry_run, "scope": scope, "matchs_1v1_total": len(duels), "matchs_supprimes": len(doomed),
              "matchs_conserves": len(kept), "elo_modifies": changes}
    if dry_run:
        return report
    for d in doomed:
        db.delete(d)
    if recompute_elo:
        for uid, u in users.items():
            u.elo = elos[uid]
        for d, (ba, bb, na, nb) in zip(kept, steps):
            d.elo_challenger_before, d.elo_defender_before, d.elo_challenger_after, d.elo_defender_after = ba, bb, na, nb
    db.commit()
    return report
