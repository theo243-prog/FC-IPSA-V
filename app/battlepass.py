"""
Pass de saison (un par mois) : une piste GRATUITE et une piste PREMIUM (300 crédits), 30 niveaux, un niveau qui se débloque par jour.

POINTS : 100 points par niveau. On gagne des points en jouant (missions du jour, matchs 1v1, tournoi, pronostics, échanges de cartes), avec un plafond par jour
pour chaque source. Les points ne se perdent JAMAIS : si on dépasse les 100 points dès le 1er jour, le niveau 2 attend simplement le lendemain, etc.
(le niveau N se débloque le jour N du mois ; en février les deux derniers niveaux se débloquent le dernier jour). Pendant la dernière semaine du mois, les points sont DOUBLÉS.
RÉCOMPENSES : chaque niveau a une récompense gratuite (crédits, packs, 3 objets sur la saison) et une récompense Premium (un objet décoratif par niveau, de toutes sortes,
+ des bonus : pack rare, crédits, 2 packs d'édition limitée aux niveaux 20 et 30, et la carte exclusive du Pass au niveau 25). Les récompenses non récupérées restent
disponibles 7 jours après la fin du mois (rattrapage, sans limite par jour). Quand les 30 niveaux sont débloqués : une ÉTOILE de prestige permanente.
OBJECTIF DU CLUB : une barre commune (packs ouverts par tous ce mois-ci) ; à chaque palier, TOUS les joueurs peuvent récupérer une récompense. Aucun avantage à payer.
THÈME : un par mois (Halloween en novembre, Noël en décembre…), réglable dans l'administration.
"""
import calendar
import json
import random
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import AppSetting, Card, OwnedCard, Player, Tier, User, gen_id
from .common import card_out, require_admin
from .security import get_current_user
from . import game_logic, missions, profiles, seasons
from . import pass_catalog as P
from .prono import now_paris

from . import events

router = APIRouter()
PRICE, CATCHUP_DAYS, LEVEL_PRICE = 300, 7, 20       # Premium 300 crédits ; 20 crédits pour acheter directement le niveau suivant
DAILY_CAPS = {"mission": 80, "duel": 50, "swap": 30, "prono": 30, "minigame": 50}          # points de base par jour et par source


class PassProgress(Base):
    __tablename__ = "pass_progress"
    __table_args__ = (UniqueConstraint("user_id", "season", name="uq_pass_progress"),)
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False, index=True)
    season = Column(String, nullable=False, index=True)
    points = Column(Integer, nullable=False, default=0)
    premium = Column(Integer, nullable=False, default=0)
    premium_at = Column(DateTime, nullable=True)
    completed = Column(Integer, nullable=False, default=0)
    daily = Column(Text, nullable=True)                     # {"d": jour, "src": {source: points de base du jour}}


class PassClaim(Base):
    __tablename__ = "pass_claims"
    __table_args__ = (UniqueConstraint("user_id", "season", "key", name="uq_pass_claim"),)
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, nullable=False, index=True)
    season = Column(String, nullable=False)
    key = Column(String, nullable=False)                    # f12 (gratuit, niveau 12), p12 (premium), c3 (objectif du club, palier 3)
    item_id = Column(String, nullable=True)
    at = Column(DateTime, default=datetime.utcnow)


class ClubGoal(Base):
    __tablename__ = "pass_club"
    season = Column(String, primary_key=True)
    packs = Column(Integer, nullable=False, default=0)


class PassLoadout(Base):
    __tablename__ = "pass_loadout"
    user_id = Column(String, primary_key=True)
    banner = Column(String, nullable=True)
    name_color = Column(String, nullable=True)
    badge = Column(String, nullable=True)
    share_bg = Column(String, nullable=True)


class ClaimRequest(BaseModel):
    season: Optional[str] = None
    track: str                                              # free / premium / club
    level: int = Field(ge=0, le=100)                        # niveau (1-30), ou numéro du palier du club (0-4)


