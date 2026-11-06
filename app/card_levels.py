"""
Niveaux de cartes : un joueur fait monter UNE copie d'une de ses cartes de 5 niveaux au plus ; chaque niveau ajoute +1 à la note en match.

- CARTES CONCERNÉES : les vrais joueurs (card_kind == « joueur ») en commune, rare ou édition limitée (Halloween, Noël, ed1 à ed12).
  Pas les gold, secrètes, épiques, légendaires, spéciales (leur note dépend déjà des résultats) ni les trophées, fans, mascottes,
  équipements, stades et moments.
- POUR ACHETER LE NIVEAU n : il faut AU MOMENT DE L'ACHAT au moins DUPES_REQUIRED[groupe][n-1] doublons de la carte (exemplaires au-delà
  du premier ; une copie mise en vente n'est plus dans la collection, donc ne compte pas). Les doublons ne sont JAMAIS détruits.
  On paie COSTS[groupe][n-1] crédits. Au plus DAILY_UPGRADES améliorations par joueur et par jour (jour de Paris).
- EN MATCH : note de base + niveau, puis malus hors poste et bonus de capitaine (duel_engine.build_members).
- LE NIVEAU SUIT LA CARTE : un joueur a au plus une copie évoluée par carte (table card_levels). Quand cette copie est vendue (annonce,
  enchère, offre d'achat), son niveau voyage avec elle (tables listing_levels, auction_levels, trade_levels) et le vendeur repasse au
  niveau 0. L'acheteur garde son meilleur niveau (le niveau reçu est perdu s'il en a déjà un supérieur ou égal). Une annonce annulée
  ou une enchère sans preneur rend la carte ET son niveau. Échanges, « vendre mes doublons » et fusion des secrètes ne prennent que
  des doublons : la copie évoluée reste.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, OwnedCard, Player, Tier, User
from .common import require_admin
from .security import get_current_user
from . import game_logic

router = APIRouter()

# ------------------------------------------------------------------ constantes réglables ----
MAX_LEVEL = 5
DAILY_UPGRADES = 2                       # améliorations par joueur et par jour (jour de Paris)
DUPES_REQUIRED = {                       # doublons à posséder au moment d'acheter le niveau 1, 2, 3, 4, 5 (jamais détruits)
    "commune": [5, 10, 20, 50, 100],
    "rare": [1, 3, 5, 12, 25],
    "edition": [1, 3, 5, 8, 10],
}
COSTS = {                                # crédits du niveau 1, 2, 3, 4, 5
    "commune": [30, 60, 120, 200, 320],
    "rare": [45, 90, 180, 300, 480],
    "edition": [60, 120, 240, 400, 640],
}
GROUP_LABELS = {"commune": "commune", "rare": "rare", "edition": "édition limitée"}
DAILY_KEY = "card_levels"


class CardLevel(Base):
    """La copie évoluée d'une carte chez un joueur (une seule par carte et par joueur). Sans clés étrangères : nettoyée à la main."""
    __tablename__ = "card_levels"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_card_level"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    card_id = Column(String, nullable=False, index=True)
    level = Column(Integer, nullable=False, default=0)


class ListingLevel(Base):
    """Le niveau d'une carte mise en vente au marché (annonce)."""
    __tablename__ = "listing_levels"
    listing_id = Column(String, primary_key=True)
    level = Column(Integer, nullable=False)


class AuctionLevel(Base):
    """Le niveau d'une carte mise aux enchères."""
    __tablename__ = "auction_levels"
    auction_id = Column(String, primary_key=True)
    level = Column(Integer, nullable=False)


class TradeLevel(Base):
    """Le niveau d'une carte dans l'historique des ventes du marché."""
    __tablename__ = "trade_levels"
    trade_id = Column(String, primary_key=True)
    level = Column(Integer, nullable=False)


# ------------------------------------------------------------------------------- outils ----

def group_of(card: Card):
    """« commune », « rare » ou « edition » pour une carte qui peut évoluer, sinon None."""
    t = card.tier.value
    if t in ("commune", "rare"):
        return t
    if t in game_logic.EDITION_TIERS:
        return "edition"
    return None


