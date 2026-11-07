"""
ENCHÈRES QUOTIDIENNES DU CLUB : cartes uniques « Édition Noire » (« Édition Noire — Léo · n° 12/22 »).

- Chaque joueur et chaque fan (ni mascotte, ni équipement, ni moment gold) a sa série de SERIES_TOTAL = 22 exemplaires, créée avec le
  mécanisme des séries limitées (numbered.py) : une carte par exemplaire, dans la réserve du club tant qu'elle n'a pas de propriétaire.
  Le n° 1 n'est JAMAIS mis aux enchères (il reste pour les récompenses de l'administration, commande series-mint).
- Chaque jour à 17h00 (heure de Paris, même calcul d'heure d'été que weekly.py), la tâche de fond crée un LOT de CLUB_AUCTIONS_PER_DAY
  enchères (réglable) : 5 personnes différentes parmi celles qui ont le moins d'exemplaires ÉMIS (attribués + en cours d'enchère),
  égalité au hasard ; pour chacune, un numéro au hasard parmi les restants (ni le n° 1, ni un numéro attribué ou aux enchères).
  Fin le LENDEMAIN à 16h00. Prolongation habituelle (+2 min), plafonnée à +60 min après 16h00 : jamais de chevauchement avec 17h00.
- Même moteur que les enchères entre joueurs (auctions.py : hausse de 5 %, crédits mis de côté), vendeur réservé CLUB_SELLER sans
  compte, table `auctions` inchangée : la table club_auction_lots relie l'enchère à la série et au numéro. À la fin, le plus offrant
  reçoit l'exemplaire et ses crédits sont DÉTRUITS (personne ne les reçoit). Sans enchère, l'exemplaire reste dans la réserve.
- Un lot par jour au plus (club_auction_batches.day est unique) : ni doublon après un redémarrage, ni lot raté (rattrapage au premier
  passage après 17h00, la fin restant 16h00 le lendemain).
- ACTIVATION DIFFÉRÉE : rien n'est créé avant la date de démarrage (réglage en base, modifiable depuis l'administration ; par défaut
  START_AT_DEFAULT). Avant cette date, la section est masquée aux joueurs (sauf les comptes PREVIEW_PSEUDOS) ; un teaser est possible.
  « Lancer un lot tout de suite » (administration) marche même avant la date, pour tester.
"""
import json
import os
import random
from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import AppSetting, Card, Player, User
from .common import optional_user, require_admin
from . import chat, game_logic, numbered, push, weekly

router = APIRouter()

SERIES_TOTAL = 22                       # exemplaires par personne (réglable avant la création des séries)
SERIES_TITLE = "Édition Noire"
CLUB_AUCTIONS_PER_DAY = 5               # valeur par défaut (réglable depuis l'administration)
CLUB_START_PRICE = 20                   # valeur par défaut (réglable depuis l'administration)
CLUB_SELLER = "club"                    # vendeur réservé : le club n'est pas un compte
RESERVED_NUMBER = 1                     # le n° 1 n'est jamais mis aux enchères
LOT_HOUR = 17                           # création du lot (heure de Paris)
END_HOUR = 16                           # fin des enchères, le lendemain (heure de Paris)
MAX_EXTENSION = timedelta(minutes=60)   # prolongations au plus 60 min au-delà de 16h00 (donc fin au plus tard à 17h00)
START_AT_DEFAULT = datetime(2026, 11, 9, 17, 0)      # lundi 9 novembre 2026, 17h00 heure de Paris : premier lot
PREVIEW_PSEUDOS = {numbered.RESERVE_PSEUDO}          # voient la section (et peuvent enchérir) avant le démarrage
SETTING_KEY = "club_auctions"
PERSON_KINDS = ("joueur", "fan")
RNG = random.Random()                   # remplaçable dans les tests
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


