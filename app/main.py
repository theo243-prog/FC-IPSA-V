"""
API du site de cartes FC Format A5.

Lancer en local :
    uvicorn app.main:app --reload
Puis ouvrir http://127.0.0.1:8000/docs pour tester chaque route.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import Base, engine, get_db, SessionLocal
from . import game_logic, duel_engine, schemas, weekly
from sqlalchemy import or_
from .models import (User, Card, Player, OwnedCard, PackState, Listing, Tier, Match, MatchGoal, MatchAssist,
                     Team, TeamSlot, Duel, MatchProposal, UpcomingMatch, MatchMoment, JobRun)
from .security import hash_password, verify_password, generate_token, get_current_user

# Clé secrète pour les routes /admin/*. À définir dans Railway (Variables -> ADMIN_KEY).
# Tant qu'elle n'est pas définie, toutes les routes admin refusent l'accès par sécurité.
ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def require_admin(x_admin_key: str = Header(default=None)):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Clé admin manquante ou invalide")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="FC IPSA V — API")

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
        "player_photo_url": card.player.photo_url,
        "display_note": game_logic.get_display_note(card.player, card.tier.value, card),
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


def pack_tokens_out(user: User) -> dict:
    ps = user.pack_state
    return {t: getattr(ps, spec["token_field"]) for t, spec in game_logic.PACK_TYPES.items()}


@app.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    game_logic.regen_user_packs(db, user)
    db.refresh(user.pack_state)
    tokens = pack_tokens_out(user)
    if user.is_test:
        # affichage clair pour un compte de test : pas de cap, pas d'attente
        return {
            "pseudo": user.pseudo,
            "credits": user.credits,
            "stored_packs": 99,
            "shop_pack_tokens": tokens["classique"],
            "pack_tokens": tokens,
            "seconds_until_next_pack": None,
            "is_test": True,
        }
    return {
        "pseudo": user.pseudo,
        "credits": user.credits,
        "stored_packs": user.pack_state.stored_packs,
        "shop_pack_tokens": tokens["classique"],
        "pack_tokens": tokens,
        "seconds_until_next_pack": game_logic.seconds_until_next_pack(user),
        "is_test": False,
    }


# --------------------------------------------------------------- Packs ----

@app.post("/pack/open")
def open_pack(
    payload: schemas.OpenPackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pack_type = payload.pack_type or ("classique" if payload.use_shop_token else "free")
    try:
        result = game_logic.open_pack_for_user(db, user, pack_type=pack_type)
    except ValueError as e:
        if str(e) == "tier_unavailable":
            raise HTTPException(status_code=400, detail="Ce pack n'est pas encore disponible : aucune carte de cette rareté n'existe cette saison")
        if str(e) == "unknown_pack":
            raise HTTPException(status_code=400, detail="Type de pack inconnu")
        raise HTTPException(status_code=400, detail="Aucun pack disponible pour le moment")

    return {
        "credits_won": result["credits_won"],
        "cards_won": [{**card_out(c), "is_new": flag} for c, flag in zip(result["cards_won"], result["new_flags"])],
        "crafted": result["crafted"],
        "source": result["source"],
        "pack_type": result["pack_type"],
    }


# ---------------------------------------------------------- Collection ----

@app.get("/collection")
def get_collection(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    all_cards = db.query(Card).all()
    owned_rows = {o.card_id: o.quantity for o in db.query(OwnedCard).filter_by(user_id=user.id).all()}
    qty_by_player = {}                      # joueur -> quantités possédées en commune / rare (pour la jauge de fusion)
    for c in all_cards:
        if c.tier in (Tier.commune, Tier.rare):
            qty_by_player.setdefault(c.player_id, {})[c.tier.value] = owned_rows.get(c.id, 0)
    out = []
    for c in all_cards:
        row = {**card_out(c), "quantity": owned_rows.get(c.id, 0)}
        if c.tier == Tier.secrete:
            q = qty_by_player.get(c.player_id, {})
            points = game_logic.fusion_points(q.get("commune", 0), q.get("rare", 0))
            row["fusion"] = {"points": points, "needed": game_logic.SECRET_FUSION_COST,
                             "ready": points >= game_logic.SECRET_FUSION_COST and row["quantity"] == 0}
        out.append(row)
    return out


@app.post("/collection/unlock-secret")
def unlock_secret(payload: schemas.UnlockSecretRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Débloque une carte secrète en fusionnant des doublons (100 points : commune = 1, rare = 5)."""
    try:
        result = game_logic.unlock_secret(db, user, payload.card_id)
    except ValueError as e:
        messages = {"not_secret": "Cette carte n'est pas une carte secrète", "already_owned": "Tu as déjà cette carte secrète",
                    "not_enough": "Pas assez de doublons : il faut %d points (commune = 1, rare = 5)" % game_logic.SECRET_FUSION_COST}
        raise HTTPException(status_code=400, detail=messages.get(str(e), "Fusion impossible"))
    return {"status": "ok", **result}


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


