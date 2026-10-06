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
    equipment_card_ids: List[str] = []   # 1 carte Équipement au maximum (bonus d'équipe)
    mascot_card_id: Optional[str] = None  # carte Loup (la mascotte) : emplacement distinct du Fan


class CreateProposalRequest(TeamPayload):
    stake: int = Field(ge=1, le=10)


# ----------------------------------------------------------- Admin -----

class AdminDeleteUserRequest(BaseModel):
    pseudo: str


class AdminDeletePlayerRequest(BaseModel):
    player_name: str


class AdminCreateCardRequest(BaseModel):
    player_name: str
    tier: str  # "commune" | "rare" | "gold" | "secrete" | "speciale" | "epique" | "legendaire"
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


class MomentEntry(BaseModel):
    player_name: str         # le joueur qui a fait l'action
    action: str              # "Petit pont", "Dribble", "Sauvetage", "Fausse touche"...


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
    moments: List["MomentEntry"] = []   # moments mémorables : chacun crée une carte GOLD


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


class UnlockSecretRequest(BaseModel):
    card_id: str


class AdminRunWeeklyRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=60)       # fenêtre de matchs 1v1 examinée (les N derniers jours)
    dry_run: bool = False                           # True : montre qui gagnerait, sans rien créer


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)


class PushPrefsRequest(BaseModel):
    packs: Optional[bool] = None
    cards: Optional[bool] = None
    duels: Optional[bool] = None
    market: Optional[bool] = None


class AdminPushBroadcastRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=250)
    url: str = "/"
    pseudo: Optional[str] = None       # vide : tous les appareils abonnés


class AdminCreatePlayerRequest(BaseModel):
    name: str
    poste: str = "X"                       # ATT, MC, DEF, GB, X (pas encore défini) ou FAN (FAN/Rôle possible)
    photo_url: Optional[str] = None        # ex. "/photos/mathis.jpg"
    with_rare: Optional[bool] = None       # carte rare ? par défaut : oui pour un joueur, non pour un fan
    grant_to_pseudo: Optional[str] = None  # offre 1 exemplaire de chaque carte créée à ce compte
    force: bool = False                    # True : crée même si un nom très proche existe (Léo / Leo)


class AdminReset1v1Request(BaseModel):
    scope: str = "test"            # "test" : les matchs où un compte de test a joué ; "all" : tous les matchs ; "none" : aucun (recalcule seulement l'Elo)
    recompute_elo: bool = True     # recalcule l'Elo de tout le monde à partir des matchs qui restent
    dry_run: bool = True           # True (par défaut) : montre ce qui serait fait, sans rien modifier