class ClubAuctionBatch(Base):
    """Un lot d'enchères du club. `day` (jour de Paris, « AAAA-MM-JJ ») n'est rempli que pour le lot automatique : unique."""
    __tablename__ = "club_auction_batches"
    id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(String, nullable=True, unique=True)
    manual = Column(Boolean, nullable=False, default=False)
    public = Column(Boolean, nullable=False, default=True)          # False : lot de test lancé avant le démarrage (pas d'annonce)
    created_at = Column(DateTime, nullable=False)                   # heure de Paris
    ends_at = Column(DateTime, nullable=True)                       # fin prévue (heure de Paris, sans prolongation)
    count = Column(Integer, nullable=False, default=0)
    announced = Column(Boolean, nullable=False, default=False)      # résultats annoncés
    note = Column(String, nullable=True)


class ClubAuctionLot(Base):
    """Une enchère du club : l'enchère (table auctions), la série et le numéro. Gardée après la fin (historique, gagnants)."""
    __tablename__ = "club_auction_lots"
    auction_id = Column(String, primary_key=True)
    batch_id = Column(Integer, nullable=False, index=True)
    series_id = Column(Integer, nullable=False, index=True)
    number = Column(Integer, nullable=False)
    card_id = Column(String, nullable=False, index=True)
    base_end = Column(DateTime, nullable=False)                     # 16h00 (heure de Paris) : la prolongation s'arrête à +60 min
    status = Column(String, nullable=False, default="open")         # open, won, unsold, cancelled
    winner_id = Column(String, nullable=True)
    winner_pseudo = Column(String, nullable=True)
    price = Column(Integer, nullable=True)
    settled_at = Column(DateTime, nullable=True)


# ------------------------------------------------------------------------------- horloge ----

def paris_now() -> datetime:
    """Heure de Paris (sans fuseau), avec le calcul d'heure d'été de weekly.py. FC_FAKE_NOW (tests) la fige, comme pour les enchères."""
    from .prono import now_paris
    if os.getenv("FC_FAKE_NOW"):
        return now_paris()
    return weekly.to_paris(datetime.utcnow())


def _label(dt: datetime, year: bool = False) -> str:
    """« lundi 9 novembre à 17h00 »."""
    return "%s %d %s%s à %dh%02d" % (DAYS[dt.weekday()], dt.day, MONTHS[dt.month - 1], (" %d" % dt.year) if year else "", dt.hour, dt.minute)


# ------------------------------------------------------------------------------ réglages ----

def get_settings(db: Session) -> dict:
    row = db.get(AppSetting, SETTING_KEY)
    raw = {}
    if row is not None:
        try:
            raw = json.loads(row.value) or {}
        except ValueError:
            raw = {}
    s = {"start_at": START_AT_DEFAULT.strftime("%Y-%m-%dT%H:%M"), "paused": False, "per_day": CLUB_AUCTIONS_PER_DAY,
         "start_price": CLUB_START_PRICE, "teaser": True, "teaser_text": ""}
    s.update({k: v for k, v in raw.items() if k in s})
    return s


def _save_settings(db: Session, s: dict) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=json.dumps(s, ensure_ascii=False)))
    else:
        row.value = json.dumps(s, ensure_ascii=False)


def start_at(db: Session, s: dict = None) -> datetime:
    s = s or get_settings(db)
    try:
        return datetime.fromisoformat(s["start_at"])
    except (TypeError, ValueError):
        return START_AT_DEFAULT


def started(db: Session, now: datetime = None) -> bool:
    return (now or paris_now()) >= start_at(db)


def teaser_text(db: Session, s: dict = None) -> str:
    s = s or get_settings(db)
    if (s.get("teaser_text") or "").strip():
        return s["teaser_text"].strip()
    st = start_at(db, s)
    return "Enchères du club : premier lot le %s %d %s à %dh%s" % (DAYS[st.weekday()], st.day, MONTHS[st.month - 1], st.hour, ("%02d" % st.minute) if st.minute else "")


def can_preview(user) -> bool:
    return bool(user is not None and user.pseudo in PREVIEW_PSEUDOS)


def visible_for(db: Session, user, now: datetime = None) -> bool:
    return started(db, now) or can_preview(user)


# ------------------------------------------------------------------------------- séries ----

