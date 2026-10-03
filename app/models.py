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
    Column, String, Integer, Float, Boolean, ForeignKey, DateTime, Enum, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_id():
    return str(uuid.uuid4())


class Tier(str, enum.Enum):
    commune = "commune"
    rare = "rare"
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
    shop_pack_tokens = Column(Integer, nullable=False, default=0)  # jetons achetés au shop

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

    motm_player = relationship("Player")
    goals = relationship("MatchGoal", cascade="all, delete-orphan")
    assists = relationship("MatchAssist", cascade="all, delete-orphan")


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


class Listing(Base):
    __tablename__ = "listings"

    id = Column(String, primary_key=True, default=gen_id)
    seller_id = Column(String, ForeignKey("users.id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    seller = relationship("User")
    card = relationship("Card")
