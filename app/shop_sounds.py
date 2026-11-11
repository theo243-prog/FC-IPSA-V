"""
Son de la semaine au shop (11/11/2026) : chaque semaine (du lundi 0 h au dimanche, heure de Paris), le shop propose UN son d'ouverture de
packs à PRICE (100) crédits, tiré au hasard parmi les sons du catalogue ci-dessous. Jamais un son des Pass de saison (un son par thème,
frontend/sounds/<thème>.mp3) ni le hurlement du loup (le son par défaut).

- Le son de la semaine est tiré au premier accès de la semaine et enregistré (table shop_sound_weeks) : le même pour tout le monde.
  On tire parmi les sons proposés le MOINS de fois jusqu'ici (égalité au hasard, RNG), et jamais celui de la semaine d'avant : tous passent à tour de rôle.
- Un son acheté est gardé pour toujours (table shop_sound_purchases) ; il s'ajoute aux objets du Pass (pass_catalog.ITEMS, type « sound »,
  identifiant shop-son-<fichier>) et se choisit comme un son du Pass (profil, « 🎨 Titre et cadre », route POST /pass/sound).
- Prix fixe : les promotions du shop ne s'appliquent qu'aux packs. Pas de remboursement.
- Le code ne dépend pas de la présence des fichiers : si un fichier manque, le site joue le hurlement du loup.
- POUR AJOUTER UN SON : déposer frontend/sounds/<fichier>.mp3 puis ajouter une ligne à SOUNDS (fichier sans « .mp3 », nom affiché).
"""
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .common import require_admin
from .security import get_current_user
from . import game_logic, pass_catalog as P

router = APIRouter()
PRICE = 100
RNG = random.Random()                                    # (remplaçable dans les tests)
SOUNDS = [                                               # (fichier dans frontend/sounds/ sans « .mp3 », nom affiché)
    ("actrice", "Actrice"),
    ("clap", "Clap"),
    ("elephant", "Éléphant"),
    ("nine", "Pas content"),
    ("ph", "PH"),
    ("siuu", "Siuu"),
    ("tronc", "Taillage de haie"),
]
RESERVED = set(P.THEMES) | {"loup"}                     # sons des Pass de saison et son par défaut : jamais au shop


def sound_item_id(file: str) -> str:
    return "shop-son-%s" % file


ITEMS = {sound_item_id(f): {"id": sound_item_id(f), "kind": "sound", "name": "Son « %s »" % name, "emoji": "🔊",
                            "style": {"file": "sounds/%s.mp3" % f}, "theme": None, "shop_sound": True}
         for f, name in SOUNDS if f not in RESERVED}
P.ITEMS.update(ITEMS)                                    # se choisissent comme les sons du Pass


class ShopSoundWeek(Base):
    """Le son proposé une semaine donnée (lundi de la semaine, heure de Paris)."""
    __tablename__ = "shop_sound_weeks"
    week = Column(String, primary_key=True)              # AAAA-MM-JJ du lundi
    item_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ShopSoundPurchase(Base):
    """Un son acheté au shop (sans clé étrangère : nettoyé à la main à la suppression d'un compte)."""
    __tablename__ = "shop_sound_purchases"
    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_shop_sound"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    item_id = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BuyRequest(BaseModel):
    item_id: str


def week_of(day=None) -> str:
    d = day or game_logic.today_paris()
    return (d - timedelta(days=d.weekday())).isoformat()


def owned_ids(db: Session, user_id: str) -> set:
    return {r.item_id for r in db.query(ShopSoundPurchase).filter_by(user_id=user_id).all() if r.item_id in ITEMS}


def _draw(db: Session, week: str):
    if not ITEMS:
        return None
    shown = dict(db.query(ShopSoundWeek.item_id, func.count()).group_by(ShopSoundWeek.item_id).all())
    prev = db.get(ShopSoundWeek, (datetime.fromisoformat(week) - timedelta(days=7)).date().isoformat())
    pool = [i for i in ITEMS if not (prev and prev.item_id == i)] or list(ITEMS)
    least = min(shown.get(i, 0) for i in pool)
    return RNG.choice(sorted(i for i in pool if shown.get(i, 0) == least))


def sound_of_week(db: Session, week: str = None):
    """L'objet son de la semaine (tiré et enregistré au premier accès), ou None s'il n'y a aucun son au catalogue."""
    week = week or week_of()
    row = db.get(ShopSoundWeek, week)
    if row is None or row.item_id not in ITEMS:
        item = _draw(db, week)
        if item is None:
            return None
        try:
            if row is None:
                db.add(ShopSoundWeek(week=week, item_id=item))
            else:
                row.item_id = item                       # (son retiré du catalogue entre-temps)
            db.commit()
        except IntegrityError:                           # deux premiers accès en même temps : on garde le premier
            db.rollback()
        row = db.get(ShopSoundWeek, week)
    return ITEMS.get(row.item_id) if row else None


def state(db: Session, user: User) -> dict:
    it = sound_of_week(db); week = week_of()
    ends = (datetime.fromisoformat(week) + timedelta(days=7)).date().isoformat()
    owned = owned_ids(db, user.id)
    return {"week": week, "ends": ends, "price": PRICE, "credits": user.credits, "owned_count": len(owned), "total": len(ITEMS),
            "sound": ({k: it[k] for k in ("id", "kind", "name", "emoji", "style")} | {"owned": it["id"] in owned}) if it else None}


@router.get("/shop/sound")
def get_shop_sound(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Le son de la semaine au shop (le même pour tout le monde, changé chaque lundi à minuit, heure de Paris)."""
    return state(db, user)


@router.post("/shop/sound/buy")
def buy_shop_sound(payload: BuyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Achète le son de la semaine (100 crédits) : il se choisit ensuite comme un son du Pass."""
    it = sound_of_week(db)
    if it is None or payload.item_id != it["id"]:
        raise HTTPException(status_code=400, detail="Ce son n'est plus en vente : le shop propose un nouveau son chaque lundi")
    db.query(User).filter_by(id=user.id).with_for_update().first()        # (deux clics en même temps : un seul passe)
    db.refresh(user)
    if it["id"] in owned_ids(db, user.id):
        raise HTTPException(status_code=400, detail="Tu as déjà ce son")
    if user.credits < PRICE:
        raise HTTPException(status_code=400, detail="Pas assez de crédits (il en faut %d)" % PRICE)
    user.credits -= PRICE
    db.add(ShopSoundPurchase(user_id=user.id, item_id=it["id"], price=PRICE))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Tu as déjà ce son")
    return {"status": "ok", "credits_total": user.credits, **state(db, user)}


@router.get("/admin/shop-sounds", dependencies=[Depends(require_admin)])
def admin_shop_sounds(db: Session = Depends(get_db)):
    """Sons du shop : semaines où chacun a été proposé, acheteurs et crédits dépensés."""
    weeks = {}
    for r in db.query(ShopSoundWeek).order_by(ShopSoundWeek.week).all():
        weeks.setdefault(r.item_id, []).append(r.week)
    buyers = dict(db.query(ShopSoundPurchase.item_id, func.count()).group_by(ShopSoundPurchase.item_id).all())
    cur = sound_of_week(db)
    return {"week": week_of(), "current": cur["name"] if cur else None,
            "sounds": [{"son": it["name"], "fichier": it["style"]["file"], "semaines": weeks.get(i, []), "acheteurs": int(buyers.get(i, 0)),
                        "credits_depenses": int(buyers.get(i, 0)) * PRICE} for i, it in ITEMS.items()]}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(ShopSoundPurchase).filter_by(user_id=user_id).delete()