def is_black_series(s) -> bool:
    return s is not None and s.title == SERIES_TITLE


def people(db: Session):
    """Les personnes qui ont droit à une série : joueurs et fans (ni mascotte, ni équipement, ni moment gold…), par nom."""
    return sorted((p for p in db.query(Player).all() if game_logic.card_kind(p) in PERSON_KINDS), key=lambda p: p.name.casefold())


def black_series(db: Session):
    return db.query(numbered.NumberedSeries).filter_by(title=SERIES_TITLE).order_by(numbered.NumberedSeries.id).all()


def ensure_series(db: Session, player: Player) -> Optional[numbered.NumberedSeries]:
    """Crée la série Édition Noire d'une personne si elle n'existe pas encore (sans commit). None si elle existe déjà ou n'y a pas droit."""
    if game_logic.card_kind(player) not in PERSON_KINDS:
        return None
    if db.query(numbered.NumberedSeries).filter_by(title=SERIES_TITLE, subject=player.name).first():
        return None
    return numbered.create_series(db, SERIES_TITLE, player.name, SERIES_TOTAL, photo_url=player.photo_url)


# ------------------------------------------------------------------------------ état ----

def _open_lots(db: Session):
    return db.query(ClubAuctionLot).filter_by(status="open").all()


def series_state(db: Session) -> list:
    """Pour chaque série Édition Noire : exemplaires attribués, aux enchères, émis, et numéros encore disponibles pour les enchères."""
    from .auctions import Auction
    series = black_series(db)
    if not series:
        return []
    in_auction = {cid for (cid,) in db.query(Auction.card_id).all()}
    by_series = {}
    for c in db.query(numbered.NumberedCopy).filter(numbered.NumberedCopy.series_id.in_([s.id for s in series])).all():
        by_series.setdefault(c.series_id, []).append(c)
    out = []
    for s in series:
        copies = by_series.get(s.id, [])
        attributed = sum(1 for c in copies if c.status == "attribue")
        auctioned = sum(1 for c in copies if c.status == "reserve" and c.card_id in in_auction)
        free = sorted(c.number for c in copies if c.status == "reserve" and c.card_id not in in_auction and c.number != RESERVED_NUMBER)
        n1 = next((c for c in copies if c.number == RESERVED_NUMBER), None)
        out.append({"series": s, "id": s.id, "subject": s.subject, "total": s.total, "attributed": attributed, "in_auction": auctioned,
                    "emitted": attributed + auctioned, "available": free, "number_one": (n1.status if n1 else None),
                    "card_by_number": {c.number: c.card_id for c in copies}})
    return out


def pick(db: Session, count: int) -> list:
    """Les exemplaires du prochain lot : `count` personnes différentes parmi celles qui ont le moins d'exemplaires émis (égalité au
    hasard), un numéro au hasard parmi les restants pour chacune. Liste de (état de la série, numéro, card_id)."""
    rows = [r for r in series_state(db) if r["available"]]
    RNG.shuffle(rows)
    rows.sort(key=lambda r: r["emitted"])                  # tri stable : l'ordre au hasard départage les égalités
    out = []
    for r in rows[:max(0, count)]:
        n = RNG.choice(r["available"])
        out.append((r, n, r["card_by_number"][n]))
    return out


def _next_end(now: datetime) -> datetime:
    """Le lendemain à 16h00 (heure de Paris)."""
    return datetime.combine(now.date() + timedelta(days=1), time(END_HOUR, 0))


def _log(db: Session, text: str) -> None:
    """Une ligne dans le journal de l'administration (pour me signaler un lot vide…)."""
    try:
        from .admin_tools import AdminLog
        db.add(AdminLog(method="TÂCHE", path="/club-auctions", status=200, summary=text[:300], payload=None, ip="serveur"))
    except Exception:
        pass