def ineligible_reason(card: Card):
    """La raison pour laquelle cette carte ne peut pas évoluer (None si elle le peut)."""
    kind = game_logic.card_kind(card.player)
    if kind != "joueur":
        labels = {"fan": "un fan", "mascotte": "la mascotte", "equipement": "un équipement", "stade": "un stade", "moment": "un moment mémorable"}
        return "Seules les cartes de joueurs évoluent : celle-ci est %s." % labels.get(kind, "une carte spéciale")
    if group_of(card) is None:
        t = card.tier.value
        why = {"gold": "les cartes gold sont des souvenirs de match", "secrete": "une carte secrète a déjà sa note fixe",
               "epique": "la note d'une épique monte avec les buts du joueur", "legendaire": "la note d'une légendaire monte avec les votes de l'homme du match",
               "speciale": "la note d'une spéciale monte avec les stars du 1v1", "saison": "un trophée de saison est un souvenir"}
        return "Cette carte ne peut pas évoluer : %s. Seules les communes, les rares et les éditions limitées évoluent." % why.get(t, "sa rareté n'évolue pas")
    return None


def level_of(db: Session, user_id: str, card_id: str) -> int:
    row = db.query(CardLevel).filter_by(user_id=user_id, card_id=card_id).first()
    return row.level if row else 0


def levels_for(db: Session, user_id: str) -> dict:
    """{carte: niveau} des copies évoluées d'un joueur."""
    return {r.card_id: r.level for r in db.query(CardLevel).filter_by(user_id=user_id).all() if r.level > 0}


def set_level(db: Session, user_id: str, card_id: str, level: int) -> None:
    """Fixe le niveau de la copie évoluée (0 : plus de copie évoluée). Ne fait pas de commit."""
    row = db.query(CardLevel).filter_by(user_id=user_id, card_id=card_id).first()
    if level <= 0:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(CardLevel(user_id=user_id, card_id=card_id, level=level))
    else:
        row.level = level


def copy_leaving(db: Session, user_id: str, card_id: str, qty_before: int, evolved: bool) -> int:
    """Un exemplaire quitte la collection du vendeur (vente, enchère, offre acceptée). Renvoie le niveau qui part avec lui :
    la copie évoluée part si le vendeur l'a choisie, ou si c'était sa dernière copie ; ses autres copies repassent au niveau 0."""
    lvl = level_of(db, user_id, card_id)
    if lvl and (evolved or qty_before <= 1):
        set_level(db, user_id, card_id, 0)
        return lvl
    return 0


def copy_arriving(db: Session, user_id: str, card_id: str, level: int) -> bool:
    """Un exemplaire arrive avec son niveau : l'acheteur garde son meilleur niveau. Renvoie False si le niveau reçu est perdu."""
    if level <= 0:
        return True
    if level_of(db, user_id, card_id) >= level:
        return False
    set_level(db, user_id, card_id, level)
    return True


def _dupes(db: Session, user_id: str, card_id: str) -> int:
    o = db.query(OwnedCard).filter_by(user_id=user_id, card_id=card_id).first()
    return max(0, (o.quantity if o else 0) - 1)


def info(db: Session, user: User, card: Card) -> dict:
    """Tout ce que la fiche d'une carte affiche : niveau, prochain palier, coût, doublons, effet, et la raison si c'est impossible."""
    base = game_logic.card_note(card.player, card.tier.value, card)
    lvl = level_of(db, user.id, card.id)
    out = {"card_id": card.id, "level": lvl, "max_level": MAX_LEVEL, "base_note": base, "note": base + lvl, "eligible": False,
           "can": False, "reason": None, "daily_left": max(0, DAILY_UPGRADES - _today_count(db, user))}
    reason = ineligible_reason(card)
    if reason:
        out["reason"] = reason
        return out
    g = group_of(card); out.update(eligible=True, group=g, group_label=GROUP_LABELS[g], dupes=_dupes(db, user.id, card.id),
                                   steps=[{"level": i + 1, "dupes": DUPES_REQUIRED[g][i], "cost": COSTS[g][i]} for i in range(MAX_LEVEL)])
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card.id).first()
    if not owned or owned.quantity < 1:
        out["reason"] = "Tu ne possèdes pas cette carte."
        return out
    if lvl >= MAX_LEVEL:
        out["reason"] = "Cette carte est déjà au niveau maximal (%d)." % MAX_LEVEL
        return out
    need, cost = DUPES_REQUIRED[g][lvl], COSTS[g][lvl]
    out.update(next_level=lvl + 1, next_note=base + lvl + 1, cost=cost, dupes_needed=need)
    if out["dupes"] < need:
        out["reason"] = "Il te faut %d doublon%s de cette carte pour le niveau %d : tu en as %d." % (need, "s" if need > 1 else "", lvl + 1, out["dupes"])
    elif user.credits < cost:
        out["reason"] = "Il te faut %d crédits : tu en as %d." % (cost, user.credits)
    elif out["daily_left"] <= 0:
        out["reason"] = "Tu as déjà fait évoluer %d cartes aujourd'hui : reviens demain (minuit, heure de Paris)." % DAILY_UPGRADES
    else:
        out["can"] = True
    return out


