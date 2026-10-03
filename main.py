"""
API du site de cartes FC Format A5.

Lancer en local :
    uvicorn app.main:app --reload
Puis ouvrir http://127.0.0.1:8000/docs pour tester chaque route.
"""
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from . import game_logic, schemas
from .models import User, Card, OwnedCard, PackState, Listing
from .security import hash_password, verify_password, generate_token, get_current_user

Base.metadata.create_all(bind=engine)

app = FastAPI(title="FC Format A5 — API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # en prod, remplace par l'URL exacte de ton frontend
    allow_methods=["*"],
    allow_headers=["*"],
)


def card_out(card: Card) -> dict:
    return {
        "id": card.id,
        "player_name": card.player.name,
        "poste": card.player.poste,
        "tier": card.tier.value,
        "vitesse": card.vitesse,
        "tir": card.tir,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- Auth ----

@app.post("/auth/register")
def register(payload: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter_by(pseudo=payload.pseudo).first():
        raise HTTPException(status_code=400, detail="Ce pseudo est déjà pris")

    user = User(
        pseudo=payload.pseudo,
        password_hash=hash_password(payload.password),
        token=generate_token(),
        credits=0,
    )
    db.add(user)
    db.flush()
    db.add(PackState(user_id=user.id, stored_packs=3, last_regen_at=datetime.utcnow(), shop_pack_tokens=0))
    db.commit()
    return {"token": user.token, "pseudo": user.pseudo}


@app.post("/auth/login")
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Pseudo ou mot de passe incorrect")
    user.token = generate_token()
    db.commit()
    return {"token": user.token, "pseudo": user.pseudo}


@app.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    game_logic.regen_user_packs(db, user)
    db.refresh(user.pack_state)
    return {
        "pseudo": user.pseudo,
        "credits": user.credits,
        "stored_packs": user.pack_state.stored_packs,
        "shop_pack_tokens": user.pack_state.shop_pack_tokens,
        "seconds_until_next_pack": game_logic.seconds_until_next_pack(user),
    }


# --------------------------------------------------------------- Packs ----

@app.post("/pack/open")
def open_pack(
    payload: schemas.OpenPackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = game_logic.open_pack_for_user(db, user, use_shop_token=payload.use_shop_token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Aucun pack disponible pour le moment")

    return {
        "credits_won": result["credits_won"],
        "cards_won": [card_out(c) for c in result["cards_won"]],
        "crafted": result["crafted"],
        "source": result["source"],
    }


# ---------------------------------------------------------- Collection ----

@app.get("/collection")
def get_collection(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    all_cards = db.query(Card).all()
    owned_rows = {o.card_id: o.quantity for o in db.query(OwnedCard).filter_by(user_id=user.id).all()}
    return [
        {**card_out(c), "quantity": owned_rows.get(c.id, 0)}
        for c in all_cards
    ]


@app.post("/collection/sell-duplicate")
def sell_duplicate(
    payload: schemas.SellDuplicateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        credits_gained = game_logic.sell_duplicate(db, user, payload.card_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Pas de doublon à vendre pour cette carte")
    return {"credits_gained": credits_gained, "credits_total": user.credits}


# -------------------------------------------------------------- Marché ----

@app.get("/market/listings")
def list_listings(db: Session = Depends(get_db)):
    listings = db.query(Listing).order_by(Listing.created_at.desc()).all()
    return [
        {
            "id": l.id,
            "seller_pseudo": l.seller.pseudo,
            "card": card_out(l.card),
            "price": l.price,
        }
        for l in listings
    ]


@app.post("/market/list")
def create_listing(
    payload: schemas.CreateListingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=payload.card_id).first()
    if not owned or owned.quantity < 1:
        raise HTTPException(status_code=400, detail="Tu ne possèdes pas cette carte")
    owned.quantity -= 1  # la carte est réservée tant que l'annonce est ouverte
    listing = Listing(seller_id=user.id, card_id=payload.card_id, price=payload.price)
    db.add(listing)
    db.commit()
    return {"id": listing.id}


@app.post("/market/buy/{listing_id}")
def buy_listing(listing_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = db.query(Listing).filter_by(id=listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Cette offre n'existe plus")
    if listing.seller_id == user.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas acheter ta propre offre")
    if user.credits < listing.price:
        raise HTTPException(status_code=400, detail="Pas assez de crédits")

    seller = listing.seller
    user.credits -= listing.price
    seller.credits += listing.price
    buyer_owned = game_logic.get_or_create_owned(db, user, listing.card)
    buyer_owned.quantity += 1
    db.delete(listing)
    db.commit()
    return {"status": "ok"}


@app.delete("/market/listings/{listing_id}")
def cancel_listing(listing_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    listing = db.query(Listing).filter_by(id=listing_id).first()
    if not listing or listing.seller_id != user.id:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    owned = game_logic.get_or_create_owned(db, user, listing.card)
    owned.quantity += 1
    db.delete(listing)
    db.commit()
    return {"status": "ok"}


# --------------------------------------------------------------- Shop -----

SHOP_ITEMS = {
    "pack_supplementaire": {"label": "Pack supplémentaire", "price": 40},
}


@app.get("/shop/items")
def shop_items():
    return [{"item": key, **value} for key, value in SHOP_ITEMS.items()]


@app.post("/shop/buy")
def shop_buy(payload: schemas.BuyShopItemRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = SHOP_ITEMS.get(payload.item)
    if not item:
        raise HTTPException(status_code=404, detail="Article inconnu")
    if user.credits < item["price"]:
        raise HTTPException(status_code=400, detail="Pas assez de crédits")
    user.credits -= item["price"]
    user.pack_state.shop_pack_tokens += 1
    db.commit()
    return {"credits_total": user.credits, "shop_pack_tokens": user.pack_state.shop_pack_tokens}


# --------------------------------------------------------- Classement -----

@app.get("/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    total_cards = db.query(Card).count()
    users = db.query(User).all()
    rows = []
    for u in users:
        owned_count = (
            db.query(OwnedCard)
            .filter(OwnedCard.user_id == u.id, OwnedCard.quantity > 0)
            .count()
        )
        completion = round(100 * owned_count / total_cards, 1) if total_cards else 0.0
        rows.append({"pseudo": u.pseudo, "completion_pct": completion, "credits": u.credits})
    rows.sort(key=lambda r: (-r["completion_pct"], -r["credits"]))
    return rows