def create_batch(db: Session, now: datetime, manual: bool = False, minutes: int = None) -> ClubAuctionBatch:
    """Crée un lot (sans commit). Le lot automatique porte le jour de Paris (unique) ; un lot vide est enregistré quand même et signalé.
    Lève IntegrityError si le lot du jour existe déjà (deux passages en même temps)."""
    from .auctions import Auction
    s = get_settings(db)
    public = started(db, now)
    picks = pick(db, int(s["per_day"]))
    if manual and minutes:
        ends = now + timedelta(minutes=int(minutes))
    elif manual:
        ends = datetime.combine(now.date(), time(END_HOUR, 0))       # lot manuel : le prochain 16h00 à au moins 1 h d'ici
        if ends - now < timedelta(hours=1):
            ends = _next_end(now)
    else:
        ends = _next_end(now)
    batch = ClubAuctionBatch(day=None if manual else now.date().isoformat(), manual=manual, public=public, created_at=now, ends_at=ends, count=len(picks))
    db.add(batch)
    db.flush()                                              # (le jour unique protège contre un deuxième lot le même jour)
    names = []
    for r, number, card_id in picks:
        a = Auction(seller_id=CLUB_SELLER, card_id=card_id, start_price=int(s["start_price"]), ends_at=ends)
        db.add(a)
        db.flush()
        db.add(ClubAuctionLot(auction_id=a.id, batch_id=batch.id, series_id=r["id"], number=number, card_id=card_id, base_end=ends, status="open"))
        names.append("%s n° %d/%d" % (r["subject"], number, r["total"]))
    if not picks:
        batch.note = "plus aucune carte à mettre aux enchères"
        _log(db, "Enchères du club : lot du %s VIDE, plus aucune carte Édition Noire à mettre aux enchères (toutes émises, ou séries pas encore créées)" % now.date().isoformat())
    elif public:
        until = "demain 16h" if ends.date() > now.date() else "%dh%02d" % (ends.hour, ends.minute)
        n = len(picks)
        chat.add_event(db, "🖤 Enchères du club : %d nouvelle%s carte%s unique%s Édition Noire aux enchères jusqu'à %s — %s" % (n, "s" if n > 1 else "", "s" if n > 1 else "", "s" if n > 1 else "", until, ", ".join(names)))
        push.safe(db, push.notify_all, "market", "🖤 Enchères du club", "%d nouvelle%s carte%s unique%s aux enchères jusqu'à %s" % (n, "s" if n > 1 else "", "s" if n > 1 else "", "s" if n > 1 else "", until), url="/#marche", tag="club-auctions")
    return batch


def due_today(db: Session, now: datetime) -> bool:
    """Le lot automatique du jour est-il à créer ? (démarré, pas en pause, 17h00 passé, pas encore de lot aujourd'hui)"""
    s = get_settings(db)
    if s.get("paused") or now < start_at(db, s) or now.time() < time(LOT_HOUR, 0):
        return False
    return db.query(ClubAuctionBatch).filter_by(day=now.date().isoformat()).first() is None


# ----------------------------------------------------------------------- fin d'enchère ----

def settle(db: Session, a) -> tuple:
    """Fin d'une enchère du club (appelée par auctions._settle). Le gagnant reçoit l'exemplaire avec son numéro ; ses crédits, déjà
    retirés au moment de l'enchère, sont détruits (le club n'est pas un compte). Sans enchère : l'exemplaire reste dans la réserve."""
    lot = db.get(ClubAuctionLot, a.id)
    winner = db.get(User, a.top_bidder_id) if a.top_bidder_id else None
    s = db.get(numbered.NumberedSeries, lot.series_id) if lot else None
    won = None
    if lot is not None and winner is not None and a.current_bid is not None and s is not None:
        try:
            numbered.mint(db, s, winner, lot.number, allow_auction=True)
            lot.status, lot.winner_id, lot.winner_pseudo, lot.price = "won", winner.id, winner.pseudo, a.current_bid
            won = winner.id
            try:
                push.enqueue(db, winner.id, "market", "Enchère du club remportée 🖤", "Tu remportes « %s » n° %d/%d (Édition Noire) pour %d crédits." % (s.subject, lot.number, s.total, a.current_bid), url="/#collection", tag="club-auctions")
            except Exception:
                pass
        except HTTPException:                                # (l'exemplaire n'est plus libre : on rembourse, rien n'est perdu)
            winner.credits += a.current_bid
            lot.status = "unsold"
    else:
        if lot is None and winner is not None and a.current_bid:
            winner.credits += a.current_bid                  # (enchère du club sans lien : on rembourse)
        if lot is not None:
            lot.status = "unsold"                            # l'exemplaire reste dans la réserve : son numéro redevient disponible
    if lot is not None:
        lot.settled_at = paris_now()
    db.delete(a)
    return won, CLUB_SELLER


