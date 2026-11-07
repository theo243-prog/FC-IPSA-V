"""
Cartes NUMÉROTÉES à tirage limité (« Titre — Sujet · n° 12/22 »).

- Une SÉRIE a un nombre FIXE d'exemplaires (total), décidé à sa création et jamais augmenté.
- Chaque exemplaire est une carte à part entière, comme un moment gold : une fiche (Player) de poste NUMEROTEE nommée
  « Titre — Sujet · n° 12/22 », avec UNE carte de rareté « numerotee ». On en possède au plus un exemplaire (quantité 1).
  Le marché, les enchères, les offres d'achat, la collection et l'image de partage la gèrent donc sans changement.
- Rareté « numerotee » : absente des poids des packs (elle ne sort jamais d'un pack, d'un pack ultra ni d'un pack d'édition du
  Pass), pas de note ; type « numerotee » : refusée en match (duel_engine.validate_team), pas de niveau, ni stats hebdomadaires,
  ni fusion des secrètes, ni échange. Elle n'apparaît dans la collection que chez son propriétaire, et ne compte pas dans le
  pourcentage de collection.
- La table numbered_copies fait foi : un exemplaire est « reserve » (dans la réserve du club, sans propriétaire) ou « attribue ».
  On attribue le premier numéro libre (1, 2, 3…) ou un numéro précis ; un numéro n'est attribué qu'une fois (sauf
  series-reclaim, pour corriger une erreur).
- Un compte supprimé : ses exemplaires (y compris ceux qu'il avait mis en vente ou aux enchères, annulées proprement) passent au
  compte de réserve RESERVE_PSEUDO.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import Card, Listing, OwnedCard, Player, Tier, User
from .common import require_admin

router = APIRouter()
RESERVE_PSEUDO = "testadmin"          # compte de réserve : reçoit les exemplaires d'un compte supprimé (réglable)
POSTE = "NUMEROTEE"
MAX_TOTAL = 1000                      # garde-fou : une série a au plus 1000 exemplaires


class NumberedSeries(Base):
    __tablename__ = "numbered_series"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    total = Column(Integer, nullable=False)                 # fixé à la création, jamais augmenté
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    description = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)


class NumberedCopy(Base):
    __tablename__ = "numbered_copies"
    __table_args__ = (UniqueConstraint("series_id", "number", name="uq_numbered_copy"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(Integer, nullable=False, index=True)
    number = Column(Integer, nullable=False)
    card_id = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default="reserve")     # « reserve » (réserve du club) ou « attribue »
    attributed_at = Column(DateTime, nullable=True)


def full_name(s: NumberedSeries) -> str:
    return "%s — %s" % (s.title, s.subject)


def copy_name(title: str, subject: str, number: int, total: int) -> str:
    return "%s — %s · n° %d/%d" % (title, subject, number, total)


# ----------------------------------------------------------------------------- création ----

def create_series(db: Session, title: str, subject: str, total: int, description: str = None, photo_url: str = None) -> NumberedSeries:
    """Crée la série et TOUS ses exemplaires, dans la réserve (sans commit). Peu de requêtes : on peut en créer beaucoup d'un coup."""
    title, subject = " ".join((title or "").split()), " ".join((subject or "").split())
    if not title or not subject:
        raise HTTPException(status_code=400, detail="Une série a un titre et un sujet")
    if not (1 <= int(total) <= MAX_TOTAL):
        raise HTTPException(status_code=400, detail="Le total doit être entre 1 et %d exemplaires" % MAX_TOTAL)
    if db.query(NumberedSeries).filter_by(title=title, subject=subject).first():
        raise HTTPException(status_code=400, detail="La série « %s — %s » existe déjà" % (title, subject))
    names = [copy_name(title, subject, n, total) for n in range(1, total + 1)]
    if db.query(Player.id).filter(Player.name.in_(names)).first():
        raise HTTPException(status_code=400, detail="Un nom d'exemplaire de « %s — %s » est déjà pris" % (title, subject))
    if not photo_url:                                       # pas d'image : celle du sujet s'il est une personne du club
        who = db.query(Player).filter_by(name=subject).first()
        photo_url = who.photo_url if who else None
    s = NumberedSeries(title=title, subject=subject, total=total, description=(description or "").strip() or None, photo_url=photo_url or None)
    db.add(s)
    players = [Player(name=nm, poste=POSTE, photo_url=s.photo_url) for nm in names]
    db.add_all(players)
    db.flush()
    cards = [Card(player_id=p.id, tier=Tier.numerotee, vitesse=0, tir=0) for p in players]
    db.add_all(cards)
    db.flush()
    db.add_all([NumberedCopy(series_id=s.id, number=n, card_id=c.id, status="reserve") for n, c in enumerate(cards, start=1)])
    db.flush()
    return s