@app.get("/players/{player_name}/detail")
def player_detail(player_name: str, tier: str = "commune", db: Session = Depends(get_db)):
    """Fiche d'un joueur. `tier` = rareté de la carte sur laquelle on a cliqué
    (détermine l'unique note affichée)."""
    player = db.query(Player).filter_by(name=player_name).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    try:
        card = db.query(Card).filter_by(player_id=player.id, tier=Tier(tier)).first()
    except ValueError:
        card = None
    moment = None
    if game_logic.card_kind(player) == "moment":          # carte gold : l'action, le joueur, le match
        mm = db.query(MatchMoment).filter_by(moment_player_id=player.id).first()
        if mm:
            m = db.get(Match, mm.match_id)
            moment = {"player": mm.real_player_name, "action": mm.action,
                      "opponent": m.opponent if m else None, "date": m.date.date().isoformat() if m else None}
    return {
        "name": player.name,
        "moment": moment,
        "poste": player.poste,
        "photo_url": player.photo_url,
        "matches_joues": player.matches_joues,
        "buts": player.buts,
        "passes_decisives": player.passes_decisives,
        "cartons_jaunes": player.cartons_jaunes,
        "cartons_rouges": player.cartons_rouges,
        "homme_du_match_count": player.homme_du_match_count,
        "tier": tier,
        "display_note": game_logic.get_display_note(player, tier, card),
    }


@app.get("/matches")
def list_matches(db: Session = Depends(get_db)):
    matches = db.query(Match).order_by(Match.date.desc(), Match.created_at.desc()).all()
    return [
        {
            "id": m.id,
            "date": m.date.date().isoformat(),
            "opponent": m.opponent,
            "stade": m.stade,
            "moments": [{"player": mm.real_player_name, "action": mm.action} for mm in m.moments],
            "score_us": m.score_us,
            "score_them": m.score_them,
            "homme_du_match": m.motm_player.name if m.motm_player else None,
            "buteurs": [{"player_name": g.player.name, "count": g.count} for g in m.goals],
            "passeurs": [{"player_name": a.player.name, "count": a.count} for a in m.assists],
        }
        for m in matches
    ]


@app.get("/matches/upcoming")
def list_upcoming_matches(db: Session = Depends(get_db)):
    rows = db.query(UpcomingMatch).order_by(UpcomingMatch.date.asc()).all()
    return [{
        "id": u.id, "date": u.date.date().isoformat(),
        "time": u.date.strftime("%H:%M") if (u.date.hour or u.date.minute) else None,
        "opponent": u.opponent, "location": u.location,
    } for u in rows]


@app.get("/players/stats")
def players_stats(db: Session = Depends(get_db)):
    """Statistiques RÉELLES de saison des joueurs (hors supporters), classées par buts."""
    players = [p for p in db.query(Player).all() if game_logic.card_kind(p) == "joueur"]
    players.sort(key=lambda p: (-p.buts, -p.passes_decisives, -p.homme_du_match_count, -p.matches_joues, p.name))
    return [{
        "name": p.name, "poste": p.poste, "matches_joues": p.matches_joues, "buts": p.buts,
        "passes_decisives": p.passes_decisives, "homme_du_match_count": p.homme_du_match_count,
    } for p in players]


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


# ---------------------------------------------------- Matchs 1v1 (5 joueurs) -----

def duel_call(fn, *args, **kwargs):
    """Exécute une fonction du moteur de duel en transformant ses erreurs en réponses HTTP."""
    try:
        return fn(*args, **kwargs)
    except duel_engine.DuelError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.get("/duel/config")
def duel_config():
    return duel_engine.get_config()


@app.get("/duel/board")
def duel_board(db: Session = Depends(get_db)):
    return duel_engine.duel_board(db)


@app.get("/duel/history")
def duel_history(limit: int = 15, db: Session = Depends(get_db)):
    return duel_engine.duel_history(db, max(1, min(limit, 50)))


@app.get("/duel/history/{duel_id}")
def duel_recap(duel_id: str, db: Session = Depends(get_db)):
    return duel_call(duel_engine.duel_recap, db, duel_id)


@app.get("/duel/card-stats")
def duel_card_stats(limit: int = 3, db: Session = Depends(get_db)):
    """Les cartes les plus utilisées / les plus décisives (buts, passes) dans les matchs 1v1."""
    limit = max(1, min(limit, 10))
    used, goals, assists = duel_engine.duel_card_stats(db)

    def top(counter):
        out = []
        for (name, tier), n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])):
            try:
                card = db.query(Card).join(Player).filter(Player.name == name, Card.tier == Tier(tier)).first()
            except ValueError:
                card = None
            if card:   # une carte supprimée depuis (ex. épique retirée) n'apparaît plus
                out.append({"card": card_out(card), "count": n})
            if len(out) >= limit:
                break
        return out

    return {"most_used": top(used), "top_scorers": top(goals), "top_assisters": top(assists)}