def cap_end(db: Session, a) -> None:
    """Après une prolongation : jamais plus de 60 min au-delà de 16h00."""
    lot = db.get(ClubAuctionLot, a.id)
    if lot is not None and a.ends_at > lot.base_end + MAX_EXTENSION:
        a.ends_at = lot.base_end + MAX_EXTENSION


def check_can_bid(db: Session, user) -> None:
    if not visible_for(db, user):
        raise HTTPException(status_code=400, detail="Les enchères du club ne sont pas encore ouvertes")


def announce_results(db: Session) -> int:
    """Les lots dont toutes les enchères sont terminées : résultats dans le chat et notification générale (une seule fois)."""
    n = 0
    for b in db.query(ClubAuctionBatch).filter_by(announced=False).all():
        lots = db.query(ClubAuctionLot).filter_by(batch_id=b.id).all()
        if any(l.status == "open" for l in lots):
            continue
        b.announced = True
        if not b.public or not lots:
            continue
        subj = {s.id: s for s in db.query(numbered.NumberedSeries).filter(numbered.NumberedSeries.id.in_([l.series_id for l in lots])).all()}
        won = [l for l in lots if l.status == "won"]
        label = lambda l: "%s n° %d/%d" % (subj[l.series_id].subject if l.series_id in subj else "?", l.number, subj[l.series_id].total if l.series_id in subj else SERIES_TOTAL)
        parts = ["%s → %s (%d cr.)" % (label(l), l.winner_pseudo, l.price) for l in won]
        unsold = [label(l) for l in lots if l.status == "unsold"]
        text = "🖤 Résultats des enchères du club : " + ("; ".join(parts) if parts else "aucune carte vendue")
        if unsold:
            text += ". Sans preneur (de retour dans la réserve) : " + ", ".join(unsold)
        chat.add_event(db, text)
        if won:
            push.safe(db, push.notify_all, "market", "🖤 Résultats des enchères du club", "; ".join(parts)[:280], url="/#marche", tag="club-auctions")
        n += 1
    return n


def tick(db: Session, now: datetime = None) -> None:
    """Toutes les minutes : fin des enchères, résultats, puis le lot du jour (17h00, ou rattrapage au premier passage après)."""
    from . import auctions
    auctions.settle_due(db)
    if announce_results(db):
        db.commit()
    now = now or paris_now()
    if not due_today(db, now):
        db.rollback()
        return
    try:
        create_batch(db, now)
        db.commit()
    except IntegrityError:                                    # un autre passage vient de créer le lot du jour
        db.rollback()


# ---------------------------------------------------------------------- prévisions ----

def next_lot_at(db: Session, now: datetime = None) -> Optional[datetime]:
    """Le prochain lot automatique : 17h00 d'un jour, jamais avant la date de démarrage (None en pause). S'il est déjà dû
    (rattrapage), c'est maintenant : la tâche de fond le crée à son prochain passage."""
    now = now or paris_now()
    s = get_settings(db)
    if s.get("paused"):
        return None
    st = start_at(db, s)
    done_today = db.query(ClubAuctionBatch).filter_by(day=now.date().isoformat()).first() is not None
    d = max(now, st).date()
    for _ in range(3):
        t = max(datetime.combine(d, time(LOT_HOUR, 0)), st)
        if t.date() == d and not (d == now.date() and done_today):
            return max(t, now)
        d += timedelta(days=1)
    return None


