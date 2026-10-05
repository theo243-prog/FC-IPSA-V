from typing import List, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    pseudo: str = Field(min_length=2, max_length=24)
    password: str = Field(min_length=4, max_length=72)


class LoginRequest(BaseModel):
    pseudo: str
    password: str


class OpenPackRequest(BaseModel):
    use_shop_token: bool = False          # ancien paramètre : équivaut à pack_type="classique"
    pack_type: Optional[str] = None       # None = pack gratuit ; sinon classique / rare / epique / legendaire


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
    slot_category: str  # GB / DEF / MC / ATT


class TeamPayload(BaseModel):
    formation: str                      # "2-1-1" | "1-2-1" | "1-1-2"
    tactic: str                         # "pressing" | "possession" | "contre"
    slots: List[TeamSlotEntry]          # 5 cartes, chacune avec son emplacement
    captain_card_id: Optional[str] = None
    fan_card_id: Optional[str] = None
    equipment_card_ids: List[str] = []   # jusqu'à 3 cartes Équipement (bonus d'équipe)


class CreateProposalRequest(TeamPayload):
    stake: int = Field(ge=1, le=10)


# ----------------------------------------------------------- Admin -----

class AdminDeleteUserRequest(BaseModel):
    pseudo: str


class AdminDeletePlayerRequest(BaseModel):
    player_name: str


class AdminCreateCardRequest(BaseModel):
    player_name: str
    tier: str  # "commune" | "rare" | "epique" | "legendaire"
    grant_to_pseudo: Optional[str] = None


class AdminDeleteCardRequest(BaseModel):
    player_name: str
    tier: str  # "commune" | "rare" | "epique" | "legendaire"


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
    stade: Optional[str] = None     # nom du stade ; sa carte (commune) est créée s'il n'existe pas encore


class AdminUpdateCardStatsRequest(BaseModel):
    player_name: str
    tier: str  # "commune" | "rare" | "epique" | "legendaire"
    vitesse: int = Field(ge=0, le=99)
    tir: int = Field(ge=0, le=99)


class AdminGrantLegendaryRequest(BaseModel):
    player_name: str
    vitesse: int = Field(default=0, ge=0, le=99)  # n'est plus utilisé (note unique par rareté)
    tir: int = Field(default=0, ge=0, le=99)      # n'est plus utilisé (note unique par rareté)
    grant_to_pseudo: Optional[str] = None  # si fourni, donne aussi 1 exemplaire à ce joueur


class AdminGrantCreditsRequest(BaseModel):
    pseudo: str
    amount: int


class AdminGrantPacksRequest(BaseModel):
    pseudo: str
    count: int = Field(gt=0)  # ajoutés aux jetons, hors cap des 3 packs gratuits
    pack_type: str = "classique"  # classique / rare / epique / legendaire


class AdminDeleteMatchRequest(BaseModel):
    """Identifie le match réel à annuler : soit son id, soit sa date + son adversaire."""
    match_id: Optional[str] = None
    date: Optional[str] = None       # "2026-10-12"
    opponent: Optional[str] = None


class AdminAddUpcomingMatchRequest(BaseModel):
    date: str                        # "2026-10-12" ou "2026-10-12 14:30"
    opponent: str
    location: Optional[str] = None


class AdminDeleteUpcomingMatchRequest(BaseModel):
    upcoming_id: Optional[str] = None
    date: Optional[str] = None
    opponent: Optional[str] = None


class AdminCreateMascotRequest(BaseModel):
    name: str = "Le Loup"                       # nom affiché sur les cartes
    grant_to_pseudo: Optional[str] = None       # si fourni : offre 1 exemplaire de chaque rareté à ce compte


class EquipmentItem(BaseModel):
    name: str
    tier: str = "commune"           # commune | rare | epique | legendaire


class AdminCreateEquipmentRequest(BaseModel):
    items: Optional[List[EquipmentItem]] = None     # vide : crée la liste officielle du club
    grant_to_pseudo: Optional[str] = None           # offre 1 exemplaire de chaque carte traitée à ce compte
