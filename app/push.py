"""
Notifications push (Web Push) : prévenir les joueurs même quand le site est fermé.

- Le joueur active les notifications depuis le site (bouton 🔔) : son navigateur nous donne une « adresse » chiffrée.
- Les actions du jeu déposent un message dans une file (push_outbox) ; une tâche de fond (toutes les minutes) l'envoie.
  Un incident d'envoi ne peut donc jamais faire échouer une action du jeu.
- Pas de notification entre 22h et 8h (heure de Paris) : elles partent le matin. Plafond : 6 par joueur et par jour.
- Les clés VAPID (l'identité du serveur) sont générées au premier démarrage puis conservées en base.
"""
import base64
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AppSetting, NotifPref, NotifState, PushOutbox, PushSubscription, User
from .weekly import from_paris, to_paris

try:
    from pywebpush import WebPushException, webpush
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization as _ser
    AVAILABLE = True
except Exception:          # bibliothèque absente : le site fonctionne, simplement sans notifications
    AVAILABLE = False

KINDS = ("packs", "cards", "duels", "market")
QUIET_START, QUIET_END = 22, 8        # heure de Paris : pas de notification de 22h à 8h
MAX_PER_DAY = 6
MAX_DEVICES = 5                       # appareils par joueur
MAX_FAILURES = 5                      # échecs d'envoi consécutifs avant d'oublier un appareil
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "https://fc-ipsa-v-production.up.railway.app")
# On n'envoie qu'aux vrais services de notification des navigateurs (sinon un joueur pourrait faire
# appeler une adresse interne de notre serveur).
ALLOWED_HOSTS = ("fcm.googleapis.com", "push.apple.com", "push.services.mozilla.com", "notify.windows.com")
TIER_NAMES = {"commune": "Commune", "rare": "Rare", "gold": "Gold", "secrete": "Secrète", "speciale": "Spéciale",
              "epique": "Épique", "legendaire": "Légendaire"}

_vapid_cache = {}


# ------------------------------------------------------------------- clés ----

def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _load_or_create_keys(db: Session):
    row = db.get(AppSetting, "vapid_private_pem")
    if row is None:
        v = Vapid()
        v.generate_keys()
        try:
            db.add(AppSetting(key="vapid_private_pem", value=v.private_pem().decode()))
            db.commit()
        except IntegrityError:            # un autre processus vient de les créer
            db.rollback()
            row = db.get(AppSetting, "vapid_private_pem")
    if row is None:
        row = db.get(AppSetting, "vapid_private_pem")
    vapid = Vapid.from_pem(row.value.encode())
    public = _b64u(vapid.public_key.public_bytes(_ser.Encoding.X962, _ser.PublicFormat.UncompressedPoint))
    return vapid, public


def vapid_pair(db: Session):
    if "pair" not in _vapid_cache:
        _vapid_cache["pair"] = _load_or_create_keys(db)
    return _vapid_cache["pair"]


def public_key(db: Session) -> str:
    return vapid_pair(db)[1]


# ------------------------------------------------------------ validation ----

def endpoint_allowed(endpoint: str) -> bool:
    if os.getenv("PUSH_ALLOW_ANY_ENDPOINT") == "1":          # uniquement pour les tests automatiques
        return True
    try:
        u = urlparse(endpoint)
    except Exception:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


# ----------------------------------------------------------- calme la nuit ----

def is_quiet(now_utc: datetime) -> bool:
    h = to_paris(now_utc).hour
    return h >= QUIET_START or h < QUIET_END


def next_morning(now_utc: datetime) -> datetime:
    local = to_paris(now_utc)
    day = local.date() + (timedelta(days=1) if local.hour >= QUIET_START else timedelta(0))
    return from_paris(datetime(day.year, day.month, day.day, QUIET_END, 0))


# --------------------------------------------------------------- préférences ----

def prefs_dict(db: Session, user_id: str) -> dict:
    row = db.get(NotifPref, user_id)
    return {k: (True if row is None else bool(getattr(row, k))) for k in KINDS}


def device_count(db: Session, user_id: str) -> int:
    return db.query(PushSubscription).filter_by(user_id=user_id).count()


# ------------------------------------------------------------------ envoi ----

def send_one(sub: PushSubscription, payload: dict, vapid) -> tuple:
    """Envoie un message à un appareil. Retourne ("ok" | "gone" | "error", détail)."""
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid, vapid_claims={"sub": VAPID_SUBJECT},
            ttl=12 * 3600, timeout=10,
        )
        return "ok", None
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        return ("gone" if status in (404, 410) else "error"), "%s: %s" % (status, e)
    except Exception as e:
        return "error", str(e)


