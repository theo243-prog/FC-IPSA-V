from typing import Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    pseudo: str = Field(min_length=2, max_length=24)
    password: str = Field(min_length=4, max_length=72)


class LoginRequest(BaseModel):
    pseudo: str
    password: str


class OpenPackRequest(BaseModel):
    use_shop_token: bool = False


class SellDuplicateRequest(BaseModel):
    card_id: str


class CreateListingRequest(BaseModel):
    card_id: str
    price: int = Field(gt=0)


class BuyShopItemRequest(BaseModel):
    item: str


# ----------------------------------------------------------- Admin -----

class AdminDeleteUserRequest(BaseModel):
    pseudo: str


class AdminUpdateCardStatsRequest(BaseModel):
    player_name: str
    tier: str  # "commune" | "rare" | "legendaire"
    vitesse: int = Field(ge=0, le=99)
    tir: int = Field(ge=0, le=99)


class AdminGrantLegendaryRequest(BaseModel):
    player_name: str
    vitesse: int = Field(ge=0, le=99)
    tir: int = Field(ge=0, le=99)
    grant_to_pseudo: Optional[str] = None  # si fourni, donne aussi 1 exemplaire à ce joueur


class AdminGrantCreditsRequest(BaseModel):
    pseudo: str
    amount: int


class AdminGrantPacksRequest(BaseModel):
    pseudo: str
    count: int = Field(gt=0)  # ajoutés aux jetons shop, hors cap des 3 packs gratuits
