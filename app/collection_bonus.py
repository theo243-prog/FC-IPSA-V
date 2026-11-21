"""
Bonus de collection SECRETS (branche prisme-couronne, 21/11/2026, en essai) : deux récompenses cachées, jamais annoncées à l'avance.

- « Prisme » (fonction en essai `prisme`) : posséder 5 cartes d'une même personne du club (joueur ou fan) — sa commune, sa rare, sa
  secrète (BASE_TIERS), AU MOINS UNE de ses cartes d'édition limitée (halloween, noel, ed1–ed12 : n'importe laquelle) et AU MOINS UN
  exemplaire de sa série Édition Noire — débloque sa carte « Prisme — Nom ». Décidé par Théo (21/11/2026) : ni spéciale, ni épique, ni
  légendaire (elles dépendent des matchs réels). Chaque joueur qui réunit les 5 reçoit la carte (une seule carte Prisme par personne, partagée).
- « Couronne noire » (fonction en essai `couronne_noire`) : posséder TOUS les exemplaires de la série Édition Noire d'une personne
  (n° 1/5 à 5/5) débloque « Couronne noire — Nom », carte UNIQUE au monde : seul le premier à réunir la série la reçoit.
- Les deux cartes : fiche de poste réservé PRISME / COURONNE (game_logic.card_kind « prisme » / « couronne »), rareté « saison » (comme
  les trophées : jamais dans un pack, ne se vend pas, ne s'échange pas, ne joue pas, ne compte pas dans le % de collection, invisible tant
  qu'on ne l'a pas). Acquises pour toujours, même si l'on revend ensuite une des cartes.
- Chacune donne un titre (« Fan absolu de Nom », « Seigneur noir de Nom », identifiant bonus-<sorte>-<id de la personne>).
- Vérification (`check`) à chaque /me, seulement pour les comptes qui ont accès à la fonction ; une récompense nouvelle part dans `/me`
  `bonus_unseen` : le site joue la révélation, puis POST /collection-bonus/seen. Annonce dans le chat seulement quand la fonction est sortie
  (ouverte à tous), pour garder le secret pendant l'essai.
- Admin (essais) : POST /admin/collection-bonus-grant {pseudo, kind, player_name} (donne la récompense sans les conditions),
  POST /admin/collection-bonus-replay {pseudo} (rejoue les révélations), GET /admin/collection-bonus (qui a quoi).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from .database import Base, get_db
from .common import require_admin
from .models import Card, OwnedCard, Player, Tier, User
from .security import get_current_user
from . import features, game_logic

router = APIRouter()
BASE_TIERS = ("commune", "rare", "secrete")      # + une édition limitée + un exemplaire Édition Noire (prisme_candidates)
KINDS = {
    "prisme": {"feature": "prisme", "poste": "PRISME", "prefix": "Prisme — ", "title": "Fan absolu de %s", "emoji": "🌈"},
    "couronne": {"feature": "couronne_noire", "poste": "COURONNE", "prefix": "Couronne noire — ", "title": "Seigneur noir de %s", "emoji": "👑"},
}
TITLE_PREFIX = "bonus-"


class BonusUnlock(Base):
    """Une récompense secrète débloquée par un joueur du site (kind : prisme / couronne ; subject_id : la personne du club)."""
    __tablename__ = "collection_bonus_unlocks"
    __table_args__ = (UniqueConstraint("user_id", "kind", "subject_id", name="uq_bonus_unlock"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)
    subject_id = Column(String, nullable=False, index=True)
    card_id = Column(String, nullable=False)
    unlocked_at = Column(DateTime, default=datetime.utcnow)
    seen = Column(Boolean, nullable=False, default=False)


class SeenRequest(BaseModel):
    ids: list[int] = []


class GrantRequest(BaseModel):
    pseudo: str
    kind: str
    player_name: str


class PseudoRequest(BaseModel):
    pseudo: str


# ------------------------------------------------------------------ les cartes
def bonus_card(db: Session, kind: str, subject: Player) -> Card:
    """La carte Prisme / Couronne d'une personne (créée la première fois ; sa photo suit celle de la personne)."""
    k = KINDS[kind]
    name = k["prefix"] + subject.name
    fiche = db.query(Player).filter_by(name=name, poste=k["poste"]).first()
    if fiche is None:
        fiche = Player(name=name, poste=k["poste"], photo_url=subject.photo_url)
        db.add(fiche); db.flush()
    elif subject.photo_url and fiche.photo_url != subject.photo_url:
        fiche.photo_url = subject.photo_url
    card = db.query(Card).filter_by(player_id=fiche.id, tier=Tier.saison).first()
    if card is None:
        card = Card(player_id=fiche.id, tier=Tier.saison, vitesse=0, tir=0)
        db.add(card); db.flush()
    return card


