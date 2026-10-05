"""
Tables de la base de données.

Vue d'ensemble :
- Player       : les joueurs du FC Format A5 (identité réelle : nom, poste)
- Card         : une "version" d'un joueur (commune / rare / légendaire),
                 chacune avec ses propres stats. Un joueur a toujours une
                 carte commune et une carte rare ; la légendaire n'existe
                 que si elle a été débloquée (but marqué, homme du match...).
- User         : un compte (pseudo + mot de passe + crédits)
- OwnedCard    : combien d'exemplaires d'une Card un User possède
- PackState    : l'état des packs gratuits d'un joueur (combien il en a
                 en stock, quand le prochain arrive) + ses jetons de pack
                 achetés au shop (illimités, séparés du cap de 3)
- Listing      : une carte mise en vente sur le marché
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, ForeignKey, DateTime, Enum, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_id():
    return str(uuid.uuid4())


class Tier(str, enum.Enum):
    # ordre de rareté : commune < rare < gold < secrete < speciale < epique < legendaire
    commune = "commune"
    rare = "rare"
    gold = "gold"            # moment mémorable d'un match IRL (créée par l'admin)
    secrete = "secrete"      # jamais dans les packs : se débloque par fusion de doublons
    speciale = "speciale"    # créée chaque vendredi 17h pour les stars du 1v1 ; packs gagnés en 1v1 uniquement
    epique = "epique"
    legendaire = "legendaire"


class Player(Base):
    __tablename__ = "players"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False, unique=True)
    poste = Column(String, nullable=False)  # GB / DEF / MIL / ATT
    photo_url = Column(String, nullable=True)  # ex: /photos/mathis.jpg

    # Statistiques de saison (vraie personne, pas liées à une carte précise)
    matches_joues = Column(Integer, nullable=False, default=0)
    buts = Column(Integer, nullable=False, default=0)
    passes_decisives = Column(Integer, nullable=False, default=0)
    cartons_jaunes = Column(Integer, nullable=False, default=0)
    cartons_rouges = Column(Integer, nullable=False, default=0)
    homme_du_match_count = Column(Integer, nullable=False, default=0)

    # Notes par poste (0-99). Seule celle correspondant au poste réel du
    # joueur est affichée sur sa carte. Réglées manuellement par l'admin.
    note_attaquant = Column(Integer, nullable=False, default=50)
    note_milieu = Column(Integer, nullable=False, default=50)
    note_defenseur = Column(Integer, nullable=False, default=50)
    note_gardien = Column(Integer, nullable=False, default=50)

    cards = relationship("Card", back_populates="player", cascade="all, delete-orphan")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (UniqueConstraint("player_id", "tier", name="one_card_per_tier_per_player"),)

    id = Column(String, primary_key=True, default=gen_id)
    player_id = Column(String, ForeignKey("players.id"), nullable=False)
    tier = Column(Enum(Tier), nullable=False)
    vitesse = Column(Integer, nullable=False)
    tir = Column(Integer, nullable=False)
    note = Column(Integer, nullable=True)     # note fixe de la carte (cartes spéciales : 80, +1 à chaque nouvelle récompense)

    player = relationship("Player", back_populates="cards")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    pseudo = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    token = Column(String, nullable=True, unique=True)  # régénéré à chaque connexion
    credits = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_test = Column(Boolean, nullable=False, default=False)  # compte de test : packs illimités, exclu du classement
    elo = Column(Integer, nullable=False, default=1000)  # classement des matchs 1v1

    owned_cards = relationship("OwnedCard", back_populates="user", cascade="all, delete-orphan")
    pack_state = relationship("PackState", back_populates="user", uselist=False, cascade="all, delete-orphan")


class OwnedCard(Base):
    __tablename__ = "owned_cards"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="one_row_per_user_per_card"),)

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)

    user = relationship("User", back_populates="owned_cards")
    card = relationship("Card")


class PackState(Base):
    __tablename__ = "pack_states"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    stored_packs = Column(Integer, nullable=False, default=3)   # packs gratuits en stock (0 à 3)
    last_regen_at = Column(DateTime, default=datetime.utcnow)   # dernier calcul de régénération
    shop_pack_tokens = Column(Integer, nullable=False, default=0)  # jetons de pack CLASSIQUE (achetés au shop / offerts)
    rare_pack_tokens = Column(Integer, nullable=False, default=0)       # jetons de pack rare
    epic_pack_tokens = Column(Integer, nullable=False, default=0)       # jetons de pack épique
    legendary_pack_tokens = Column(Integer, nullable=False, default=0)  # jetons de pack légendaire
    match_pack_tokens = Column(Integer, nullable=False, default=0)      # jetons de pack match (récompense des victoires 1v1)

    user = relationship("User", back_populates="pack_state")


class Match(Base):
    __tablename__ = "matches"

    id = Column(String, primary_key=True, default=gen_id)
    date = Column(DateTime, nullable=False)
    opponent = Column(String, nullable=False)
    score_us = Column(Integer, nullable=False)
    score_them = Column(Integer, nullable=False)
    motm_player_id = Column(String, ForeignKey("players.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # de quoi pouvoir annuler proprement ce match plus tard (NULL pour les matchs enregistrés avant)
    lineup_json = Column(Text, nullable=True)    # joueurs présents (matchs joués +1)
    yellow_json = Column(Text, nullable=True)    # cartons jaunes
    red_json = Column(Text, nullable=True)       # cartons rouges
    epics_json = Column(Text, nullable=True)     # joueurs dont la carte épique a été créée PAR ce match
    stade = Column(String, nullable=True)        # nom du stade où le match a été joué
    stade_created = Column(Boolean, default=False)   # True si la carte du stade a été créée PAR ce match

    motm_player = relationship("Player")
    moments = relationship("MatchMoment", cascade="all, delete-orphan")
    goals = relationship("MatchGoal", cascade="all, delete-orphan")
    assists = relationship("MatchAssist", cascade="all, delete-orphan")


class MatchMoment(Base):
    """Un moment mémorable d'un match IRL : il donne naissance à une carte gold (un 'joueur' de poste MOMENT)."""
    __tablename__ = "match_moments"

    id = Column(String, primary_key=True, default=gen_id)
    match_id = Column(String, ForeignKey("matches.id"), nullable=False)
    moment_player_id = Column(String, ForeignKey("players.id"), nullable=False)   # la 'fiche' qui porte la carte gold
    real_player_name = Column(String, nullable=False)                              # le joueur qui a fait l'action
    action = Column(String, nullable=False)                                        # "Petit pont", "Sauvetage"...

    moment_player = relationship("Player")