def forecast(db: Session, state: list = None, now: datetime = None) -> dict:
    """Date du dernier lot au rythme actuel, si toutes les cartes trouvent preneur (simulation du choix « le moins d'émis »)."""
    state = state if state is not None else series_state(db)
    per_day = max(1, int(get_settings(db)["per_day"]))
    rows = [[r["emitted"], len(r["available"])] for r in state if r["available"]]
    remaining = sum(r[1] for r in rows)
    days = 0
    while any(r[1] for r in rows) and days < 100000:
        cand = sorted((r for r in rows if r[1]), key=lambda r: r[0])[:per_day]
        for r in cand:
            r[0] += 1; r[1] -= 1
        days += 1
    first = next_lot_at(db, now)
    last = (first.date() + timedelta(days=days - 1)) if (first and days) else None
    return {"remaining": remaining, "days": days, "per_day": per_day, "first_lot": first.isoformat() if first else None,
            "last_lot_day": last.isoformat() if last else None, "people": len(state),
            "note": "si toutes les cartes trouvent preneur (une carte sans enchère revient dans la réserve et allonge le programme)"}


def on_cards_deleted(db: Session, card_ids: list) -> None:
    """Des cartes disparaissent : leurs enchères du club en cours sont marquées annulées (auctions.cancel_for_cards rembourse)."""
    for lot in db.query(ClubAuctionLot).filter(ClubAuctionLot.card_id.in_(card_ids), ClubAuctionLot.status == "open").all():
        lot.status, lot.settled_at = "cancelled", paris_now()


def on_user_deleted(db: Session, user_id: str) -> None:
    """Compte supprimé : ses gains passés gardent seulement le pseudo (ses mises en tête sont gérées par auctions.on_user_deleted)."""
    db.query(ClubAuctionLot).filter(ClubAuctionLot.winner_id == user_id).update({"winner_id": None}, synchronize_session=False)


# ----------------------------------------------------------------------- présentation ----

def _lot_out(db: Session, lot: ClubAuctionLot, a, now: datetime, viewer=None) -> dict:
    from .auctions import min_next_bid
    from .common import card_out
    s = db.get(numbered.NumberedSeries, lot.series_id)
    card = db.get(Card, lot.card_id)
    out = {"auction_id": lot.auction_id, "series_id": lot.series_id, "subject": s.subject if s else "?", "number": lot.number,
           "total": s.total if s else SERIES_TOTAL, "card": card_out(card) if card else None, "status": lot.status}
    if a is not None:
        bidder = db.get(User, a.top_bidder_id) if a.top_bidder_id else None
        out.update({"start_price": a.start_price, "current_bid": a.current_bid, "bids": a.bids, "top_bidder": bidder.pseudo if bidder else None,
                    "min_next_bid": min_next_bid(a), "seconds_left": max(0, int((a.ends_at - now).total_seconds())), "ends_at": a.ends_at.isoformat(),
                    "base_end": lot.base_end.isoformat(), "i_am_top": bool(viewer and a.top_bidder_id == viewer.id)})
    else:
        out.update({"winner": lot.winner_pseudo, "price": lot.price})
    return out


@router.get("/club-auctions")
def public_club_auctions(viewer=Depends(optional_user), db: Session = Depends(get_db)):
    """Les enchères du club en cours (section « 🖤 Enchères du club »), le prochain lot et les derniers gagnants.
    Avant le démarrage : seulement le teaser (sauf pour les comptes autorisés à prévisualiser)."""
    from .auctions import Auction, settle_due
    settle_due(db)
    now = paris_now()
    s = get_settings(db)
    st = start_at(db, s)
    is_started = now >= st
    base = {"started": is_started, "start_at": st.isoformat(), "start_label": _label(st), "paused": bool(s.get("paused")),
            "total": SERIES_TOTAL, "reserved_number": RESERVED_NUMBER, "lot_hour": LOT_HOUR, "end_hour": END_HOUR}
    if not visible_for(db, viewer, now):
        return {**base, "visible": False, "teaser": teaser_text(db, s) if s.get("teaser") else None}
    lots = []
    for lot in sorted(_open_lots(db), key=lambda l: l.base_end):
        a = db.get(Auction, lot.auction_id)
        if a is not None:
            lots.append(_lot_out(db, lot, a, now, viewer))
    last = db.query(ClubAuctionBatch).filter(ClubAuctionBatch.count > 0).order_by(ClubAuctionBatch.id.desc()).limit(5).all()
    results = []
    for b in last:
        for lot in db.query(ClubAuctionLot).filter(ClubAuctionLot.batch_id == b.id, ClubAuctionLot.status == "won").all():
            results.append(_lot_out(db, lot, None, now, viewer))
    nxt = next_lot_at(db, now)
    return {**base, "visible": True, "preview": not is_started, "lots": lots, "results": results[:10],
            "next_lot_at": nxt.isoformat() if nxt else None, "next_lot_label": _label(nxt) if nxt else None}


