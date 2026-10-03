from typing import List, Optional

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


# ------------------------------------------------------- Équipes & duels -----

class TeamSlotEntry(BaseModel):
    card_id: str
    slot_category: str  # GB / DEF / MIL / ATT


class SaveTeamRequest(BaseModel):
    formation: str  # "4-4-2" | "4-3-3" | "3-4-3" | "5-3-2"
    stake: int = Field(ge=1, le=10)
    slots: List[TeamSlotEntry]


class ChallengeRequest(BaseModel):
    defender_pseudo: str


# ----------------------------------------------------------- Admin -----

class AdminDeleteUserRequest(BaseModel):
    pseudo: str


class AdminDeletePlayerRequest(BaseModel):
    player_name: str


class AdminSetPlayerPhotoRequest(BaseModel):
    player_name: str
    photo_url: str  # ex: "/photos/mathis.jpg" ou une URL complète


class AdminSetTestAccountRequest(BaseModel):
    pseudo: str
    is_test: bool = True


class AdminSetPlayerPosteRequest(BaseModel):
    player_name: str
    poste: str  # ATT, MC, DEF, GB (ou X / FAN...)


class BulkNoteEntry(BaseModel):
    player_name: str
    note_attaquant: int = Field(default=50, ge=0, le=99)
    note_milieu: int = Field(default=50, ge=0, le=99)
    note_defenseur: int = Field(default=50, ge=0, le=99)
    note_gardien: int = Field(default=50, ge=0, le=99)


class AdminSetNotesBulkRequest(BaseModel):
    notes: List[BulkNoteEntry]


class BulkPosteEntry(BaseModel):
    player_name: str
    poste: str


class AdminSetPostesBulkRequest(BaseModel):
    postes: List[BulkPosteEntry]


class AdminSetPlayerNotesRequest(BaseModel):
    player_name: str
    note_attaquant: Optional[int] = Field(default=None, ge=0, le=99)
    note_milieu: Optional[int] = Field(default=None, ge=0, le=99)
    note_defenseur: Optional[int] = Field(default=None, ge=0, le=99)
    note_gardien: Optional[int] = Field(default=None, ge=0, le=99)


class GoalEntry(BaseModel):
    player_name: str
    count: int = Field(default=1, ge=1)


class AssistEntry(BaseModel):
    player_name: str
    count: int = Field(default=1, ge=1)


class AdminRecordMatchRequest(BaseModel):
    date: str  # "2026-10-12"
    opponent: str
    score_us: int = Field(ge=0)
    score_them: int = Field(ge=0)
    buteurs: List[GoalEntry] = []
    passeurs: List[AssistEntry] = []
    homme_du_match: Optional[str] = None
    lineup: List[str] = []          # joueurs ayant joué ce match (pour matches_joues)
    cartons_jaunes: List[str] = []
    cartons_rouges: List[str] = []


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