def subject_of(player: Player):
    """Pour une fiche Prisme / Couronne : (sorte, nom de la personne) ; sinon None."""
    for kind, k in KINDS.items():
        if (player.poste or "").upper() == k["poste"] and (player.name or "").startswith(k["prefix"]):
            return kind, player.name[len(k["prefix"]):]
    return None


def info(player: Player):
    """Ce que le site reçoit pour une carte bonus (card_out) : sorte, personne, emoji."""
    s = subject_of(player)
    return {"kind": s[0], "subject": s[1], "emoji": KINDS[s[0]]["emoji"]} if s else None


def _unlock(db: Session, user: User, kind: str, subject: Player) -> BonusUnlock:
    card = bonus_card(db, kind, subject)
    row = BonusUnlock(user_id=user.id, kind=kind, subject_id=subject.id, card_id=card.id, seen=False)
    db.add(row)
    owned = game_logic.get_or_create_owned(db, user, card); owned.quantity = max(owned.quantity, 1)
    db.flush()
    if features.get(db, KINDS[kind]["feature"])["public"] and not getattr(user, "is_test", False):     # annonce : seulement une fois la fonction sortie
        from . import chat
        chat.add_event(db, ("🌈 %s a débloqué le Prisme de %s !" if kind == "prisme" else "👑 %s a réuni l'Édition Noire complète de %s !") % (user.pseudo, subject.name), user)
    return row