class PushSubscription(Base):
    """Un appareil (téléphone, ordinateur) qui a accepté les notifications. Un joueur peut en avoir plusieurs."""
    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    endpoint = Column(String, nullable=False, unique=True)     # adresse fournie par Google / Apple / Mozilla
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_ok_at = Column(DateTime, nullable=True)
    failures = Column(Integer, nullable=False, default=0)


class NotifPref(Base):
    """Quels types de notifications un joueur veut recevoir (tout est activé par défaut)."""
    __tablename__ = "notif_prefs"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    packs = Column(Boolean, nullable=False, default=True)
    cards = Column(Boolean, nullable=False, default=True)
    duels = Column(Boolean, nullable=False, default=True)
    market = Column(Boolean, nullable=False, default=True)


class NotifState(Base):
    """Où en est le joueur côté packs gratuits (0 = aucun, 1 = au moins un, 3 = tous pleins) pour ne prévenir qu'une fois."""
    __tablename__ = "notif_state"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    pack_level = Column(Integer, nullable=False, default=0)


class PushOutbox(Base):
    """File d'attente des notifications : les actions du jeu y déposent un message, une tâche de fond l'envoie."""
    __tablename__ = "push_outbox"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    kind = Column(String, nullable=False)                      # packs | cards | duels | market | admin
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    url = Column(String, nullable=False, default="/")
    tag = Column(String, nullable=True)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    send_after = Column(DateTime, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    skipped = Column(String, nullable=True)                    # raison si elle n'a pas été envoyée
    attempts = Column(Integer, nullable=False, default=0)
    force = Column(Boolean, nullable=False, default=False)     # message de l'admin : ignore la nuit et le plafond


class AppSetting(Base):
    """Petits réglages gardés en base (ex. les clés VAPID, générées une seule fois)."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


class JobRun(Base):
    """Mémorise la dernière exécution d'une tâche planifiée (ex. cartes spéciales du vendredi 17h)."""
    __tablename__ = "job_runs"

    name = Column(String, primary_key=True)
    last_slot = Column(DateTime, nullable=True)      # le créneau (vendredi 17h, en UTC) déjà traité
    last_run_at = Column(DateTime, nullable=True)
    last_report = Column(Text, nullable=True)


class UpcomingMatch(Base):
    """Un match réel à venir de l'équipe (affiché dans l'onglet Actualité)."""
    __tablename__ = "upcoming_matches"

    id = Column(String, primary_key=True, default=gen_id)
    date = Column(DateTime, nullable=False)
    opponent = Column(String, nullable=False)
    location = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MatchGoal(Base):
    __tablename__ = "match_goals"

    id = Column(String, primary_key=True, default=gen_id)
    match_id = Column(String, ForeignKey("matches.id"), nullable=False)
    player_id = Column(String, ForeignKey("players.id"), nullable=False)
    count = Column(Integer, nullable=False, default=1)

    player = relationship("Player")


class MatchAssist(Base):
    __tablename__ = "match_assists"

    id = Column(String, primary_key=True, default=gen_id)
    match_id = Column(String, ForeignKey("matches.id"), nullable=False)
    player_id = Column(String, ForeignKey("players.id"), nullable=False)
    count = Column(Integer, nullable=False, default=1)

    player = relationship("Player")


class Team(Base):
    """LEGACY (ancien 1v1 à 11 joueurs) : n'est plus utilisé. La table est conservée pour ne
    perdre aucune donnée et ne pas casser les clés étrangères existantes."""
    __tablename__ = "teams"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    formation = Column(String, nullable=False)   # "4-4-2" / "4-3-3" / "3-4-3" / "5-3-2"
    stake = Column(Integer, nullable=False, default=2)  # mise proposée (1 à 10 crédits)
    fan_card_id = Column(String, ForeignKey("cards.id"), nullable=True)  # carte Fan optionnelle (bonus %)
    updated_at = Column(DateTime, default=datetime.utcnow)

    slots = relationship("TeamSlot", cascade="all, delete-orphan")


class TeamSlot(Base):
    """LEGACY (ancien 1v1 à 11 joueurs) : n'est plus utilisé."""
    __tablename__ = "team_slots"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("teams.user_id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    slot_category = Column(String, nullable=False)  # GB / DEF / MIL / ATT

    card = relationship("Card")


class Duel(Base):
    """Un match 1v1 résolu entre deux équipes, avec son résultat et l'évolution Elo."""
    __tablename__ = "duels"

    id = Column(String, primary_key=True, default=gen_id)
    challenger_id = Column(String, ForeignKey("users.id"), nullable=False)
    defender_id = Column(String, ForeignKey("users.id"), nullable=False)
    stake = Column(Integer, nullable=False)
    formation_challenger = Column(String, nullable=False)
    formation_defender = Column(String, nullable=False)
    score_challenger = Column(Integer, nullable=False)
    score_defender = Column(Integer, nullable=False)
    elo_challenger_before = Column(Integer, nullable=False)
    elo_defender_before = Column(Integer, nullable=False)
    elo_challenger_after = Column(Integer, nullable=False)
    elo_defender_after = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # ajoutés avec le 1v1 à 5 joueurs (NULL pour les anciens matchs)
    tactic_challenger = Column(String, nullable=True)
    tactic_defender = Column(String, nullable=True)
    events_json = Column(Text, nullable=True)    # chronologie racontée du match
    lineups_json = Column(Text, nullable=True)   # compositions des deux équipes au moment du match

    challenger = relationship("User", foreign_keys=[challenger_id])
    defender = relationship("User", foreign_keys=[defender_id])


class MatchProposal(Base):
    """Un défi 1v1 en attente : l'équipe, la tactique (secrète) et la mise d'un joueur.
    La mise est retirée de ses crédits à la création (séquestre) et rendue s'il annule."""
    __tablename__ = "match_proposals"

    id = Column(String, primary_key=True, default=gen_id)
    creator_id = Column(String, ForeignKey("users.id"), nullable=False)
    stake = Column(Integer, nullable=False)
    formation = Column(String, nullable=False)
    tactic = Column(String, nullable=False)
    captain_card_id = Column(String, ForeignKey("cards.id"), nullable=True)
    fan_card_id = Column(String, ForeignKey("cards.id"), nullable=True)
    mascot_card_id = Column(String, ForeignKey("cards.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User")
    slots = relationship("ProposalSlot", cascade="all, delete-orphan")
    equipment = relationship("ProposalEquipment", cascade="all, delete-orphan")


class ProposalEquipment(Base):
    """Une carte Équipement jointe à un défi 1v1 (jusqu'à MAX_EQUIPMENT par équipe)."""
    __tablename__ = "proposal_equipment"

    id = Column(String, primary_key=True, default=gen_id)
    proposal_id = Column(String, ForeignKey("match_proposals.id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)

    card = relationship("Card")


class ProposalSlot(Base):
    __tablename__ = "proposal_slots"

    id = Column(String, primary_key=True, default=gen_id)
    proposal_id = Column(String, ForeignKey("match_proposals.id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    slot_category = Column(String, nullable=False)  # GB / DEF / MC / ATT

    card = relationship("Card")


class Listing(Base):
    __tablename__ = "listings"

    id = Column(String, primary_key=True, default=gen_id)
    seller_id = Column(String, ForeignKey("users.id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    seller = relationship("User")
    card = relationship("Card")
