"""
Cosmétiques de la boutique : achat des paliers (le catalogue est dans shop_catalog.py).

- 5 pistes (titre, cadre, bannière, couleur du pseudo, badge), 5 paliers chacune, de 30 à 300 crédits (shop_catalog.PRICES).
- Les paliers d'une piste s'achètent dans l'ordre : le palier N demande d'avoir le palier N-1.
- Un objet acheté est gardé pour toujours ; il s'équipe comme les objets du Pass (battlepass.owned_ids les compte).
- Prix fixes : les promotions de la boutique (événements) ne s'appliquent qu'aux packs.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .common import require_admin
from .security import get_current_user
from . import shop_catalog as S

router = APIRouter()


class ShopCosmeticPurchase(Base):
    """Un palier acheté par un joueur (sans clé étrangère : nettoyage à la main à la suppression d'un compte)."""
    __tablename__ = "shop_cosmetic_purchases"
    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_shop_cosmetic"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    item_id = Column(String, nullable=False)
    price = Column(Integer, nullable=False)                 # prix payé (pour un éventuel remboursement)
    created_at = Column(DateTime, default=datetime.utcnow)


class BuyCosmeticRequest(BaseModel):
    item_id: str


class AdminRefundRequest(BaseModel):
    pseudo: str
    item_id: str


def owned_ids(db: Session, user_id: str) -> set:
    return {r.item_id for r in db.query(ShopCosmeticPurchase).filter_by(user_id=user_id).all() if r.item_id in S.SHOP_ITEMS}


def state(db: Session, user: User) -> dict:
    owned = owned_ids(db, user.id)
    tracks = []
    for kind in S.TRACK_ORDER:
        levels, prev = [], True
        for lv in range(1, len(S.PRICES) + 1):
            it = S.SHOP_ITEMS[S.shop_item_id(kind, lv)]; mine = it["id"] in owned
            levels.append({"level": lv, "price": it["price"], "item": {k: it[k] for k in ("id", "kind", "name", "emoji", "style")}, "owned": mine,
                           "next": prev and not mine})                                   # le prochain palier à acheter dans cette piste
            prev = mine
        tracks.append({"kind": kind, "label": S.TRACK_LABELS[kind], "levels": levels, "owned": sum(1 for l in levels if l["owned"])})
    return {"tracks": tracks, "credits": user.credits, "owned": len(owned), "total": len(S.SHOP_ITEMS),
            "total_price": sum(S.PRICES) * len(S.TRACK_ORDER)}


@router.get("/shop/cosmetics")
def get_shop_cosmetics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return state(db, user)


@router.post("/shop/cosmetics/buy")
def buy_cosmetic(payload: BuyCosmeticRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    it = S.SHOP_ITEMS.get(payload.item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="Cosmétique inconnu")
    owned = owned_ids(db, user.id)
    if it["id"] in owned:
        raise HTTPException(status_code=400, detail="Tu as déjà ce cosmétique")
    if it["level"] > 1 and S.shop_item_id(it["kind"], it["level"] - 1) not in owned:
        raise HTTPException(status_code=400, detail="Achète d'abord le palier %d de cette piste" % (it["level"] - 1))
    if user.credits < it["price"]:
        raise HTTPException(status_code=400, detail="Pas assez de crédits (il en faut %d)" % it["price"])
    user.credits -= it["price"]
    db.add(ShopCosmeticPurchase(user_id=user.id, item_id=it["id"], price=it["price"]))
    try:
        db.commit()
    except IntegrityError:                                    # double appui : le premier achat suffit, le second n'est pas débité
        db.rollback()
        raise HTTPException(status_code=400, detail="Tu as déjà ce cosmétique")
    return {"status": "ok", "credits_total": user.credits, "item": {k: it[k] for k in ("id", "kind", "name", "emoji", "style")}}


def _unequip(db: Session, user_id: str, item_id: str) -> None:
    """Retire un objet de ce que le joueur a équipé (titre, cadre, bannière, couleur du pseudo, badge)."""
    from .battlepass import PassLoadout
    from .cosmetics import UserCosmetics
    lo = db.query(PassLoadout).filter_by(user_id=user_id).first()
    if lo is not None:
        for slot in ("banner", "name_color", "badge", "share_bg"):
            if getattr(lo, slot) == item_id: setattr(lo, slot, None)
    uc = db.query(UserCosmetics).filter_by(user_id=user_id).first()
    if uc is not None:
        if uc.title == item_id: uc.title = None
        if uc.frame == item_id: uc.frame = None


# ------------------------------------------------------------------ administration
@router.get("/admin/shop-cosmetics", dependencies=[Depends(require_admin)])
def admin_shop_cosmetics(db: Session = Depends(get_db)):
    """Ventes des cosmétiques de la boutique : nombre d'acheteurs et crédits dépensés par palier (pour suivre l'économie)."""
    counts = dict(db.query(ShopCosmeticPurchase.item_id, func.count()).group_by(ShopCosmeticPurchase.item_id).all())
    spent = dict(db.query(ShopCosmeticPurchase.item_id, func.sum(ShopCosmeticPurchase.price)).group_by(ShopCosmeticPurchase.item_id).all())
    rows = [{"piste": S.TRACK_LABELS[it["kind"]], "palier": it["level"], "objet": it["name"], "prix": it["price"],
             "acheteurs": int(counts.get(i, 0)), "credits_depenses": int(spent.get(i) or 0)} for i, it in S.SHOP_ITEMS.items()]
    rows.append({"piste": "TOTAL", "palier": "", "objet": "", "prix": "", "acheteurs": sum(r["acheteurs"] for r in rows), "credits_depenses": sum(r["credits_depenses"] for r in rows)})
    return rows


@router.post("/admin/shop-cosmetics-refund", dependencies=[Depends(require_admin)])
def admin_shop_cosmetics_refund(payload: AdminRefundRequest, db: Session = Depends(get_db)):
    """Annule l'achat d'un palier (le plus haut possédé de sa piste, pour garder l'ordre) et rend au joueur les crédits payés.
    L'objet est retiré de ce qu'il a équipé."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    it = S.SHOP_ITEMS.get(payload.item_id)
    row = db.query(ShopCosmeticPurchase).filter_by(user_id=user.id, item_id=payload.item_id).first() if it else None
    if row is None:
        raise HTTPException(status_code=404, detail="Ce joueur n'a pas acheté ce cosmétique (identifiant attendu : shop-<piste>-<palier>, ex. shop-title-5)")
    if it["level"] < len(S.PRICES) and S.shop_item_id(it["kind"], it["level"] + 1) in owned_ids(db, user.id):
        raise HTTPException(status_code=400, detail="Rembourse d'abord le palier %d de cette piste (les paliers se suivent)" % (it["level"] + 1))
    user.credits += row.price
    db.delete(row)
    _unequip(db, user.id, it["id"])
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "refunded": it["name"], "credits_rendus": row.price, "credits": user.credits}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(ShopCosmeticPurchase).filter_by(user_id=user_id).delete()