class EquipRequest(BaseModel):
    banner: Optional[str] = None
    name_color: Optional[str] = None
    badge: Optional[str] = None
    share_bg: Optional[str] = None


class AdminThemeRequest(BaseModel):
    month: str
    theme: str


class AdminGrantRequest(BaseModel):
    pseudo: str
    points: int = Field(default=0, ge=0, le=100000)
    premium: Optional[bool] = None


class AdminClubRequest(BaseModel):
    packs: int = Field(default=0, ge=0, le=1000000)
    goals: Optional[List[int]] = None


# ------------------------------------------------------------------ calendrier
def dim(key: str) -> int:
    y, m = map(int, key.split("-")); return calendar.monthrange(y, m)[1]


def season_end(key: str) -> datetime:
    y, m = map(int, key.split("-")); return datetime(y + (m == 12), m % 12 + 1, 1)


def prev_key(key: str) -> str:
    y, m = map(int, key.split("-")); return "%d-%02d" % (y - (m == 1), (m - 2) % 12 + 1)


def in_catchup(key: str, now: datetime) -> bool:
    end = season_end(key); return end <= now < end + timedelta(days=CATCHUP_DAYS)


def unlocked_level(points: int, key: str, now: datetime) -> int:
    cap = P.LEVELS if now >= season_end(key) else (P.LEVELS if now.day >= dim(key) else now.day)        # le niveau N se débloque le jour N
    return max(0, min(P.LEVELS, points // P.POINTS_PER_LEVEL, cap))


def multiplier(key: str, now: datetime) -> int:
    return 2 if season_end(key) > now and now.day >= dim(key) - 6 else 1                   # dernière semaine du mois : points doublés


def theme_for(db: Session, key: str) -> str:
    row = db.get(AppSetting, "pass_theme:" + key)
    return row.value if row is not None and row.value in P.THEMES else P.DEFAULT_THEME_BY_MONTH[int(key[5:])]


def club_goals(db: Session) -> list:
    row = db.get(AppSetting, "pass_club_goals")
    try:
        goals = json.loads(row.value) if row is not None else None
    except ValueError:
        goals = None
    return goals if goals and len(goals) == len(P.CLUB_TIERS) else [g for g, _ in P.CLUB_TIERS]


def _progress(db: Session, user_id: str, key: str, create: bool = False):
    row = db.query(PassProgress).filter_by(user_id=user_id, season=key).first()
    if row is None and create:
        row = PassProgress(user_id=user_id, season=key); db.add(row); db.flush()
    return row


def _claims(db: Session, user_id: str, key: str) -> set:
    return {c.key for c in db.query(PassClaim).filter_by(user_id=user_id, season=key).all()}


# ------------------------------------------------------------------ gagner des points (jamais bloquant)
def add_points(db: Session, user: User, source: str, pts: int, cap: Optional[int] = None) -> int:
    """Ajoute des points de Pass pour une action. Ne valide PAS la transaction (l'appelant le fait) et ne fait jamais échouer l'action du joueur."""
    try:
        with db.begin_nested():
            now = now_paris(); key = seasons.key_of(now); row = _progress(db, user.id, key, create=True)
            daily = json.loads(row.daily) if row.daily else {}
            today = now.date().isoformat()
            if daily.get("d") != today:
                daily = {"d": today, "src": {}}
            got = int(daily["src"].get(source, 0)); allowed = pts if cap is None else max(0, min(pts, cap - got))
            if allowed <= 0:
                return 0
            gain = allowed * max(multiplier(key, now), 2 if events.pass_double(db) else 1)          # dernière semaine du mois OU événement « ×2 » (pas de cumul)
            daily["src"][source] = got + allowed; row.daily = json.dumps(daily); row.points = (row.points or 0) + gain
            return gain
    except Exception:
        return 0


def club_add(db: Session, n: int = 1) -> None:
    """Un pack a été ouvert : la barre commune du club avance."""
    try:
        with db.begin_nested():
            key = seasons.key_of(now_paris()); row = db.get(ClubGoal, key)
            if row is None:
                row = ClubGoal(season=key, packs=0); db.add(row)
            row.packs = (row.packs or 0) + int(n)
    except Exception:
        pass


# ------------------------------------------------------------------ objets, étoiles
def owned_ids(db: Session, user: User) -> set:
    if profiles._counter(db, user.id, "cosmetics_all") == 1:                  # compte d'essai : tout débloqué à la main
        return set(P.ITEMS)
    return {c.item_id for c in db.query(PassClaim).filter(PassClaim.user_id == user.id, PassClaim.item_id.isnot(None)).all() if c.item_id in P.ITEMS}


def owned_items(db: Session, user: User, kind: Optional[str] = None) -> list:
    return [P.ITEMS[i] for i in sorted(owned_ids(db, user)) if kind is None or P.ITEMS[i]["kind"] == kind]


def stars_map(db: Session) -> dict:
    return dict(db.query(PassProgress.user_id, func.count()).filter(PassProgress.completed == 1).group_by(PassProgress.user_id).all())


def display_map(db: Session) -> dict:
    """{joueur: {badge, name_color, stars}} : ce qui s'affiche à côté d'un pseudo (classement, chat, profil)."""
    out = {uid: {"badge": None, "name_color": None, "stars": n} for uid, n in stars_map(db).items()}
    for r in db.query(PassLoadout).all():
        d = out.setdefault(r.user_id, {"badge": None, "name_color": None, "stars": 0}); d["badge"], d["name_color"] = r.badge, r.name_color
    return out


def user_display(db: Session, user_id: str) -> dict:
    r = db.query(PassLoadout).filter_by(user_id=user_id).first()
    stars = db.query(func.count()).select_from(PassProgress).filter(PassProgress.user_id == user_id, PassProgress.completed == 1).scalar() or 0
    return {"badge": r.badge if r else None, "name_color": r.name_color if r else None, "banner": r.banner if r else None, "share_bg": r.share_bg if r else None, "stars": int(stars)}


def ensure_completion(db: Session, user: User, key: str, now: datetime) -> bool:
    row = _progress(db, user.id, key)
    if row is not None and not row.completed and unlocked_level(row.points, key, now) >= P.LEVELS:
        row.completed = 1
        db.flush()                                              # (pour que l'étoile qu'on vient de gagner soit comptée)
        n = db.query(func.count()).select_from(PassProgress).filter(PassProgress.user_id == user.id, PassProgress.completed == 1).scalar()
        from . import chat
        chat.add_event(db, "🌟 %s a terminé le Pass de %s ! Étoile de prestige n°%d." % (user.pseudo, seasons.label_of(key), n), user)
        return True
    return False


def pass_card(db: Session, key: str, theme_id: str) -> Card:
    """La carte exclusive du Pass du mois, au style du thème (créée la première fois, une par saison)."""
    t = P.THEMES[theme_id]; name = "Pass %s (%s)" % (t["name"], seasons.label_of(key))
    player = db.query(Player).filter_by(name=name).first()
    if player is None:
        player = Player(name=name, poste="TROPHEE"); db.add(player); db.flush()
    card = db.query(Card).filter_by(player_id=player.id, tier=Tier.saison).first()
    if card is None:
        card = Card(player_id=player.id, tier=Tier.saison, vitesse=0, tir=0); db.add(card); db.flush()
    return card


def _edition_pack(db: Session, user: User, theme_id: str, n: int) -> dict:
    """Un « pack d'édition limitée » : n cartes de l'édition du thème (de préférence nouvelles). Sans édition (ou sans carte), repli : packs rares."""
    ed = P.THEMES[theme_id].get("edition"); cards = db.query(Card).filter(Card.tier == Tier(ed)).all() if ed else []
    if not cards:
        ps = user.pack_state; ps.rare_pack_tokens = (getattr(ps, "rare_pack_tokens", 0) or 0) + (1 if n <= 2 else 2)
        return {"fallback": "pack rare", "count": 1 if n <= 2 else 2}
    owned = {o.card_id for o in db.query(OwnedCard).filter(OwnedCard.user_id == user.id, OwnedCard.quantity > 0).all()}
    fresh = [c for c in cards if c.id not in owned]; random.shuffle(fresh); rest = [c for c in cards if c.id in owned]; random.shuffle(rest)
    won = (fresh + rest)[:n]
    for c in won:
        game_logic.get_or_create_owned(db, user, c).quantity += 1
    return {"cards": [card_out(c) for c in won], "edition": ed}


def _grant(db: Session, user: User, season: str, reward: dict, theme_id: str) -> dict:
    out = {}
    if reward.get("credits"):
        user.credits += int(reward["credits"]); out["credits"] = int(reward["credits"])
    if reward.get("pack"):
        missions._grant(user, {"pack": reward["pack"]}); out["pack"] = reward["pack"]
    if reward.get("edition_pack"):
        out["edition_pack"] = _edition_pack(db, user, theme_id, int(reward["edition_pack"]))
    if reward.get("pass_card"):
        c = pass_card(db, season, theme_id); o = game_logic.get_or_create_owned(db, user, c); o.quantity = max(o.quantity, 1); out["pass_card"] = card_out(c)
    if reward.get("item"):
        out["item"] = P.ITEMS[reward["item"]]
    return out


# ------------------------------------------------------------------ état affiché
def _reward_out(reward, theme_id):
    return None if not reward else {**{k: v for k, v in reward.items()}, "label": P.reward_label(reward, theme_id), "item_obj": P.ITEMS.get(reward.get("item")) if reward.get("item") else None}


def season_out(db: Session, user: User, key: str, now: datetime) -> dict:
    theme_id = theme_for(db, key); th = P.THEMES[theme_id]; row = _progress(db, user.id, key); points = row.points if row else 0
    level = unlocked_level(points, key, now); premium = bool(row and row.premium); claims = _claims(db, user.id, key); d = dim(key); over = now >= season_end(key)
    levels = []
    for lv in range(1, P.LEVELS + 1):
        fr, pr = P.free_reward(theme_id, lv), P.premium_reward(theme_id, lv)
        fs = "claimed" if "f%d" % lv in claims else ("ready" if lv <= level else "locked")
        ps = "claimed" if "p%d" % lv in claims else (("ready" if lv <= level else "locked") if premium else "premium_locked")
        levels.append({"level": lv, "unlock_day": min(lv, d), "reached": lv <= level, "free": {"status": fs, **_reward_out(fr, theme_id)} if fr else None, "premium": {"status": ps, **_reward_out(pr, theme_id)}})
    by_points = min(P.LEVELS, points // P.POINTS_PER_LEVEL)
    out = {"key": key, "label": seasons.label_of(key), "theme": {"id": theme_id, **{k: th[k] for k in ("name", "emoji", "c1", "c2", "accent")}}, "points": points, "level": level, "premium": premium,
           "day": min(now.day, d) if not over else d, "days": d, "ended": over, "double_points": multiplier(key, now) == 2, "ends_at": season_end(key).isoformat(),
           "points_in_level": points % P.POINTS_PER_LEVEL if level < P.LEVELS else P.POINTS_PER_LEVEL, "waiting_for_day": level < P.LEVELS and by_points > level and not over,
           "completed": bool(row and row.completed), "levels": levels, "club": club_out(db, user, key, claims), "claimable": sum(1 for l in levels for t in ("free", "premium") if l[t] and l[t]["status"] == "ready") + sum(1 for t in club_out(db, user, key, claims)["tiers"] if t["reached"] and not t["claimed"])}
    if over:
        out["catchup_until"] = (season_end(key) + timedelta(days=CATCHUP_DAYS)).isoformat()
    return out


def club_out(db: Session, user: User, key: str, claims: set) -> dict:
    goals = club_goals(db); row = db.get(ClubGoal, key); packs = row.packs if row else 0
    return {"packs": packs, "tiers": [{"index": i, "goal": g, "reward": P.CLUB_TIERS[i][1], "label": P.reward_label({**P.CLUB_TIERS[i][1], **({"item": P.CLUB_STICKER["id"]} if i == len(goals) - 1 else {})}, ""),
                                       "reached": packs >= g, "claimed": "c%d" % i in claims} for i, g in enumerate(goals)]}


def claimable_count(db: Session, user: User) -> int:
    now = now_paris(); key = seasons.key_of(now); n = 0
    for k in (key, prev_key(key)) if now.day <= CATCHUP_DAYS else (key,):
        if k != key and not in_catchup(k, now): continue
        n += season_out(db, user, k, now)["claimable"]
    return n


@router.get("/pass")
def get_pass(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = now_paris(); key = seasons.key_of(now); pk = prev_key(key)
    for k in (key, pk):
        if ensure_completion(db, user, k, now): db.commit()
    prev = season_out(db, user, pk, now) if in_catchup(pk, now) and (_progress(db, user.id, pk) is not None or db.get(ClubGoal, pk)) else None
    return {"now": now.isoformat(), "price": PRICE, "level_price": LEVEL_PRICE, "current": season_out(db, user, key, now), "previous": prev, "stars": user_display(db, user.id)["stars"], "loadout": user_display(db, user.id),
            "points_help": {"minigame": "mini-jeu du jour (10 par bonne réponse ou but, 50 au maximum)", "mission": "missions du jour (20 par mission)", "duel": "match 1v1 (10)", "tournoi": "tournoi : inscription 30, tour gagné 20", "prono": "pronostic (15), score exact (60)", "swap": "échange de cartes (15)"}}


@router.post("/pass/claim")
def claim(payload: ClaimRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = now_paris(); cur = seasons.key_of(now); key = payload.season or cur
    if key != cur and not in_catchup(key, now):
        raise HTTPException(status_code=400, detail="Ce Pass est terminé : les récompenses ne se récupèrent plus")
    if not (key == cur or key == prev_key(cur)):
        raise HTTPException(status_code=400, detail="Saison inconnue")
    theme_id = theme_for(db, key); row = _progress(db, user.id, key); points = row.points if row else 0; level = unlocked_level(points, key, now); claims = _claims(db, user.id, key)
    if payload.track == "club":
        goals = club_goals(db); i = payload.level
        if not (0 <= i < len(goals)): raise HTTPException(status_code=400, detail="Palier inconnu")
        cg = db.get(ClubGoal, key)
        if (cg.packs if cg else 0) < goals[i]: raise HTTPException(status_code=400, detail="L'objectif du club n'est pas encore atteint pour ce palier")
        ck = "c%d" % i
        if ck in claims: raise HTTPException(status_code=400, detail="Tu as déjà récupéré ce palier")
        reward = dict(P.CLUB_TIERS[i][1]); item = P.CLUB_STICKER["id"] if i == len(goals) - 1 else None
        if item: reward["item"] = item
    else:
        lv = payload.level
        if not (1 <= lv <= P.LEVELS): raise HTTPException(status_code=400, detail="Niveau inconnu")
        if lv > level: raise HTTPException(status_code=400, detail="Le niveau %d n'est pas encore débloqué%s" % (lv, " (il s'ouvre le jour %d du mois)" % min(lv, dim(key)) if points >= lv * P.POINTS_PER_LEVEL else ""))
        if payload.track == "free":
            ck, reward = "f%d" % lv, P.free_reward(theme_id, lv)
            if not reward: raise HTTPException(status_code=400, detail="Pas de récompense gratuite à ce niveau")
        elif payload.track == "premium":
            if not (row and row.premium): raise HTTPException(status_code=400, detail="Cette récompense est réservée au Pass Premium")
            ck, reward = "p%d" % lv, P.premium_reward(theme_id, lv)
        else:
            raise HTTPException(status_code=400, detail="Piste inconnue")
        if ck in claims: raise HTTPException(status_code=400, detail="Tu as déjà récupéré cette récompense")
    got = _grant(db, user, key, reward, theme_id)
    db.add(PassClaim(user_id=user.id, season=key, key=ck, item_id=reward.get("item"))); ensure_completion(db, user, key, now); db.commit()
    return {"status": "ok", "season": key, "reward": got, "credits": user.credits}


@router.post("/pass/premium")
def buy_premium(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = now_paris(); key = seasons.key_of(now); row = _progress(db, user.id, key, create=True)
    if row.premium: raise HTTPException(status_code=400, detail="Tu as déjà le Pass Premium de ce mois")
    if user.credits < PRICE: raise HTTPException(status_code=400, detail="Il te faut %d crédits (tu en as %d)" % (PRICE, user.credits))
    user.credits -= PRICE; row.premium, row.premium_at = 1, datetime.utcnow()
    from . import chat
    chat.add_event(db, "💎 %s a pris le Pass Premium de %s !" % (user.pseudo, seasons.label_of(key)), user)
    db.commit()
    return {"status": "ok", "credits": user.credits, "claimable": season_out(db, user, key, now)["claimable"]}


@router.post("/pass/buy-level")
def buy_level(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """20 crédits : on gagne les points qui manquent pour atteindre le niveau SUIVANT (le niveau ne s'ouvre quand même que le jour qui lui correspond). Pass du mois en cours seulement."""
    now = now_paris(); key = seasons.key_of(now); row = _progress(db, user.id, key, create=True); total = P.LEVELS * P.POINTS_PER_LEVEL
    if (row.points or 0) >= total:
        raise HTTPException(status_code=400, detail="Tu as déjà atteint les %d niveaux de ce Pass" % P.LEVELS)
    if user.credits < LEVEL_PRICE:
        raise HTTPException(status_code=400, detail="Il te faut %d crédits (tu en as %d)" % (LEVEL_PRICE, user.credits))
    target = ((row.points or 0) // P.POINTS_PER_LEVEL + 1) * P.POINTS_PER_LEVEL; gained = target - (row.points or 0)
    user.credits -= LEVEL_PRICE; row.points = target
    ensure_completion(db, user, key, now); db.commit()
    reached = min(P.LEVELS, row.points // P.POINTS_PER_LEVEL)
    return {"status": "ok", "credits": user.credits, "points": row.points, "gained": gained, "reached": reached, "unlocked": unlocked_level(row.points, key, now), "opens_day": min(reached, dim(key))}


@router.get("/pass/inventory")
def inventory(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lo = db.query(PassLoadout).filter_by(user_id=user.id).first()
    return {"items": owned_items(db, user), "loadout": {k: getattr(lo, k, None) if lo else None for k in ("banner", "name_color", "badge", "share_bg")}}


@router.post("/pass/equip")
def equip(payload: EquipRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned = owned_ids(db, user); lo = db.query(PassLoadout).filter_by(user_id=user.id).first()
    if lo is None:
        lo = PassLoadout(user_id=user.id); db.add(lo)
    for slot in ("banner", "name_color", "badge", "share_bg"):
        v = getattr(payload, slot)
        if v is not None and (v not in owned or P.ITEMS[v]["kind"] != slot):
            raise HTTPException(status_code=400, detail="Tu n'as pas cet objet (ou il ne va pas à cet emplacement)")
        setattr(lo, slot, v)
    db.commit()
    return {"status": "ok"}


@router.get("/pass/styles")
def styles():
    """Le dessin de tous les objets (pour que le site puisse afficher ceux des autres joueurs) : public."""
    return {"items": {i: {"kind": it["kind"], "name": it["name"], "emoji": it["emoji"], "style": it["style"]} for i, it in P.ITEMS.items()},
            "themes": {k: {kk: v[kk] for kk in ("name", "emoji", "c1", "c2", "accent")} for k, v in P.THEMES.items()}}


# ------------------------------------------------------------------ administration
@router.get("/admin/pass", dependencies=[Depends(require_admin)])
def admin_pass(db: Session = Depends(get_db)):
    now = now_paris(); key = seasons.key_of(now); nk = seasons.next_key(key)
    rows = db.query(PassProgress).filter_by(season=key).all(); cg = db.get(ClubGoal, key)
    return {"season": key, "theme": theme_for(db, key), "next_season": nk, "next_theme": theme_for(db, nk), "themes": list(P.THEMES), "players": len(rows), "premium": sum(1 for r in rows if r.premium),
            "average_level": round(sum(unlocked_level(r.points, key, now) for r in rows) / len(rows), 1) if rows else 0, "club_packs": cg.packs if cg else 0, "club_goals": club_goals(db), "double_points": multiplier(key, now) == 2}


@router.post("/admin/pass-theme", dependencies=[Depends(require_admin)])
def admin_pass_theme(payload: AdminThemeRequest, db: Session = Depends(get_db)):
    import re
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", payload.month): raise HTTPException(status_code=422, detail="Le mois doit s'écrire comme 2026-11")
    if payload.theme not in P.THEMES: raise HTTPException(status_code=422, detail="Thèmes possibles : " + ", ".join(P.THEMES))
    k = "pass_theme:" + payload.month; row = db.get(AppSetting, k)
    if row is None: db.add(AppSetting(key=k, value=payload.theme))
    else: row.value = payload.theme
    db.commit()
    return {"status": "ok", "month": payload.month, "theme": payload.theme}


@router.post("/admin/pass-grant", dependencies=[Depends(require_admin)])
def admin_pass_grant(payload: AdminGrantRequest, db: Session = Depends(get_db)):
    """Pour essayer le Pass : ajoute des points (sans plafond ni doublement) et/ou active/retire le Premium d'un compte, pour le mois en cours."""
    user = db.query(User).filter_by(pseudo=payload.pseudo).first()
    if user is None: raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    now = now_paris(); key = seasons.key_of(now); row = _progress(db, user.id, key, create=True)
    row.points = (row.points or 0) + payload.points
    if payload.premium is not None:
        row.premium = 1 if payload.premium else 0
        if payload.premium and not row.premium_at: row.premium_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "pseudo": user.pseudo, "points": row.points, "level": unlocked_level(row.points, key, now), "premium": bool(row.premium)}


@router.post("/admin/pass-club", dependencies=[Depends(require_admin)])
def admin_pass_club(payload: AdminClubRequest, db: Session = Depends(get_db)):
    key = seasons.key_of(now_paris())
    if payload.goals is not None:
        g = payload.goals
        if len(g) != len(P.CLUB_TIERS) or any(x < 1 for x in g) or g != sorted(g): raise HTTPException(status_code=422, detail="Donne %d paliers croissants (ex. 500, 1000, 1500, 2000, 3000)" % len(P.CLUB_TIERS))
        row = db.get(AppSetting, "pass_club_goals")
        if row is None: db.add(AppSetting(key="pass_club_goals", value=json.dumps(g)))
        else: row.value = json.dumps(g)
    if payload.packs:
        cg = db.get(ClubGoal, key)
        if cg is None: cg = ClubGoal(season=key, packs=0); db.add(cg)
        cg.packs = (cg.packs or 0) + payload.packs
    db.commit()
    cg = db.get(ClubGoal, key)
    return {"status": "ok", "packs": cg.packs if cg else 0, "goals": club_goals(db)}


def tick(db: Session) -> None:
    """Chaque minute (planificateur) : les étoiles de prestige de la saison qui vient de finir (rattrapage) sont attribuées même si le joueur ne se connecte pas."""
    now = now_paris(); key = seasons.key_of(now); pk = prev_key(key)
    if not in_catchup(pk, now): return
    for row in db.query(PassProgress).filter_by(season=pk, completed=0).filter(PassProgress.points >= P.LEVELS * P.POINTS_PER_LEVEL).all():
        u = db.get(User, row.user_id)
        if u is not None: ensure_completion(db, u, pk, now)
    db.commit()


def on_user_deleted(db: Session, user_id: str) -> None:
    for m in (PassProgress, PassClaim, PassLoadout):
        db.query(m).filter_by(user_id=user_id).delete()