# ------------------------------------------------------------------ les conditions
def prisme_candidates(db: Session, user: User) -> list:
    """Les personnes dont le joueur possède la commune, la rare, la secrète, une édition limitée et un exemplaire Édition Noire."""
    from . import numbered, club_auctions
    tiers = [Tier(t) for t in BASE_TIERS + tuple(game_logic.EDITION_TIERS)]
    owned = (db.query(Card.player_id, Card.tier).join(OwnedCard, OwnedCard.card_id == Card.id)
             .filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0, Card.tier.in_(tiers)).all())
    have = {}
    for pid, tier in owned:
        t = tier.value
        have.setdefault(pid, set()).add("edition" if t in game_logic.EDITION_TIERS else t)
    need = set(BASE_TIERS) | {"edition"}
    ready = [pid for pid, ts in have.items() if need <= ts]
    if not ready:
        return []
    noire = {s for (s,) in db.query(numbered.NumberedSeries.subject).join(numbered.NumberedCopy, numbered.NumberedCopy.series_id == numbered.NumberedSeries.id)
             .join(OwnedCard, OwnedCard.card_id == numbered.NumberedCopy.card_id)
             .filter(numbered.NumberedSeries.title == club_auctions.SERIES_TITLE, OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    out = []
    for pid in ready:
        p = db.get(Player, pid)
        if p is not None and p.name in noire and game_logic.card_kind(p) in ("joueur", "fan") and not getattr(p, "unique_card", False):
            out.append(p)
    return out


def couronne_candidates(db: Session, user: User) -> list:
    """Les personnes dont le joueur possède TOUS les exemplaires de la série Édition Noire."""
    from . import numbered, club_auctions
    out = []
    owned_ids = {cid for (cid,) in db.query(OwnedCard.card_id).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    for s in db.query(numbered.NumberedSeries).filter_by(title=club_auctions.SERIES_TITLE).all():
        copies = [c.card_id for c in db.query(numbered.NumberedCopy).filter_by(series_id=s.id).all()]
        if copies and len(copies) == s.total and all(cid in owned_ids for cid in copies):
            p = db.query(Player).filter_by(name=s.subject).first()
            if p is not None:
                out.append(p)
    return out


def check(db: Session, user: User) -> list:
    """Débloque les récompenses nouvelles (sans commit). Seulement pour les comptes qui ont accès à la fonction."""
    new = []
    done = {(r.kind, r.subject_id) for r in db.query(BonusUnlock).filter_by(user_id=user.id).all()}
    for kind, finder in (("prisme", prisme_candidates), ("couronne", couronne_candidates)):
        if not features.has_access(db, user, KINDS[kind]["feature"]):
            continue
        for subject in finder(db, user):
            if (kind, subject.id) in done:
                continue
            if kind == "couronne" and db.query(BonusUnlock).filter_by(kind="couronne", subject_id=subject.id).first() is not None:
                continue                                         # couronne : unique au monde, le premier l'a déjà
            new.append(_unlock(db, user, kind, subject))
    return new


def unseen_out(db: Session, user: User) -> list:
    from .common import card_out
    out = []
    for r in db.query(BonusUnlock).filter_by(user_id=user.id, seen=False).order_by(BonusUnlock.unlocked_at).all():
        card = db.get(Card, r.card_id)
        subject = db.get(Player, r.subject_id)
        if card is not None and subject is not None:
            out.append({"id": r.id, "kind": r.kind, "subject": subject.name, "title": KINDS[r.kind]["title"] % subject.name, "card": card_out(card)})
    return out


def safe_unseen(db: Session, user: User) -> list:
    """Vérification + récompenses pas encore révélées (pour /me). Ne fait jamais échouer l'appelant."""
    try:
        if check(db, user):
            db.commit()
        return unseen_out(db, user)
    except Exception:
        db.rollback()
        return []


# ------------------------------------------------------------------ titres
def titles(db: Session, user_id: str) -> list:
    rows = db.query(BonusUnlock).filter_by(user_id=user_id).all()
    out = []
    for r in rows:
        p = db.get(Player, r.subject_id)
        if p is not None:
            out.append((TITLE_PREFIX + r.kind + "-" + r.subject_id, KINDS[r.kind]["title"] % p.name))
    return out


def title_label(title_id, db: Session = None):
    from .database import SessionLocal
    rest = str(title_id)[len(TITLE_PREFIX):]
    kind, _, pid = rest.partition("-")
    if kind not in KINDS:
        return None
    own = db is None
    db = db or SessionLocal()
    try:
        p = db.get(Player, pid)
        return KINDS[kind]["title"] % p.name if p is not None else None
    finally:
        if own:
            db.close()


def all_title_labels(db: Session) -> dict:
    out = {}
    for r in db.query(BonusUnlock).all():
        p = db.get(Player, r.subject_id)
        if p is not None:
            out[TITLE_PREFIX + r.kind + "-" + r.subject_id] = KINDS[r.kind]["title"] % p.name
    return out


# ------------------------------------------------------------------ routes
@router.post("/collection-bonus/seen")
def mark_seen(payload: SeenRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(BonusUnlock).filter_by(user_id=user.id, seen=False)
    if payload.ids:
        q = q.filter(BonusUnlock.id.in_(payload.ids))
    n = q.update({"seen": True}, synchronize_session=False)
    db.commit()
    return {"status": "ok", "seen": n}


@router.get("/admin/collection-bonus", dependencies=[Depends(require_admin)])
def admin_list(db: Session = Depends(get_db)):
    users = {u.id: u.pseudo for u in db.query(User).all()}
    return [{"kind": r.kind, "pseudo": users.get(r.user_id), "subject": (db.get(Player, r.subject_id).name if db.get(Player, r.subject_id) else None),
             "unlocked_at": r.unlocked_at.isoformat() if r.unlocked_at else None, "seen": r.seen}
            for r in db.query(BonusUnlock).order_by(BonusUnlock.unlocked_at.desc()).all()]


@router.post("/admin/collection-bonus-grant", dependencies=[Depends(require_admin)])
def admin_grant(payload: GrantRequest, db: Session = Depends(get_db)):
    """Pour essayer : donne la récompense (prisme / couronne) d'une personne à un compte, sans les conditions. La révélation se jouera au prochain /me."""
    kind = (payload.kind or "").strip().lower()
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="Sorte inconnue : prisme ou couronne")
    user = db.query(User).filter_by(pseudo=payload.pseudo.strip()).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    subject = db.query(Player).filter_by(name=payload.player_name.strip()).first()
    if subject is None or game_logic.card_kind(subject) not in ("joueur", "fan"):
        raise HTTPException(status_code=404, detail="Joueur ou fan introuvable : %s (nom exact)" % payload.player_name)
    row = db.query(BonusUnlock).filter_by(user_id=user.id, kind=kind, subject_id=subject.id).first()
    if row is not None:
        row.seen = False; db.commit()
        return {"status": "ok", "already": True, "note": "déjà débloqué : la révélation sera rejouée"}
    if kind == "couronne":
        other = db.query(BonusUnlock).filter_by(kind="couronne", subject_id=subject.id).first()
        if other is not None:
            raise HTTPException(status_code=400, detail="La Couronne noire de %s appartient déjà à un autre joueur (elle est unique)" % subject.name)
    _unlock(db, user, kind, subject)
    db.commit()
    return {"status": "ok", "kind": kind, "pseudo": user.pseudo, "subject": subject.name}


@router.post("/admin/collection-bonus-replay", dependencies=[Depends(require_admin)])
def admin_replay(payload: PseudoRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(pseudo=payload.pseudo.strip()).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    n = db.query(BonusUnlock).filter_by(user_id=user.id).update({"seen": False}, synchronize_session=False)
    db.commit()
    return {"status": "ok", "replays": n}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(BonusUnlock).filter_by(user_id=user_id).delete()      # (une Couronne libérée peut être gagnée par quelqu'un d'autre)