# --------------------------------------------------------------------------- admin ----

class CreateAll(BaseModel):
    dry_run: bool = True


@router.post("/admin/series-create-all", dependencies=[Depends(require_admin)])
def admin_series_create_all(payload: CreateAll, db: Session = Depends(get_db)):
    """Crée la série Édition Noire (22 exemplaires, dans la réserve) de chaque joueur et fan qui n'en a pas encore. Aperçu par défaut."""
    have = {s.subject for s in black_series(db)}
    todo = [p for p in people(db) if p.name not in have]
    plan = [{"name": p.name, "type": game_logic.card_kind(p)} for p in todo]
    if payload.dry_run:
        return {"status": "dry_run", "total": SERIES_TOTAL, "to_create": plan, "already": sorted(have)}
    for p in todo:
        numbered.create_series(db, SERIES_TITLE, p.name, SERIES_TOTAL, photo_url=p.photo_url)
    db.commit()
    return {"status": "ok", "total": SERIES_TOTAL, "created": plan, "already": sorted(have)}


@router.get("/admin/club-auctions", dependencies=[Depends(require_admin)])
def admin_club_auctions(db: Session = Depends(get_db)):
    """Le programme : réglages, lot du jour, enchères en cours, séries (émis / restants par personne), date de fin prévue."""
    from .auctions import Auction, settle_due
    settle_due(db)
    now = paris_now()
    s = get_settings(db)
    st = start_at(db, s)
    state = series_state(db)
    today = db.query(ClubAuctionBatch).filter_by(day=now.date().isoformat()).first()
    lots = []
    for lot in sorted(_open_lots(db), key=lambda l: l.base_end):
        a = db.get(Auction, lot.auction_id)
        if a is not None:
            lots.append(_lot_out(db, lot, a, now))
    batches = [{"id": b.id, "day": b.day, "manual": b.manual, "public": b.public, "created_at": b.created_at.isoformat(), "ends_at": b.ends_at.isoformat() if b.ends_at else None,
                "count": b.count, "note": b.note} for b in db.query(ClubAuctionBatch).order_by(ClubAuctionBatch.id.desc()).limit(10).all()]
    nxt = next_lot_at(db, now)
    return {"now": now.isoformat(), "settings": s, "start_at": st.isoformat(), "start_label": _label(st, year=True), "started": now >= st,
            "teaser": teaser_text(db, s), "next_lot_at": nxt.isoformat() if nxt else None,
            "today": ({"id": today.id, "count": today.count, "created_at": today.created_at.isoformat(), "note": today.note} if today else None),
            "open": lots, "batches": batches, "forecast": forecast(db, state, now),
            "series": [{"id": r["id"], "subject": r["subject"], "total": r["total"], "attributed": r["attributed"], "in_auction": r["in_auction"],
                        "emitted": r["emitted"], "remaining_for_auctions": len(r["available"]), "number_one": r["number_one"]} for r in state],
            "people_without_series": [p.name for p in people(db) if p.name not in {r["subject"] for r in state}]}


class ClubSettings(BaseModel):
    start_at: Optional[str] = None          # « AAAA-MM-JJ HH:MM » (heure de Paris)
    paused: Optional[bool] = None
    per_day: Optional[int] = Field(default=None, ge=1, le=20)
    start_price: Optional[int] = Field(default=None, ge=1, le=100000)
    teaser: Optional[bool] = None
    teaser_text: Optional[str] = Field(default=None, max_length=200)