SENDER = send_one          # remplaçable : les tests y mettent un faux serveur


def deliver(db: Session, user_id: str, payload: dict) -> dict:
    """Envoie tout de suite à tous les appareils d'un joueur ; oublie ceux qui n'existent plus."""
    vapid, _ = vapid_pair(db)
    ok = failed = 0
    for sub in db.query(PushSubscription).filter_by(user_id=user_id).all():
        state, _detail = SENDER(sub, payload, vapid)
        if state == "ok":
            ok += 1
            sub.last_ok_at, sub.failures = datetime.utcnow(), 0
        else:
            failed += 1
            sub.failures += 1
            if state == "gone" or sub.failures >= MAX_FAILURES:
                db.delete(sub)
    db.commit()
    return {"sent": ok, "failed": failed}


# --------------------------------------------------------- file d'attente ----

def enqueue(db: Session, user_id: str, kind: str, title: str, body: str, url: str = "/", tag: str = None,
            meta: dict = None, now: datetime = None, force: bool = False) -> bool:
    """Dépose une notification pour un joueur (si elle l'intéresse). Ne fait pas de commit."""
    now = now or datetime.utcnow()
    if device_count(db, user_id) == 0:
        return False
    if kind in KINDS and not prefs_dict(db, user_id)[kind]:
        return False
    send_after = now if (force or not is_quiet(now)) else next_morning(now)
    db.add(PushOutbox(user_id=user_id, kind=kind, title=title[:120], body=body[:300], url=url, tag=tag or kind,
                      meta=json.dumps(meta) if meta else None, created_at=now, send_after=send_after, force=force))
    return True


def notify_users(db: Session, user_ids, kind: str, title: str, body: str, **kw) -> int:
    return sum(1 for uid in set(user_ids) if enqueue(db, uid, kind, title, body, **kw))


def notify_all(db: Session, kind: str, title: str, body: str, **kw) -> int:
    ids = [r[0] for r in db.query(PushSubscription.user_id).distinct().all()]
    return notify_users(db, ids, kind, title, body, **kw)


def safe(db: Session, fn, *args, **kwargs):
    """Les notifications ne doivent JAMAIS faire échouer une action du jeu."""
    try:
        fn(db, *args, **kwargs)
        db.commit()
    except Exception as exc:
        db.rollback()
        print("Notification ignorée :", exc)


def process_outbox(db: Session, now: datetime = None) -> dict:
    """Envoie les notifications arrivées à échéance. Appelée toutes les minutes."""
    now = now or datetime.utcnow()
    stats = {"sent": 0, "skipped": 0, "retry": 0}
    q = (db.query(PushOutbox).filter(PushOutbox.sent_at.is_(None), PushOutbox.skipped.is_(None), PushOutbox.send_after <= now)
         .order_by(PushOutbox.created_at).limit(200).with_for_update(skip_locked=True))
    rows = q.all()
    if not rows:
        return stats
    vapid, _ = vapid_pair(db)
    quiet = is_quiet(now)
    for row in rows:
        if quiet and not row.force:
            continue                                   # la nuit : elles attendent
        if now - row.created_at > timedelta(hours=24):
            row.skipped = "expired"
        elif row.kind == "packs" and not _pack_still_true(db, row):
            row.skipped = "stale"
        elif not row.force and db.query(PushOutbox).filter(PushOutbox.user_id == row.user_id, PushOutbox.sent_at > now - timedelta(hours=24)).count() >= MAX_PER_DAY:
            row.skipped = "cap"
        else:
            subs = db.query(PushSubscription).filter_by(user_id=row.user_id).all()
            if not subs:
                row.skipped = "no_subscription"
            else:
                payload = {"title": row.title, "body": row.body, "url": row.url, "tag": row.tag,
                           "icon": "/icons/icon-192.png", "badge": "/icons/badge-96.png"}
                ok = 0
                for sub in subs:
                    state, _d = SENDER(sub, payload, vapid)
                    if state == "ok":
                        ok += 1
                        sub.last_ok_at, sub.failures = now, 0
                    else:
                        sub.failures += 1
                        if state == "gone" or sub.failures >= MAX_FAILURES:
                            db.delete(sub)
                if ok:
                    row.sent_at = now
                    stats["sent"] += 1
                else:
                    row.attempts += 1
                    if row.attempts >= 3:
                        row.skipped = "failed"
                    else:
                        row.send_after = now + timedelta(minutes=2)
                        stats["retry"] += 1
        if row.skipped:
            stats["skipped"] += 1
        db.flush()            # (la session n'enregistre pas toute seule : sans ça, le plafond ne verrait pas les envois de ce même lot)
    db.commit()
    return stats


