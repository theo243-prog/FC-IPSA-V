"""
Tables de la base de données.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, ForeignKey, DateTime, Enum, UniqueConstraint
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
    poste = Column(String, nullable=False)

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
    token = Column(String, nullable=True, unique=True)
    credits = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    stored_packs = Column(Integer, nullable=False, default=3)
    last_regen_at = Column(DateTime, default=datetime.utcnow)
    shop_pack_tokens = Column(Integer, nullable=False, default=0)

    user = relationship("User", back_populates="pack_state")


class Listing(Base):
    __tablename__ = "listings"

    id = Column(String, primary_key=True, default=gen_id)
    seller_id = Column(String, ForeignKey("users.id"), nullable=False)
    card_id = Column(String, ForeignKey("cards.id"), nullable=False)
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    seller = relationship("User")
    card = relationship("Card")