@router.post("/admin/club-auctions-settings", dependencies=[Depends(require_admin)])
def admin_club_settings(payload: ClubSettings, db: Session = Depends(get_db)):
    """Date de démarrage, pause / reprise, nombre d'enchères par jour, prix de départ, teaser. Seuls les champs remplis changent."""
    s = get_settings(db)
    if payload.start_at is not None and payload.start_at.strip():
        txt = payload.start_at.strip().replace(" ", "T")
        if len(txt) == 10:
            txt += "T%02d:00" % LOT_HOUR
        try:
            s["start_at"] = datetime.fromisoformat(txt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            raise HTTPException(status_code=400, detail="Date de démarrage illisible : écris « AAAA-MM-JJ HH:MM » (heure de Paris), ex. 2026-11-09 17:00")
    for k in ("paused", "per_day", "start_price", "teaser"):
        v = getattr(payload, k)
        if v is not None:
            s[k] = v
    if payload.teaser_text is not None:
        s["teaser_text"] = payload.teaser_text.strip()
    _save_settings(db, s)
    db.commit()
    st = start_at(db, s)
    return {"status": "ok", "settings": s, "start_label": _label(st, year=True), "teaser": teaser_text(db, s)}


class Launch(BaseModel):
    minutes: Optional[int] = Field(default=None, ge=5, le=1440)      # facultatif : durée (sinon fin au prochain 16h00)


@router.post("/admin/club-auctions-launch", dependencies=[Depends(require_admin)])
def admin_club_launch(payload: Launch, db: Session = Depends(get_db)):
    """Lance un lot tout de suite (en plus du lot automatique de 17h00), même avant la date de démarrage, pour tester."""
    from .auctions import settle_due
    settle_due(db)
    now = paris_now()
    if not any(r["available"] for r in series_state(db)):
        raise HTTPException(status_code=400, detail="Aucune carte à mettre aux enchères : crée d'abord les séries (series-create-all), ou elles sont toutes émises")
    b = create_batch(db, now, manual=True, minutes=payload.minutes)
    db.commit()
    st = start_at(db)
    note = None if b.public else ("Test avant le démarrage du programme (%s) : ce lot n'est visible que par %s, aucune annonce n'est faite et seul ce compte peut enchérir. "
                                  "Un exemplaire gagné lui est vraiment attribué : remets-le dans la réserve avec « series-reclaim » si besoin." % (_label(st, year=True), ", ".join(sorted(PREVIEW_PSEUDOS))))
    lots = db.query(ClubAuctionLot).filter_by(batch_id=b.id).all()
    subj = {x.id: x.subject for x in black_series(db)}
    return {"status": "ok", "batch_id": b.id, "count": b.count, "ends_at": b.ends_at.isoformat(), "public": b.public, "note": note,
            "lots": [{"auction_id": l.auction_id, "subject": subj.get(l.series_id, "?"), "number": l.number} for l in lots]}


class CancelLot(BaseModel):
    auction_id: str


@router.post("/admin/club-auctions-cancel", dependencies=[Depends(require_admin)])
def admin_club_cancel(payload: CancelLot, db: Session = Depends(get_db)):
    """Annule une enchère du club SANS enchère : l'exemplaire reste dans la réserve, son numéro redevient disponible."""
    from .auctions import Auction
    a = db.get(Auction, payload.auction_id)
    lot = db.get(ClubAuctionLot, payload.auction_id)
    if a is None or lot is None or a.seller_id != CLUB_SELLER:
        raise HTTPException(status_code=404, detail="Enchère du club introuvable (ou déjà terminée)")
    if a.bids:
        raise HTTPException(status_code=400, detail="Il y a déjà une enchère : elle ne peut plus être annulée")
    lot.status, lot.settled_at = "cancelled", paris_now()
    db.delete(a)
    db.commit()
    return {"status": "ok", "auction_id": payload.auction_id, "number": lot.number}
