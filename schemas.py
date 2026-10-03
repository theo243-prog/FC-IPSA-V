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
