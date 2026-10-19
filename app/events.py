"""
Événements éphémères, pilotés depuis la page d'administration (onglet « Événements »).

Trois sortes :
- « shop_discount » : les packs de la boutique sont moins chers (par défaut -50 %) ;
- « pass_double »   : les points du Pass sont doublés (ne se cumule pas avec le doublement de la dernière semaine du mois : le plus fort s'applique) ;
- « free_pack »     : chaque joueur peut récupérer un pack gratuit par jour (à minuit, heure de Paris, il peut en reprendre un).
Un événement a un début et une fin (heure de Paris) ; il s'arrête tout seul. Un bandeau l'annonce en haut du site.
"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User, gen_id
from .common import optional_user, require_admin
from .security import get_current_user
from .prono import now_paris
from . import game_logic

router = APIRouter()
KINDS = {"shop_discount": ("🏷️", "Packs en promotion"), "pass_double": ("⭐", "Points du Pass ×2"), "free_pack": ("🎁", "Un pack gratuit par jour")}


def _now() -> datetime:
    return now_paris()


class SiteEvent(Base):
    __tablename__ = "site_events"
    id = Column(String, primary_key=True, default=gen_id)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    starts_at = Column(DateTime, nullable=False)           # heure de Paris
    ends_at = Column(DateTime, nullable=False)
    params = Column(Text, nullable=False, default="{}")
    cancelled = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class EventClaim(Base):
    __tablename__ = "event_claims"
    event_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    day = Column(String, primary_key=True)                 # « AAAA-MM-JJ »


def _params(e: SiteEvent) -> dict:
    try:
        return json.loads(e.params or "{}")
    except Exception:
        return {}


def active(db: Session, kind: str = None) -> list:
    now = _now(); q = db.query(SiteEvent).filter(SiteEvent.cancelled == 0, SiteEvent.starts_at <= now, SiteEvent.ends_at > now)
    if kind:
        q = q.filter(SiteEvent.kind == kind)
    return q.order_by(SiteEvent.ends_at).all()


def discount_percent(db: Session) -> int:
    try:
        return max([int(_params(e).get("percent", 50)) for e in active(db, "shop_discount")] or [0])
    except Exception:
        return 0


def shop_price(db: Session, base: int) -> int:
    p = discount_percent(db)
    return base if p <= 0 else max(1, int(base * (100 - p) / 100 + 0.5))


def pass_double(db: Session) -> bool:
    try:
        return bool(active(db, "pass_double"))
    except Exception:
        return False


def _out(e: SiteEvent, now: datetime, claimed: bool = False) -> dict:
    p = _params(e); icon, label = KINDS.get(e.kind, ("🎉", e.kind)); is_active = e.cancelled == 0 and e.starts_at <= now < e.ends_at
    return {"id": e.id, "kind": e.kind, "icon": icon, "title": e.title, "params": p, "active": is_active, "cancelled": bool(e.cancelled),
            "seconds_left": max(0, int((e.ends_at - now).total_seconds())), "starts_in": max(0, int((e.starts_at - now).total_seconds())),
            "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat(), "claimed_today": claimed}


@router.get("/events")
def list_events(viewer=Depends(optional_user), db: Session = Depends(get_db)):
    """Les événements en cours et ceux qui commencent dans les 7 jours (pour le bandeau du site)."""
    now = _now(); rows = db.query(SiteEvent).filter(SiteEvent.cancelled == 0, SiteEvent.ends_at > now, SiteEvent.starts_at <= now + timedelta(days=7)).order_by(SiteEvent.starts_at).all()
    today = now.date().isoformat(); out = []
    for e in rows:
        claimed = bool(viewer and db.get(EventClaim, (e.id, viewer.id, today)))
        out.append(_out(e, now, claimed))
    return {"events": out}


@router.post("/events/{event_id}/claim")
def claim_free_pack(event_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = _now(); e = db.get(SiteEvent, event_id)
    if e is None or e.cancelled or e.kind != "free_pack" or not (e.starts_at <= now < e.ends_at):
        raise HTTPException(status_code=404, detail="Cet événement n'est pas en cours")
    today = now.date().isoformat()
    if db.get(EventClaim, (e.id, user.id, today)):
        raise HTTPException(status_code=400, detail="Tu as déjà récupéré ton pack gratuit aujourd'hui : reviens demain !")
    p = _params(e); pack = p.get("pack", "classique"); n = int(p.get("per_day", 1)); spec = game_logic.PACK_TYPES.get(pack)
    if not spec or not spec.get("token_field"):
        raise HTTPException(status_code=400, detail="Pack de l'événement inconnu")
    field = spec["token_field"]; setattr(user.pack_state, field, getattr(user.pack_state, field) + n)
    db.add(EventClaim(event_id=e.id, user_id=user.id, day=today)); db.commit()
    return {"status": "ok", "pack": pack, "count": n, "label": spec["label"]}


class EventRequest(BaseModel):
    kind: str
    title: str = Field(default="", max_length=60)
    duration_hours: int = Field(default=48, ge=1, le=720)       # durée
    start_in_hours: int = Field(default=0, ge=0, le=720)        # 0 = tout de suite
    percent: int = Field(default=50, ge=1, le=90)               # shop_discount
    pack: str = "classique"                                     # free_pack
    per_day: int = Field(default=1, ge=1, le=5)                 # free_pack


class EventCancel(BaseModel):
    id: str


@router.post("/admin/event", dependencies=[Depends(require_admin)])
def admin_create(payload: EventRequest, db: Session = Depends(get_db)):
    if payload.kind not in KINDS:
        raise HTTPException(status_code=422, detail="Sorte inconnue : " + ", ".join(KINDS))
    spec = game_logic.PACK_TYPES.get(payload.pack)
    if payload.kind == "free_pack" and (not spec or spec.get("price") is None):
        raise HTTPException(status_code=422, detail="Pack inconnu (classique, rare, epique, legendaire, ultra)")
    params = {"shop_discount": {"percent": payload.percent}, "pass_double": {}, "free_pack": {"pack": payload.pack, "per_day": payload.per_day}}[payload.kind]
    title = payload.title.strip() or {"shop_discount": ("Packs à moitié prix" if payload.percent == 50 else "Packs -%d %%" % payload.percent), "pass_double": "Points du Pass ×2",
                                       "free_pack": "Un pack gratuit par jour"}[payload.kind]
    start = _now() + timedelta(hours=payload.start_in_hours); e = SiteEvent(kind=payload.kind, title=title, starts_at=start, ends_at=start + timedelta(hours=payload.duration_hours), params=json.dumps(params))
    db.add(e); db.commit()
    return {"status": "ok", **_out(e, _now())}


@router.get("/admin/events", dependencies=[Depends(require_admin)])
def admin_list(db: Session = Depends(get_db)):
    now = _now(); rows = db.query(SiteEvent).order_by(SiteEvent.starts_at.desc()).limit(40).all(); out = []
    for e in rows:
        p = _params(e); detail = ("-%d %%" % p.get("percent", 50)) if e.kind == "shop_discount" else ("%d pack %s par jour" % (p.get("per_day", 1), p.get("pack", "classique")) if e.kind == "free_pack" else "×2")
        out.append({"id": e.id, "état": "annulé" if e.cancelled else ("en cours" if e.starts_at <= now < e.ends_at else ("à venir" if e.starts_at > now else "terminé")), "sorte": e.kind, "titre": e.title, "détail": detail,
                    "début (Paris)": e.starts_at.strftime("%d/%m %H:%M"), "fin (Paris)": e.ends_at.strftime("%d/%m %H:%M")})
    return out


@router.post("/admin/event-cancel", dependencies=[Depends(require_admin)])
def admin_cancel(payload: EventCancel, db: Session = Depends(get_db)):
    e = db.get(SiteEvent, payload.id)
    if e is None:
        raise HTTPException(status_code=404, detail="Événement introuvable")
    e.cancelled = 1; db.commit()
    return {"status": "ok", "id": e.id}
