"""
API du site de cartes FC Format A5.

Lancer en local :
    uvicorn app.main:app --reload
Puis ouvrir http://127.0.0.1:8000/docs pour tester chaque route.
"""
import os
from datetime import datetime

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from . import game_logic, schemas
from .models import User, Card, Player, OwnedCard, PackState, Listing, Tier
from .security import hash_password, verify_password, generate_token, get_current_user

# Clé secrète pour les routes /admin/*. À définir dans Railway (Variables -> ADMIN_KEY).
# Tant qu'elle n'est pas définie, toutes les routes admin refusent l'accès par sécurité.
ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def require_admin(x_admin_key: str = Header(default=None)):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Clé admin manquante ou invalide")

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


@app.get("/users/{pseudo}/collection")
def get_user_collection(pseudo: str, db: Session = Depends(get_db)):
    """Collection PUBLIQUE d'un autre joueur (lecture seule), pour le classement."""
    user = db.query(User).filter_by(pseudo=pseudo).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    all_cards = db.query(Card).all()
    owned_rows = {o.card_id: o.quantity for o in db.query(OwnedCard).filter_by(user_id=user.id).all()}
    return [{**card_out(c), "quantity": owned_rows.get(c.id, 0)} for c in all_cards]


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


# ---------------------------------------------------------------- Admin ---
# Toutes ces routes exigent l'en-tête  X-Admin-Key: <ta clé secrète>
# (définie dans Railway -> Variables -> ADMIN_KEY). Rien de tout ça n'est
# accessible depuis le site normal, uniquement par toi via /docs ou un appel direct.

@app.post("/admin/delete-user", dependencies=[Depends(require_admin)])
def admin_delete_user(payload: schemas.AdminDeleteUserRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    db.query(Listing).filter_by(seller_id=user.id).delete()
    db.delete(user)  # supprime en cascade ses cartes possédées et son pack_state
    db.commit()
    return {"status": "ok", "deleted": payload.pseudo}


@app.post("/admin/delete-player", dependencies=[Depends(require_admin)])
def admin_delete_player(payload: schemas.AdminDeletePlayerRequest, db: Session = Depends(get_db)):
    """Retire un joueur de l'effectif (ses cartes, les exemplaires possédés par
    tout le monde, et les annonces du marché le concernant disparaissent aussi)."""
    player = db.query(Player).filter_by(name=payload.player_name).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    card_ids = [c.id for c in player.cards]
    if card_ids:
        db.query(Listing).filter(Listing.card_id.in_(card_ids)).delete(synchronize_session=False)
        db.query(OwnedCard).filter(OwnedCard.card_id.in_(card_ids)).delete(synchronize_session=False)
    db.delete(player)  # cascade : supprime aussi ses Card (commune/rare/légendaire)
    db.commit()
    return {"status": "ok", "deleted_player": payload.player_name, "cards_removed": len(card_ids)}


@app.post("/admin/update-card-stats", dependencies=[Depends(require_admin)])
def admin_update_card_stats(payload: schemas.AdminUpdateCardStatsRequest, db: Session = Depends(get_db)):
    try:
        tier = Tier(payload.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail="tier doit être commune, rare ou legendaire")
    card = (
        db.query(Card)
        .join(Player)
        .filter(Player.name == payload.player_name, Card.tier == tier)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="Carte introuvable pour ce joueur/tier")
    card.vitesse = payload.vitesse
    card.tir = payload.tir
    db.commit()
    return {"status": "ok", "card_id": card.id, "vitesse": card.vitesse, "tir": card.tir}


@app.post("/admin/grant-legendary", dependencies=[Depends(require_admin)])
def admin_grant_legendary(payload: schemas.AdminGrantLegendaryRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter_by(name=payload.player_name).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")

    legend = db.query(Card).filter_by(player_id=player.id, tier=Tier.legendaire).first()
    if not legend:
        legend = Card(player_id=player.id, tier=Tier.legendaire, vitesse=payload.vitesse, tir=payload.tir)
        db.add(legend)
        db.flush()
    else:
        legend.vitesse = payload.vitesse
        legend.tir = payload.tir

    granted_to = None
    if payload.grant_to_pseudo:
        user = db.query(User).filter_by(pseudo=payload.grant_to_pseudo).first()
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable pour grant_to_pseudo")
        owned = game_logic.get_or_create_owned(db, user, legend)
        owned.quantity += 1
        granted_to = user.pseudo

    db.commit()
    return {"status": "ok", "card_id": legend.id, "granted_to": granted_to}


@app.post("/admin/grant-credits", dependencies=[Depends(require_admin)])
def admin_grant_credits(payload: schemas.AdminGrantCreditsRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.credits += payload.amount
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "credits_total": user.credits}


@app.post("/admin/grant-packs", dependencies=[Depends(require_admin)])
def admin_grant_packs(payload: schemas.AdminGrantPacksRequest, db: Session = Depends(get_db)):
    """
    Ajoute des packs à un joueur SANS toucher au cap de 3 packs gratuits —
    ils atterrissent dans ses jetons shop (illimités), utilisables à tout moment.
    Idéal pour offrir des packs aux supporters présents un jour de match.
    """
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.pack_state.shop_pack_tokens += payload.count
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "shop_pack_tokens": user.pack_state.shop_pack_tokens}