def find_series(db: Session, ref) -> NumberedSeries:
    """Une série par son identifiant (« 3 ») ou par son nom complet (« Titre — Sujet »)."""
    text = " ".join(str(ref or "").split())
    s = db.get(NumberedSeries, int(text)) if text.isdigit() else None
    if s is None and text:
        s = next((x for x in db.query(NumberedSeries).all() if full_name(x).casefold() == text.casefold()), None)
    if s is None:
        raise HTTPException(status_code=404, detail="Série introuvable : « %s » (identifiant ou « Titre — Sujet »)" % text)
    return s


# ------------------------------------------------------------------------- attribution ----

def mint(db: Session, s: NumberedSeries, user: User, number: int = None) -> NumberedCopy:
    """Donne un exemplaire de la réserve : le premier numéro libre, ou le numéro demandé (sans commit)."""
    q = db.query(NumberedCopy).filter_by(series_id=s.id)
    if number is not None:
        if not (1 <= number <= s.total):
            raise HTTPException(status_code=400, detail="Le n° %d n'existe pas : la série « %s » a %d exemplaires" % (number, full_name(s), s.total))
        copy = q.filter_by(number=number).with_for_update().first()
        if copy is None or copy.status != "reserve":
            raise HTTPException(status_code=400, detail="Le n° %d/%d est déjà attribué" % (number, s.total))
    else:
        copy = q.filter_by(status="reserve").order_by(NumberedCopy.number).with_for_update().first()
        if copy is None:
            raise HTTPException(status_code=400, detail="Série épuisée : les %d exemplaires de « %s » sont attribués" % (s.total, full_name(s)))
    copy.status, copy.attributed_at = "attribue", datetime.utcnow()
    owned = db.query(OwnedCard).filter_by(user_id=user.id, card_id=copy.card_id).first()
    if owned is None:
        db.add(OwnedCard(user_id=user.id, card_id=copy.card_id, quantity=1))
    else:
        owned.quantity = 1
    return copy


def _holders(db: Session, copies) -> dict:
    """{card_id: (pseudo, où)} : dans la collection d'un joueur, en vente au marché ou aux enchères."""
    from .auctions import Auction
    ids = [c.card_id for c in copies]
    out = {}
    for cid, pseudo in db.query(OwnedCard.card_id, User.pseudo).join(User, User.id == OwnedCard.user_id).filter(OwnedCard.card_id.in_(ids), OwnedCard.quantity > 0).all():
        out[cid] = (pseudo, "collection")
    for cid, pseudo in db.query(Listing.card_id, User.pseudo).join(User, User.id == Listing.seller_id).filter(Listing.card_id.in_(ids)).all():
        out[cid] = (pseudo, "marché")
    for cid, sid in db.query(Auction.card_id, Auction.seller_id).filter(Auction.card_id.in_(ids)).all():
        u = db.get(User, sid)
        out[cid] = (u.pseudo if u else "?", "enchères")
    return out


def series_out(db: Session, s: NumberedSeries) -> dict:
    copies = db.query(NumberedCopy).filter_by(series_id=s.id).order_by(NumberedCopy.number).all()
    who = _holders(db, copies)
    rows = []
    for c in copies:
        pseudo, where = who.get(c.card_id, (None, None))
        rows.append({"number": c.number, "card_id": c.card_id, "status": c.status, "holder": pseudo if c.status == "attribue" else None,
                     "where": where if c.status == "attribue" else "réserve du club"})
    attributed = sum(1 for c in copies if c.status == "attribue")
    return {"id": s.id, "title": s.title, "subject": s.subject, "name": full_name(s), "total": s.total, "attributed": attributed,
            "reserve": s.total - attributed, "description": s.description, "photo_url": s.photo_url,
            "created_at": s.created_at.isoformat() if s.created_at else None, "copies": rows}