def _today_count(db: Session, user: User) -> int:
    from . import missions
    return missions.daily_count(db, user, DAILY_KEY)


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(CardLevel).filter_by(user_id=user_id).delete()


def on_cards_deleted(db: Session, card_ids) -> None:
    """Des cartes disparaissent du jeu : leurs niveaux aussi (les annonces et enchères sont supprimées par ailleurs)."""
    if card_ids:
        db.query(CardLevel).filter(CardLevel.card_id.in_(list(card_ids))).delete(synchronize_session=False)


def cleanup_orphans(db: Session) -> None:
    """Retire les niveaux d'annonces ou d'enchères qui n'existent plus (sans commit)."""
    from .models import Listing
    from .auctions import Auction
    live = {i for (i,) in db.query(Listing.id).all()}
    for r in db.query(ListingLevel).all():
        if r.listing_id not in live:
            db.delete(r)
    live = {i for (i,) in db.query(Auction.id).all()}
    for r in db.query(AuctionLevel).all():
        if r.auction_id not in live:
            db.delete(r)


# ------------------------------------------------------------------------------- routes ----

@router.get("/cards/{card_id}/level")
def card_level_info(card_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Cette carte n'existe pas")
    return info(db, user, card)


@router.post("/cards/{card_id}/evolve")
def evolve(card_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fait monter d'un niveau la copie évoluée d'une carte : crédits payés, doublons seulement vérifiés (jamais détruits)."""
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Cette carte n'existe pas")
    db.query(User).filter_by(id=user.id).with_for_update().first()        # (deux clics en même temps : un seul passe)
    i = info(db, user, card)
    if not i["can"]:
        raise HTTPException(status_code=400, detail=i["reason"] or "Évolution impossible")
    from . import missions
    user.credits -= i["cost"]
    set_level(db, user.id, card.id, i["next_level"])
    missions.daily_add(db, user, DAILY_KEY)
    db.commit()
    return {"status": "ok", "level": i["next_level"], "note": i["next_note"], "cost": i["cost"], "credits": user.credits, **{"info": info(db, user, card)}}


class AdminSetLevel(BaseModel):
    pseudo: str
    player_name: str
    tier: str
    level: int = Field(ge=0, le=MAX_LEVEL)


@router.post("/admin/set-card-level", dependencies=[Depends(require_admin)])
def admin_set_card_level(payload: AdminSetLevel, db: Session = Depends(get_db)):
    """Fixe le niveau d'une carte d'un joueur, sans paiement ni condition de doublons (pour tester). Il doit posséder la carte."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    try:
        tier = Tier(payload.tier.strip().lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Rareté inconnue : %s" % payload.tier)
    card = db.query(Card).join(Player).filter(Player.name == payload.player_name.strip(), Card.tier == tier).first()
    if card is None:
        raise HTTPException(status_code=404, detail="Carte introuvable : %s (%s)" % (payload.player_name, payload.tier))
    reason = ineligible_reason(card)
    if reason and payload.level > 0:
        raise HTTPException(status_code=400, detail=reason)
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=card.id).first()
    if payload.level > 0 and (owned is None or owned.quantity < 1):
        raise HTTPException(status_code=400, detail="%s ne possède pas cette carte" % user.pseudo)
    set_level(db, user.id, card.id, payload.level)
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "card": card.player.name, "tier": card.tier.value, "level": payload.level}