@app.get("/duel/proposals")
def duel_proposals(db: Session = Depends(get_db)):
    return duel_engine.list_proposals(db)


@app.post("/duel/proposals")
def create_duel_proposal(payload: schemas.CreateProposalRequest, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    slots = [{"card_id": s.card_id, "slot_category": s.slot_category} for s in payload.slots]
    proposal = duel_call(duel_engine.create_proposal, db, user, payload.formation, payload.tactic, payload.stake,
                         slots, payload.captain_card_id, payload.fan_card_id, payload.equipment_card_ids, payload.mascot_card_id)
    return {"id": proposal.id, "credits": user.credits}


@app.delete("/duel/proposals/{proposal_id}")
def cancel_duel_proposal(proposal_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    proposal = db.query(MatchProposal).filter_by(id=proposal_id).first()
    if not proposal or proposal.creator_id != user.id:
        raise HTTPException(status_code=404, detail="Défi introuvable")
    duel_engine.cancel_proposal(db, proposal)
    db.commit()
    return {"status": "ok", "credits": user.credits}


@app.post("/duel/proposals/{proposal_id}/play")
def play_duel_proposal(proposal_id: str, payload: schemas.TeamPayload, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    slots = [{"card_id": s.card_id, "slot_category": s.slot_category} for s in payload.slots]
    return duel_call(duel_engine.play_proposal, db, user, proposal_id, payload.formation, payload.tactic, slots,
                     payload.captain_card_id, payload.fan_card_id, payload.equipment_card_ids, payload.mascot_card_id)


# --------------------------------------------------------------- Shop -----

@app.get("/shop/items")
def shop_items(db: Session = Depends(get_db)):
    counts = game_logic.tier_card_counts(db)
    return [
        {
            "item": "pack_" + key,
            "pack_type": key,
            "label": spec["label"],
            "price": spec["price"],
            "description": spec["description"],
            "available": game_logic.pack_available(counts, key),
        }
        for key, spec in game_logic.PACK_TYPES.items()
        if spec["price"] is not None      # le pack match se gagne en 1v1, il ne s'achète pas
    ]


@app.post("/shop/buy")
def shop_buy(payload: schemas.BuyShopItemRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pack_type = payload.item[len("pack_"):] if payload.item.startswith("pack_") else None
    spec = game_logic.PACK_TYPES.get(pack_type)
    if not spec or spec["price"] is None:
        raise HTTPException(status_code=404, detail="Article inconnu")
    if not game_logic.pack_available(game_logic.tier_card_counts(db), pack_type):
        raise HTTPException(status_code=400, detail="Ce pack n'est pas encore disponible cette saison")
    if user.credits < spec["price"]:
        raise HTTPException(status_code=400, detail="Pas assez de crédits")
    user.credits -= spec["price"]
    field = spec["token_field"]
    setattr(user.pack_state, field, getattr(user.pack_state, field) + 1)
    db.commit()
    return {
        "credits_total": user.credits,
        "pack_type": pack_type,
        "pack_tokens": pack_tokens_out(user),
        "shop_pack_tokens": user.pack_state.shop_pack_tokens,
    }


# --------------------------------------------------------- Classement -----

@app.get("/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    total_cards = db.query(Card).count()
    users = db.query(User).filter_by(is_test=False).all()
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

def purge_card_rows(db: Session, card_ids: list):
    """Retire toute trace de ces cartes avant de les supprimer : défis 1v1 (annulés et remboursés),
    annonces du marché, exemplaires possédés, et anciennes équipes de l'ancien 1v1."""
    if not card_ids:
        return
    duel_engine.purge_card_references(db, card_ids)
    db.query(Listing).filter(Listing.card_id.in_(card_ids)).delete(synchronize_session=False)
    db.query(OwnedCard).filter(OwnedCard.card_id.in_(card_ids)).delete(synchronize_session=False)
    db.query(TeamSlot).filter(TeamSlot.card_id.in_(card_ids)).delete(synchronize_session=False)      # ancien 1v1
    db.query(Team).filter(Team.fan_card_id.in_(card_ids)).update({"fan_card_id": None}, synchronize_session=False)


@app.post("/admin/delete-user", dependencies=[Depends(require_admin)])
def admin_delete_user(payload: schemas.AdminDeleteUserRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    db.query(Listing).filter_by(seller_id=user.id).delete()
    for proposal in db.query(MatchProposal).filter_by(creator_id=user.id).all():
        db.delete(proposal)          # ses défis ouverts (le compte est supprimé, pas de remboursement utile)
    db.flush()
    db.query(Duel).filter(or_(Duel.challenger_id == user.id, Duel.defender_id == user.id)).delete(synchronize_session=False)
    db.query(TeamSlot).filter_by(user_id=user.id).delete()      # ancien 1v1
    db.query(Team).filter_by(user_id=user.id).delete()          # ancien 1v1
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
    purge_card_rows(db, card_ids)
    db.query(MatchMoment).filter(MatchMoment.moment_player_id == player.id).delete(synchronize_session=False)
    db.flush()
    db.delete(player)  # cascade : supprime aussi ses Card (commune/rare/légendaire)
    db.commit()
    return {"status": "ok", "deleted_player": payload.player_name, "cards_removed": len(card_ids)}


@app.post("/admin/set-player-photo", dependencies=[Depends(require_admin)])
def admin_set_player_photo(payload: schemas.AdminSetPlayerPhotoRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter_by(name=payload.player_name).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    player.photo_url = payload.photo_url
    db.commit()
    return {"status": "ok", "player": player.name, "photo_url": player.photo_url}


@app.post("/admin/set-player-poste", dependencies=[Depends(require_admin)])
def admin_set_player_poste(payload: schemas.AdminSetPlayerPosteRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter_by(name=payload.player_name).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    player.poste = payload.poste
    db.commit()
    return {"status": "ok", "player": player.name, "poste": player.poste}


@app.post("/admin/set-notes-bulk", dependencies=[Depends(require_admin)])
def admin_set_notes_bulk(payload: schemas.AdminSetNotesBulkRequest, db: Session = Depends(get_db)):
    """Règle les 4 notes (attaquant/milieu/defenseur/gardien) de plusieurs joueurs
    en un seul appel. Chaque joueur n'affichera que celle de son propre poste —
    les 3 autres valeurs ne servent qu'en réserve si son poste change un jour."""
    updated = []
    for entry in payload.notes:
        player = db.query(Player).filter_by(name=entry.player_name).first()
        if not player:
            raise HTTPException(status_code=404, detail=f"Joueur introuvable : {entry.player_name}")
        player.note_attaquant = entry.note_attaquant
        player.note_milieu = entry.note_milieu
        player.note_defenseur = entry.note_defenseur
        player.note_gardien = entry.note_gardien
        updated.append(player.name)
    db.commit()
    return {"status": "ok", "updated": updated}


@app.post("/admin/set-postes-bulk", dependencies=[Depends(require_admin)])
def admin_set_postes_bulk(payload: schemas.AdminSetPostesBulkRequest, db: Session = Depends(get_db)):
    updated = []
    for entry in payload.postes:
        player = db.query(Player).filter_by(name=entry.player_name).first()
        if not player:
            raise HTTPException(status_code=404, detail=f"Joueur introuvable : {entry.player_name}")
        player.poste = entry.poste
        updated.append({"player": player.name, "poste": player.poste})
    db.commit()
    return {"status": "ok", "updated": updated}


@app.post("/admin/set-player-notes", dependencies=[Depends(require_admin)])
def admin_set_player_notes(payload: schemas.AdminSetPlayerNotesRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter_by(name=payload.player_name).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    if payload.note_attaquant is not None: player.note_attaquant = payload.note_attaquant
    if payload.note_milieu is not None: player.note_milieu = payload.note_milieu
    if payload.note_defenseur is not None: player.note_defenseur = payload.note_defenseur
    if payload.note_gardien is not None: player.note_gardien = payload.note_gardien
    db.commit()
    return {
        "status": "ok", "player": player.name,
        "notes": {
            "attaquant": player.note_attaquant, "milieu": player.note_milieu,
            "defenseur": player.note_defenseur, "gardien": player.note_gardien,
        },
    }


@app.post("/admin/record-match", dependencies=[Depends(require_admin)])
def admin_record_match(payload: schemas.AdminRecordMatchRequest, db: Session = Depends(get_db)):
    try:
        match_date = datetime.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date doit être au format AAAA-MM-JJ")

    def find_player(name: str) -> Player:
        p = db.query(Player).filter_by(name=name).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Joueur introuvable : {name}")
        return p

    motm_player = find_player(payload.homme_du_match) if payload.homme_du_match else None

    # Le stade : même nom (sans tenir compte des majuscules ni des espaces en trop) = même stade.
    # Un nouveau stade reçoit sa carte commune ; un stade déjà connu ne crée rien.
    stade_player, stade_created = None, False
    stade_name = " ".join((payload.stade or "").split())
    if stade_name:
        wanted = stade_name.lower()
        stade_player = next((p for p in db.query(Player).filter(Player.poste == "STADE").all()
                             if " ".join(p.name.split()).lower() == wanted), None)
        if stade_player is None:
            if db.query(Player).filter_by(name=stade_name).first():
                raise HTTPException(status_code=400, detail="Ce nom est déjà celui d'un joueur ou d'une carte : choisis un autre nom de stade")
            stade_player = Player(name=stade_name, poste="STADE")
            db.add(stade_player)
            db.flush()
            db.add(Card(player_id=stade_player.id, tier=Tier.commune, vitesse=0, tir=0))
            stade_created = True

    match = Match(
        date=match_date, opponent=payload.opponent,
        score_us=payload.score_us, score_them=payload.score_them,
        motm_player_id=motm_player.id if motm_player else None,
        stade=stade_player.name if stade_player else None, stade_created=stade_created,
    )
    db.add(match)
    db.flush()
    if stade_player:
        stade_player.matches_joues += 1       # nombre de matchs joués dans ce stade
    match.lineup_json = json.dumps(payload.lineup, ensure_ascii=False)
    match.yellow_json = json.dumps(payload.cartons_jaunes, ensure_ascii=False)
    match.red_json = json.dumps(payload.cartons_rouges, ensure_ascii=False)

    for name in payload.lineup:
        find_player(name).matches_joues += 1

    # Moments mémorables : chacun donne naissance à une carte GOLD (une 'fiche' de poste MOMENT, avec sa carte).
    moment_cards = []
    for entry in payload.moments:
        actor = find_player(entry.player_name)
        if game_logic.card_kind(actor) != "joueur":
            raise HTTPException(status_code=400, detail=entry.player_name + " n'est pas un joueur de l'effectif")
        action = " ".join(entry.action.split())
        if not action:
            raise HTTPException(status_code=400, detail="Un moment mémorable doit avoir une action (ex. « Petit pont »)")
        name = action + " — " + actor.name
        if db.query(Player).filter_by(name=name).first():                    # même action, même joueur : on distingue par la date
            name = name + " (" + match_date.strftime("%d/%m") + ")"
        while db.query(Player).filter_by(name=name).first():
            name += "+"
        moment_player = Player(name=name, poste="MOMENT", photo_url=actor.photo_url)
        db.add(moment_player)
        db.flush()
        db.add(Card(player_id=moment_player.id, tier=Tier.gold, vitesse=0, tir=0))
        db.add(MatchMoment(match_id=match.id, moment_player_id=moment_player.id, real_player_name=actor.name, action=action))
        moment_cards.append(name)

    epics_created = []
    scorers_notes = {}
    for entry in payload.buteurs:
        p = find_player(entry.player_name)
        p.buts += entry.count
        db.add(MatchGoal(match_id=match.id, player_id=p.id, count=entry.count))
        # un buteur débloque sa carte épique (créée une seule fois, ensuite tirable dans les packs)
        has_epic = db.query(Card).filter_by(player_id=p.id, tier=Tier.epique).first()
        if not has_epic:
            db.add(Card(player_id=p.id, tier=Tier.epique, vitesse=0, tir=0))
            epics_created.append(p.name)
        scorers_notes[p.name] = game_logic.EPIC_BASE_NOTE + game_logic.EPIC_NOTE_PER_EXTRA_GOAL * max(0, p.buts - 1)

    for entry in payload.passeurs:
        p = find_player(entry.player_name)
        p.passes_decisives += entry.count
        db.add(MatchAssist(match_id=match.id, player_id=p.id, count=entry.count))

    for name in payload.cartons_jaunes:
        find_player(name).cartons_jaunes += 1

    for name in payload.cartons_rouges:
        find_player(name).cartons_rouges += 1

    if motm_player:
        motm_player.homme_du_match_count += 1

    match.epics_json = json.dumps(epics_created, ensure_ascii=False)

    # ce match n'est plus "à venir" : on retire l'annonce correspondante (même jour, même adversaire)
    removed_upcoming = 0
    for upcoming in db.query(UpcomingMatch).all():
        if upcoming.date.date() == match_date.date() and upcoming.opponent.strip().lower() == payload.opponent.strip().lower():
            db.delete(upcoming)
            removed_upcoming += 1

    db.commit()
    return {"status": "ok", "match_id": match.id, "epic_cards_created": epics_created,
            "epic_notes": scorers_notes,  # note actuelle de la carte épique de chaque buteur
            "upcoming_removed": removed_upcoming,
            "stade": stade_player.name if stade_player else None, "stade_card_created": stade_created,
            "gold_cards_created": moment_cards}


def _find_by_day_and_opponent(rows, date_str, opponent):
    day = None
    if date_str:
        try:
            day = datetime.fromisoformat(date_str).date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date doit être au format AAAA-MM-JJ")
    found = [r for r in rows
             if (day is None or r.date.date() == day)
             and (not opponent or r.opponent.strip().lower() == opponent.strip().lower())]
    return found


@app.post("/admin/delete-match", dependencies=[Depends(require_admin)])
def admin_delete_match(payload: schemas.AdminDeleteMatchRequest, db: Session = Depends(get_db)):
    """Annule un match réel enregistré : retire le match et remet les stats des joueurs comme avant
    (buts, passes, homme du match, matchs joués, cartons). La carte épique d'un buteur de ce match
    est supprimée si le joueur n'a plus aucun but."""
    if payload.match_id:
        match = db.get(Match, payload.match_id)
        found = [match] if match else []
    elif payload.date or payload.opponent:
        found = _find_by_day_and_opponent(db.query(Match).all(), payload.date, payload.opponent)
    else:
        raise HTTPException(status_code=400, detail="Indique match_id, ou la date et l'adversaire")
    if not found:
        raise HTTPException(status_code=404, detail="Match introuvable")
    if len(found) > 1:
        raise HTTPException(status_code=400, detail="Plusieurs matchs correspondent : précise la date et l'adversaire, ou utilise match_id")
    match = found[0]
    label = match.opponent + " (" + match.date.date().isoformat() + ")"

    reverted = {"buts": {}, "passes_decisives": {}, "matches_joues": [], "cartons_jaunes": [], "cartons_rouges": []}
    for goal in match.goals:
        goal.player.buts = max(0, goal.player.buts - goal.count)
        reverted["buts"][goal.player.name] = goal.count
    for assist in match.assists:
        assist.player.passes_decisives = max(0, assist.player.passes_decisives - assist.count)
        reverted["passes_decisives"][assist.player.name] = assist.count
    if match.motm_player:
        match.motm_player.homme_du_match_count = max(0, match.motm_player.homme_du_match_count - 1)
        reverted["homme_du_match"] = match.motm_player.name

    warnings = []
    if match.lineup_json is None:
        warnings.append("Ce match avait été enregistré avant la mise à jour : les « matchs joués » et les cartons "
                        "n'ont pas pu être remis à zéro (buts, passes et homme du match l'ont été).")
    else:
        for field, attr, key in (("lineup_json", "matches_joues", "matches_joues"),
                                 ("yellow_json", "cartons_jaunes", "cartons_jaunes"),
                                 ("red_json", "cartons_rouges", "cartons_rouges")):
            for name in json.loads(getattr(match, field) or "[]"):
                player = db.query(Player).filter_by(name=name).first()
                if player:
                    setattr(player, attr, max(0, getattr(player, attr) - 1))
                    reverted[key].append(name)

    # Règle du jeu : seul un joueur qui a marqué cette saison possède une carte épique. Les buteurs de ce
    # match qui retombent à zéro but perdent donc la leur (quel que soit le match qui l'avait créée).
    candidates = [goal.player.name for goal in match.goals]
    candidates += [n for n in json.loads(match.epics_json or "[]") if n not in candidates]
    epic_deleted = []
    for name in candidates:
        player = db.query(Player).filter_by(name=name).first()
        epic = db.query(Card).filter_by(player_id=player.id, tier=Tier.epique).first() if player else None
        if epic and player.buts == 0:
            purge_card_rows(db, [epic.id])
            db.flush()
            db.delete(epic)
            epic_deleted.append(name)

    # Le stade : un match de moins joué ici. Si CE match avait créé la carte du stade et qu'aucun autre
    # match n'y a eu lieu, la carte du stade disparaît aussi.
    stade_deleted = None
    if match.stade:
        stade_player = db.query(Player).filter_by(name=match.stade, poste="STADE").first()
        if stade_player:
            others = (db.query(Match).filter(Match.id != match.id, Match.stade == match.stade)
                      .order_by(Match.date, Match.created_at).all())
            if match.stade_created and not others:
                purge_card_rows(db, [c.id for c in stade_player.cards])
                db.flush()
                db.delete(stade_player)
                stade_deleted = match.stade
            else:
                stade_player.matches_joues = max(0, stade_player.matches_joues - 1)
                if match.stade_created and others:
                    others[0].stade_created = True     # un autre match garde la « paternité » de la carte du stade

    # Les cartes gold (moments mémorables) créées par ce match disparaissent avec lui.
    gold_deleted = []
    for mm in list(match.moments):
        moment_player = mm.moment_player
        db.delete(mm)
        db.flush()
        if moment_player is not None:
            purge_card_rows(db, [c.id for c in moment_player.cards])
            db.flush()
            gold_deleted.append(moment_player.name)
            db.delete(moment_player)

    db.delete(match)     # supprime aussi ses lignes de buteurs et de passeurs
    db.commit()
    return {"status": "ok", "deleted_match": label, "reverted": reverted,
            "epic_cards_deleted": epic_deleted, "stade_card_deleted": stade_deleted,
            "gold_cards_deleted": gold_deleted, "warnings": warnings}


@app.post("/admin/add-upcoming-match", dependencies=[Depends(require_admin)])
def admin_add_upcoming_match(payload: schemas.AdminAddUpcomingMatchRequest, db: Session = Depends(get_db)):
    try:
        date = datetime.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date doit être au format AAAA-MM-JJ (ou AAAA-MM-JJ HH:MM)")
    upcoming = UpcomingMatch(date=date, opponent=payload.opponent, location=payload.location)
    db.add(upcoming)
    db.commit()
    return {"status": "ok", "id": upcoming.id}


@app.post("/admin/delete-upcoming-match", dependencies=[Depends(require_admin)])
def admin_delete_upcoming_match(payload: schemas.AdminDeleteUpcomingMatchRequest, db: Session = Depends(get_db)):
    if payload.upcoming_id:
        row = db.get(UpcomingMatch, payload.upcoming_id)
        found = [row] if row else []
    elif payload.date or payload.opponent:
        found = _find_by_day_and_opponent(db.query(UpcomingMatch).all(), payload.date, payload.opponent)
    else:
        raise HTTPException(status_code=400, detail="Indique upcoming_id, ou la date et l'adversaire")
    if not found:
        raise HTTPException(status_code=404, detail="Match à venir introuvable")
    if len(found) > 1:
        raise HTTPException(status_code=400, detail="Plusieurs matchs correspondent : précise la date et l'adversaire")
    label = found[0].opponent + " (" + found[0].date.date().isoformat() + ")"
    db.delete(found[0])
    db.commit()
    return {"status": "ok", "deleted": label}


@app.post("/admin/set-test-account", dependencies=[Depends(require_admin)])
def admin_set_test_account(payload: schemas.AdminSetTestAccountRequest, db: Session = Depends(get_db)):
    """Marque (ou démarque) un compte comme compte de test :
    packs illimités, exclu du classement. N'affecte en rien les autres comptes."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.is_test = payload.is_test
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "is_test": user.is_test}


@app.post("/admin/create-card", dependencies=[Depends(require_admin)])
def admin_create_card(payload: schemas.AdminCreateCardRequest, db: Session = Depends(get_db)):
    """Crée la carte d'une rareté donnée pour un joueur (si elle n'existe pas déjà),
    et peut en offrir directement un exemplaire à un compte."""
    try:
        tier = Tier(payload.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail="tier doit être commune, rare, gold, secrete, speciale, epique ou legendaire")
    player = db.query(Player).filter_by(name=payload.player_name).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")
    card = db.query(Card).filter_by(player_id=player.id, tier=tier).first()
    created = False
    if not card:
        card = Card(player_id=player.id, tier=tier, vitesse=0, tir=0,
                    note=game_logic.SPECIAL_BASE_NOTE if tier == Tier.speciale else None)
        db.add(card)
        db.flush()
        created = True
    granted_to = None
    if payload.grant_to_pseudo:
        user = db.query(User).filter_by(pseudo=payload.grant_to_pseudo).first()
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable pour grant_to_pseudo")
        game_logic.get_or_create_owned(db, user, card).quantity += 1
        granted_to = user.pseudo
    db.commit()
    return {"status": "ok", "created": created, "card_id": card.id, "granted_to": granted_to}


@app.post("/admin/create-mascot", dependencies=[Depends(require_admin)])
def admin_create_mascot(payload: schemas.AdminCreateMascotRequest, db: Session = Depends(get_db)):
    """Crée la mascotte du club : une carte « Mascotte » dans les 4 raretés de packs (commune, rare, épique,
    légendaire), plus sa carte secrète. Elle a son propre emplacement « Loup » en 1v1 (+5 / +10 / +12 / +13 / +15 %),
    distinct de l'emplacement Fan. Peut être relancée sans risque : elle ne crée que ce qui manque, et passe
    une ancienne mascotte « FAN/Mascotte » au nouveau format."""
    player = db.query(Player).filter_by(name=payload.name).first()
    created_player = False
    if player is None:
        player = Player(name=payload.name, poste="MASCOTTE")
        db.add(player)
        db.flush()
        created_player = True
    elif game_logic.card_kind(player) != "mascotte":
        raise HTTPException(status_code=400, detail="Ce nom est déjà celui d'un joueur de l'effectif : choisis un autre nom pour la mascotte")
    else:
        player.poste = "MASCOTTE"        # ancien format « FAN/Mascotte » -> nouveau

    created, cards = [], []
    for tier in (Tier.commune, Tier.rare, Tier.epique, Tier.legendaire):
        card = db.query(Card).filter_by(player_id=player.id, tier=tier).first()
        if card is None:
            card = Card(player_id=player.id, tier=tier, vitesse=0, tir=0)
            db.add(card)
            db.flush()
            created.append(tier.value)
        cards.append(card)

    granted_to = None
    if payload.grant_to_pseudo:
        user = db.query(User).filter_by(pseudo=payload.grant_to_pseudo).first()
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable pour grant_to_pseudo")
        for card in cards:
            game_logic.get_or_create_owned(db, user, card).quantity += 1
        granted_to = user.pseudo

    db.commit()
    game_logic.ensure_secret_cards(db)         # sa carte secrète (fusion) est créée aussi
    return {"status": "ok", "mascot": player.name, "player_created": created_player,
            "cards_created": created, "granted_to": granted_to}


@app.post("/admin/create-equipment", dependencies=[Depends(require_admin)])
def admin_create_equipment(payload: schemas.AdminCreateEquipmentRequest, db: Session = Depends(get_db)):
    """Crée les cartes Équipement (bonus d'équipe en 1v1 : +1 % commune, +2 % rare, +3 % épique, +5 % légendaire).
    Sans `items`, crée la liste officielle du club. Relançable sans risque : ne crée que ce qui manque.
    Avec `items` : [{name, tier}] pour en ajouter d'autres plus tard."""
    items = [(i.name.strip(), i.tier) for i in payload.items] if payload.items else list(game_logic.EQUIPMENT_CATALOG)
    for name, tier in items:
        if not name:
            raise HTTPException(status_code=400, detail="Un équipement n'a pas de nom")
        try:
            Tier(tier)
        except ValueError:
            raise HTTPException(status_code=400, detail="Rareté inconnue pour « %s » : %s (commune, rare, gold, secrete, speciale, epique, legendaire)" % (name, tier))
    user = None
    if payload.grant_to_pseudo:
        user = db.query(User).filter_by(pseudo=payload.grant_to_pseudo).first()
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable pour grant_to_pseudo")

    created, cards = [], []
    for name, tier in items:
        player = db.query(Player).filter_by(name=name).first()
        if player is None:
            player = Player(name=name, poste="EQUIPEMENT")
            db.add(player)
            db.flush()
        elif not game_logic.is_equipment(player):
            raise HTTPException(status_code=400, detail="« %s » est déjà le nom d'un joueur ou d'une autre carte : choisis un autre nom" % name)
        card = db.query(Card).filter_by(player_id=player.id, tier=Tier(tier)).first()
        if card is None:
            card = Card(player_id=player.id, tier=Tier(tier), vitesse=0, tir=0)
            db.add(card)
            db.flush()
            created.append("%s (%s)" % (name, tier))
        cards.append(card)
    if user:
        for card in cards:
            game_logic.get_or_create_owned(db, user, card).quantity += 1
    db.commit()
    return {"status": "ok", "cards_created": created, "already_existing": len(cards) - len(created),
            "granted_to": user.pseudo if user else None}


@app.post("/admin/run-weekly-specials", dependencies=[Depends(require_admin)])
def admin_run_weekly_specials(payload: schemas.AdminRunWeeklyRequest, db: Session = Depends(get_db)):
    """Lance À LA MAIN la tâche du vendredi 17h sur les N derniers jours de matchs 1v1 (essai ou rattrapage).
    Avec dry_run=true : montre qui gagnerait, sans rien créer. Ne décale pas le vrai créneau du vendredi."""
    now = datetime.utcnow()
    return weekly.run_weekly_specials(db, now - timedelta(days=payload.days), now, dry_run=payload.dry_run)


@app.post("/admin/delete-card", dependencies=[Depends(require_admin)])
def admin_delete_card(payload: schemas.AdminDeleteCardRequest, db: Session = Depends(get_db)):
    """Supprime UNE carte précise (un tier d'un joueur), sans toucher au reste
    de son effectif. Utile par ex. pour retirer les versions rares des Fan."""
    try:
        tier = Tier(payload.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail="tier doit être commune, rare, gold, secrete, speciale, epique ou legendaire")
    card = (
        db.query(Card).join(Player)
        .filter(Player.name == payload.player_name, Card.tier == tier)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="Carte introuvable pour ce joueur/tier")
    purge_card_rows(db, [card.id])
    db.flush()
    db.delete(card)
    db.commit()
    return {"status": "ok", "deleted": payload.player_name + " (" + payload.tier + ")"}


@app.post("/admin/update-card-stats", dependencies=[Depends(require_admin)])
def admin_update_card_stats(payload: schemas.AdminUpdateCardStatsRequest, db: Session = Depends(get_db)):
    try:
        tier = Tier(payload.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail="tier doit être commune, rare, gold, secrete, speciale, epique ou legendaire")
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
    ils atterrissent dans ses jetons (illimités), utilisables à tout moment.
    pack_type : classique (défaut), rare, epique ou legendaire.
    Idéal pour offrir des packs aux supporters présents un jour de match.
    """
    spec = game_logic.PACK_TYPES.get(payload.pack_type)
    if not spec:
        raise HTTPException(status_code=400, detail="pack_type doit être classique, rare, epique, legendaire ou match")
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    field = spec["token_field"]
    setattr(user.pack_state, field, getattr(user.pack_state, field) + payload.count)
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "pack_type": payload.pack_type, "pack_tokens": pack_tokens_out(user)}

# ------------------------------------------------- Démarrage + tâches planifiées ----

def _weekly_tick():
    db = SessionLocal()
    try:
        weekly.check_and_run(db)
    finally:
        db.close()


async def _weekly_loop():
    """Toutes les minutes : exécute les cartes spéciales du vendredi 17h si leur créneau est passé."""
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, _weekly_tick)
        except Exception as exc:            # une erreur ici ne doit jamais faire tomber le site
            print("Tâche hebdomadaire : erreur ignorée :", exc)
        await asyncio.sleep(60)


@app.on_event("startup")
async def _startup():
    db = SessionLocal()
    try:
        created = game_logic.ensure_secret_cards(db)      # chaque joueur / fan / mascotte a sa carte secrète
        if created:
            print("Cartes secrètes créées :", created)
    except Exception as exc:
        print("Cartes secrètes : erreur ignorée au démarrage :", exc)
    finally:
        db.close()
    asyncio.create_task(_weekly_loop())