def info_for_card(db: Session, card_id: str) -> Optional[dict]:
    """La série et le numéro d'un exemplaire (None si ce n'est pas une carte numérotée)."""
    c = db.query(NumberedCopy).filter_by(card_id=card_id).first()
    if c is None:
        return None
    s = db.get(NumberedSeries, c.series_id)
    return {"series_id": s.id, "number": c.number, "total": s.total, "title": s.title, "subject": s.subject}


def on_user_deleted(db: Session, user: User) -> None:
    """Avant la suppression d'un compte : ses ventes et enchères d'exemplaires numérotés sont annulées (le meilleur enchérisseur est
    remboursé), puis TOUS ses exemplaires passent au compte de réserve. Refuse (400) si le compte de réserve manque ou si c'est lui."""
    from .auctions import Auction
    numbered_ids = {cid for (cid,) in db.query(NumberedCopy.card_id).all()}
    if not numbered_ids:
        return
    owned = [o for o in db.query(OwnedCard).filter_by(user_id=user.id).all() if o.card_id in numbered_ids and o.quantity > 0]
    listed = [l for l in db.query(Listing).filter_by(seller_id=user.id).all() if l.card_id in numbered_ids]
    auctioned = [a for a in db.query(Auction).filter_by(seller_id=user.id).all() if a.card_id in numbered_ids]
    if not (owned or listed or auctioned):
        return
    if user.pseudo == RESERVE_PSEUDO:
        raise HTTPException(status_code=400, detail="« %s » est le compte de réserve des cartes numérotées : il ne peut pas être supprimé tant qu'il en détient" % RESERVE_PSEUDO)
    reserve = db.query(User).filter_by(pseudo=RESERVE_PSEUDO).first()
    if reserve is None:
        raise HTTPException(status_code=400, detail="Suppression refusée : ce compte a des cartes numérotées et le compte de réserve « %s » n'existe pas. Crée-le d'abord (ou change RESERVE_PSEUDO dans app/numbered.py)." % RESERVE_PSEUDO)
    moving = {o.card_id for o in owned}
    for l in listed:                                       # vente annulée : la carte revient… puis part à la réserve
        moving.add(l.card_id); db.delete(l)
    for a in auctioned:                                    # enchère annulée : le meilleur enchérisseur est remboursé
        if a.top_bidder_id:
            bidder = db.get(User, a.top_bidder_id)
            if bidder:
                bidder.credits += a.current_bid or 0
        moving.add(a.card_id); db.delete(a)
    for o in owned:
        db.delete(o)
    db.flush()
    for cid in moving:
        o = db.query(OwnedCard).filter_by(user_id=reserve.id, card_id=cid).first()
        if o is None:
            db.add(OwnedCard(user_id=reserve.id, card_id=cid, quantity=1))
        else:
            o.quantity = 1
    db.flush()


# -------------------------------------------------------------------------------- routes ----