# ------------------------------------------------------- packs gratuits prêts ----

def _pack_level(stored: int, maximum: int) -> int:
    return 3 if stored >= maximum else (1 if stored >= 1 else 0)


def _pack_still_true(db: Session, row: PushOutbox) -> bool:
    """Au moment d'envoyer, le pack est-il toujours là ? (le joueur a pu l'ouvrir pendant la nuit)"""
    from . import game_logic
    user = db.get(User, row.user_id)
    if user is None:
        return False
    level = json.loads(row.meta or "{}").get("level", 1)
    stored = user.pack_state.stored_packs
    return stored >= (game_logic.MAX_STORED_PACKS if level >= 3 else 1)


def check_packs(db: Session, now: datetime = None) -> int:
    """Prévient (une seule fois) quand un pack gratuit est prêt, puis quand les 3 sont pleins."""
    from . import game_logic
    now = now or datetime.utcnow()
    users = (db.query(User).join(PushSubscription, PushSubscription.user_id == User.id)
             .filter(User.is_test.is_(False)).distinct().all())
    sent = 0
    for user in users:
        if not prefs_dict(db, user.id)["packs"]:
            continue
        game_logic.regen_user_packs(db, user)
        level = _pack_level(user.pack_state.stored_packs, game_logic.MAX_STORED_PACKS)
        state = db.get(NotifState, user.id)
        if state is None:
            db.add(NotifState(user_id=user.id, pack_level=level))      # première observation : on ne dit rien
            continue
        if level > state.pack_level:
            if level >= 3:
                title, body = "Tes %d packs gratuits sont prêts 🎁" % game_logic.MAX_STORED_PACKS, "Ils ne se rechargent plus tant que tu n'en ouvres pas."
            else:
                title, body = "Un pack gratuit t'attend 🎁", "Ouvre-le pour découvrir tes nouvelles cartes."
            sent += 1 if enqueue(db, user.id, "packs", title, body, url="/#pack", tag="packs", meta={"level": level}, now=now) else 0
        state.pack_level = level
    db.commit()
    return sent


# ------------------------------------------------------- messages du jeu ----

def notify_cards_from_match(db: Session, epics, moments, stade_created, stade_name):
    parts = []
    if epics:
        parts.append("Épique : " + ", ".join(epics))
    if moments:
        parts.append("Gold : " + ", ".join("%s (%s)" % (m["action"], m["player"]) for m in moments))
    if stade_created and stade_name:
        parts.append("Nouveau stade : " + stade_name)
    if parts:
        notify_all(db, "cards", "Nouvelles cartes au club ! ⚽", " · ".join(parts), url="/#collection", tag="cards")


def notify_weekly_specials(db: Session, awards):
    if awards:
        body = ", ".join("%s (%s)" % (a["player"], a["label"]) for a in awards)
        notify_all(db, "cards", "Cartes spéciales de la semaine ⭐", body + ". Elles sortent des packs gagnés en 1v1.", url="/#pack", tag="cards")


def notify_duel_played(db: Session, result: dict):
    """Prévient le créateur du défi : son défi vient d'être joué."""
    creator = db.query(User).filter_by(pseudo=result["defender"]).first()
    if creator is None:
        return
    mine, theirs, stake = result["score_defender"], result["score_challenger"], result["stake"]
    who = result["challenger"]
    if result["result"] == "défaite":       # le challenger a perdu : le créateur gagne
        title, body = "%s a joué ton défi : victoire %d–%d ! 🏆" % (who, mine, theirs), "Tu gagnes %d crédits et un pack match." % stake
    elif result["result"] == "victoire":
        title, body = "%s a joué ton défi : défaite %d–%d" % (who, mine, theirs), "Tu perds ta mise de %d crédits. Une revanche ?" % stake
    else:
        title, body = "%s a joué ton défi : match nul %d–%d" % (who, mine, theirs), "Ta mise de %d crédits t'est rendue." % stake
    enqueue(db, creator.id, "duels", title, body, url="/#duels", tag="duels")


def notify_listing_sold(db: Session, seller_id: str, buyer_pseudo: str, card, price: int):
    enqueue(db, seller_id, "market", "Carte vendue ! 💰",
            "%s a acheté ta carte %s (%s) pour %d crédits." % (buyer_pseudo, card.player.name, TIER_NAMES.get(card.tier.value, card.tier.value), price),
            url="/#marche", tag="market")