@router.get("/series/{series_id}")
def public_series(series_id: int, db: Session = Depends(get_db)):
    """Une série : titre, sujet, « 18 / 22 attribués » et les détenteurs (pseudo et numéro ; « réserve du club » sinon)."""
    s = db.get(NumberedSeries, series_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Série introuvable")
    return series_out(db, s)


@router.get("/cards/{card_id}/series")
def card_series(card_id: str, db: Session = Depends(get_db)):
    i = info_for_card(db, card_id)
    if i is None:
        raise HTTPException(status_code=404, detail="Cette carte n'est pas numérotée")
    return {**i, "series": series_out(db, db.get(NumberedSeries, i["series_id"]))}


class SeriesCreate(BaseModel):
    title: str
    subject: str
    total: int = Field(ge=1, le=MAX_TOTAL)
    description: Optional[str] = None
    photo_url: Optional[str] = None


@router.post("/admin/series-create", dependencies=[Depends(require_admin)])
def admin_series_create(payload: SeriesCreate, db: Session = Depends(get_db)):
    from .main import _photo_path
    s = create_series(db, payload.title, payload.subject, payload.total, payload.description, _photo_path(payload.photo_url) if payload.photo_url else None)
    db.commit()
    return {"status": "ok", "series": series_out(db, s)}


class SeriesMint(BaseModel):
    series: str
    pseudo: str
    number: Optional[int] = None


@router.post("/admin/series-mint", dependencies=[Depends(require_admin)])
def admin_series_mint(payload: SeriesMint, db: Session = Depends(get_db)):
    s = find_series(db, payload.series)
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable : %s" % payload.pseudo)
    copy = mint(db, s, user, payload.number)
    db.commit()
    return {"status": "ok", "series": full_name(s), "number": copy.number, "total": s.total, "pseudo": user.pseudo, "card_id": copy.card_id}


class SeriesAwardFirst(BaseModel):
    series: str
    count: int = Field(ge=1, le=MAX_TOTAL)
    exclude: List[str] = []
    dry_run: bool = True


@router.post("/admin/series-award-first", dependencies=[Depends(require_admin)])
def admin_series_award_first(payload: SeriesAwardFirst, db: Session = Depends(get_db)):
    """Les numéros 1 à count aux `count` premiers comptes créés (par date de création), sans les pseudos exclus. Simulation par défaut."""
    s = find_series(db, payload.series)
    if payload.count > s.total:
        raise HTTPException(status_code=400, detail="La série « %s » n'a que %d exemplaires" % (full_name(s), s.total))
    taken = [c.number for c in db.query(NumberedCopy).filter(NumberedCopy.series_id == s.id, NumberedCopy.number <= payload.count, NumberedCopy.status != "reserve").order_by(NumberedCopy.number).all()]
    if taken:
        raise HTTPException(status_code=400, detail="Refusé : les n° %s sont déjà attribués" % ", ".join(str(n) for n in taken))
    excluded = {p.strip() for p in payload.exclude if p.strip()}
    users = [u for u in db.query(User).order_by(User.created_at, User.pseudo).all() if u.pseudo not in excluded][:payload.count]
    if len(users) < payload.count:
        raise HTTPException(status_code=400, detail="Il n'y a que %d comptes (après exclusions) pour %d numéros" % (len(users), payload.count))
    plan = [{"number": i, "pseudo": u.pseudo, "created_at": u.created_at.isoformat() if u.created_at else None} for i, u in enumerate(users, start=1)]
    if payload.dry_run:
        return {"status": "dry_run", "series": full_name(s), "plan": plan}
    for i, u in enumerate(users, start=1):
        mint(db, s, u, i)
    db.commit()
    return {"status": "ok", "series": full_name(s), "awarded": plan}


@router.get("/admin/series", dependencies=[Depends(require_admin)])
def admin_series(db: Session = Depends(get_db)):
    return [series_out(db, s) for s in db.query(NumberedSeries).order_by(NumberedSeries.id).all()]


class SeriesReclaim(BaseModel):
    series: str
    number: int


@router.post("/admin/series-reclaim", dependencies=[Depends(require_admin)])
def admin_series_reclaim(payload: SeriesReclaim, db: Session = Depends(get_db)):
    """Remet un exemplaire dans la réserve du club (pour corriger une erreur). Refusé s'il est en vente ou aux enchères."""
    from .auctions import Auction
    s = find_series(db, payload.series)
    copy = db.query(NumberedCopy).filter_by(series_id=s.id, number=payload.number).first()
    if copy is None:
        raise HTTPException(status_code=404, detail="Le n° %d n'existe pas dans « %s »" % (payload.number, full_name(s)))
    if copy.status == "reserve":
        raise HTTPException(status_code=400, detail="Le n° %d/%d est déjà dans la réserve" % (copy.number, s.total))
    if db.query(Listing).filter_by(card_id=copy.card_id).first() or db.query(Auction).filter_by(card_id=copy.card_id).first():
        raise HTTPException(status_code=400, detail="Le n° %d/%d est en vente ou aux enchères : annule d'abord la vente" % (copy.number, s.total))
    owners = [o for o in db.query(OwnedCard).filter_by(card_id=copy.card_id).all() if o.quantity > 0]
    who = [db.get(User, o.user_id).pseudo for o in owners]
    for o in owners:
        db.delete(o)
    copy.status, copy.attributed_at = "reserve", None
    db.commit()
    return {"status": "ok", "series": full_name(s), "number": copy.number, "taken_from": who}
