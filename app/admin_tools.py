"""
Journal des actions de l'administration et tableau de bord.

- JOURNAL : chaque commande d'administration qui MODIFIE quelque chose (POST/DELETE sur /admin/...) est notée : quand, laquelle, avec
  quelles valeurs (raccourcies), et si elle a réussi. Les simples consultations ne sont pas notées. La clé admin n'est jamais enregistrée.
  Le journal ne peut jamais bloquer une commande : s'il échoue, la commande passe quand même.
- TABLEAU DE BORD : joueurs, activité, packs, matchs 1v1, marché, crédits en circulation.
"""
import json
import statistics
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, get_db
from .models import Duel, Listing, MatchProposal, User
from .common import require_admin
from . import duel_engine, game_logic, missions, profiles, sessions, welcome

router = APIRouter()
MAX_PAYLOAD_CHARS = 700


class AdminLog(Base):
    """Une action d'administration (sans clés étrangères : le journal est une trace, il survit à tout)."""
    __tablename__ = "admin_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, default=datetime.utcnow, index=True)
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    status = Column(Integer, nullable=False)
    summary = Column(Text, nullable=False)
    payload = Column(Text, nullable=True)
    ip = Column(String, nullable=True)


# ------------------------------------------------------------------ résumé lisible d'une action
def _s(p, k, default=""):
    v = p.get(k) if isinstance(p, dict) else None
    return default if v is None else v


def summarize(path: str, payload) -> str:
    name = path.rsplit("/", 1)[-1]
    p = payload if isinstance(payload, dict) else {}
    who = _s(p, "pseudo") or _s(p, "grant_to_pseudo")
    try:
        if name == "grant-credits": return "%+d crédits à %s" % (int(_s(p, "amount", 0)), who)
        if name == "grant-packs": return "%s pack(s) %s à %s" % (_s(p, "count", 1), _s(p, "pack_type", "classique"), who)
        if name == "delete-user": return "Suppression du compte %s" % who
        if name == "set-test-account": return "Compte de test %s : %s" % (who, "oui" if p.get("is_test", True) else "non")
        if name == "reset-missions": return "Missions et série remises à zéro pour %s" % who
        if name == "create-card": return "Carte %s (%s) créée%s" % (_s(p, "player_name"), _s(p, "tier"), " et offerte à " + who if who else "")
        if name == "delete-card": return "Carte %s (%s) supprimée" % (_s(p, "player_name"), _s(p, "tier"))
        if name == "create-player": return "Joueur %s créé (poste %s)%s" % (_s(p, "name"), _s(p, "poste", "X"), ", cartes offertes à " + who if who else "")
        if name == "delete-player": return "Joueur %s supprimé" % _s(p, "player_name")
        if name == "set-player-info": return "Surnoms / numéros : %d personne(s)%s" % (len(p.get("players") or []), " (aperçu, rien enregistré)" if p.get("dry_run") else "")
        if name == "set-player-photo": return "Photo de %s%s" % (_s(p, "player_name"), " (rareté " + _s(p, "tier") + ")" if _s(p, "tier") else "")
        if name == "set-player-poste": return "Poste de %s : %s" % (_s(p, "player_name"), _s(p, "poste"))
        if name == "define-edition": return "Édition « %s » %s créée (%s → %s)" % (_s(p, "label"), _s(p, "icon"), _s(p, "start"), _s(p, "end"))
        if name == "remove-edition": return "Édition %s supprimée" % _s(p, "edition")
        if name == "set-edition-dates": return "Dates de l'édition %s : %s → %s%s" % (_s(p, "edition"), _s(p, "start", "—"), _s(p, "end", "—"), " (retour aux dates d'origine)" if p.get("reset") else "")
        if name == "create-edition-cards": return "Cartes de l'édition %s : %d joueur(s)%s" % (_s(p, "edition"), len(p.get("players") or []), ", offertes à " + who if who else "")
        if name == "cancel-proposal": return "Défi %s annulé" % str(_s(p, "proposal_id"))[:8]
        if name == "welcome-gift": return "Packs ultra de bienvenue : %s prochains comptes" % _s(p, "remaining")
        if name == "reset-1v1": return "Ménage 1v1 : %s%s" % (_s(p, "scope"), " (aperçu)" if p.get("dry_run", True) else " (EFFACÉ)")
        if name == "run-weekly-specials": return "Cartes spéciales de la semaine%s" % (" (aperçu)" if p.get("dry_run", True) else "")
        if name == "record-match": return "Match enregistré : %s %s-%s" % (_s(p, "opponent"), _s(p, "score_us", 0), _s(p, "score_them", 0))
        if name == "delete-match": return "Match supprimé : %s (%s)" % (_s(p, "opponent"), _s(p, "date"))
        if name == "add-upcoming-match": return "Match à venir : %s (%s)" % (_s(p, "opponent"), _s(p, "date"))
        if name == "delete-upcoming-match": return "Match à venir retiré : %s (%s)" % (_s(p, "opponent"), _s(p, "date"))
        if name == "push-broadcast": return "Notification « %s »%s" % (_s(p, "title"), " à " + who if who else " à tous")
        if name == "tournament-settings": return "Tournoi : %s" % " · ".join(x for x in (("droit d'entrée %s crédits" % p["entry_fee"]) if p.get("entry_fee") is not None else "", ("bonus du club %s crédits" % p["bonus"]) if p.get("bonus") is not None else "") if x)
        if name == "first-steps-reset": return "Premiers pas : récupération de la récompense effacée pour %s" % who
        if name == "club-reset": return "Défi du club : essais et récompenses du jour remis à zéro pour %s" % who
        if name == "tournament-cancel": return "Tournoi du mois annulé (droits d'entrée remboursés)"
        if name == "pass-theme": return "Thème du Pass de %s : %s" % (_s(p, "month"), _s(p, "theme"))
        if name == "pass-grant": return "Pass : %s%s pour %s" % (("+%s points" % p.get("points")) if p.get("points") else "", (", Premium " + ("activé" if p.get("premium") else "retiré")) if p.get("premium") is not None else "", who)
        if name == "pass-club": return "Objectif du club : %s%s" % (("+%s packs" % p.get("packs")) if p.get("packs") else "", (" paliers " + str(p.get("goals"))) if p.get("goals") else "")
        if name == "give-trophies": return "Cartes de trophée (rangs %s, %s) offertes à %s" % (",".join(str(r) for r in p.get("ranks", [1, 2, 3, 4, 5])), p.get("month") or "mois en cours", who)
        if name == "minigame-set": return "Mini-jeu du jour (%s) donné à %s pour test" % (p.get("kind"), who)
        if name == "event": return "Événement lancé : %s (%s h)" % (p.get("kind"), p.get("duration_hours", 48))
        if name == "event-cancel": return "Événement annulé"
        if name == "backup-now": return "Sauvegarde de la base prise à la main"
        if name == "unlock-cosmetics": return "%s pour %s" % ("Tous les cosmétiques (titres, cadres, objets des Pass) débloqués" if p.get("enabled", True) else "Déblocage manuel des cosmétiques retiré", who)
        if name == "chat-delete": return "Message %s du chat supprimé" % _s(p, "id")
        if name == "chat-mute": return "%s rendu muet %s h dans le chat" % (who, _s(p, "hours"))
        if name == "chat-unmute": return "%s peut de nouveau écrire dans le chat" % who
        if name == "prono-bonus": return "Bonus de %s crédits sur la cagnotte d'un pronostic" % _s(p, "bonus")
        if name == "remove-avatar": return "Photo de profil de %s retirée" % who
        if name == "create-mascot": return "Mascotte %s créée" % _s(p, "name", "Le Loup")
        if name == "create-equipment": return "Équipements officiels créés"
    except Exception:
        pass
    return "%s %s" % ("POST", path)


def write_entry(method: str, path: str, status: int, body: bytes, ip: str) -> None:
    """Note une action. Ne lève JAMAIS d'exception."""
    try:
        payload = None
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except Exception:
            payload = None
        raw = (json.dumps(payload, ensure_ascii=False) if payload is not None else (body.decode("utf-8", "replace") if body else ""))[:MAX_PAYLOAD_CHARS]
        db = SessionLocal()
        try:
            db.add(AdminLog(method=method, path=path, status=status, summary=summarize(path, payload), payload=raw, ip=ip))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


class AdminLogMiddleware:
    """Middleware ASGI : lit le corps des commandes d'administration qui modifient quelque chose, le rend intact à la commande,
    puis note le résultat (code de réponse) dans le journal."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "DELETE", "PUT", "PATCH") or not scope["path"].startswith("/admin/"):
            return await self.app(scope, receive, send)
        chunks, more = [], True
        while more:
            msg = await receive()
            if msg["type"] != "http.request":
                break
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        body = b"".join(chunks)
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        status = {"code": 500}

        async def spy(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, replay, spy)
        finally:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            ip = (headers.get("x-forwarded-for") or (scope.get("client") or ["?"])[0]).split(",")[0].strip()
            write_entry(scope["method"], scope["path"], status["code"], body, ip)


@router.get("/admin/log", dependencies=[Depends(require_admin)])
def admin_log(limit: int = 100, q: str = "", db: Session = Depends(get_db)):
    """Les dernières actions d'administration (la plus récente en premier). `q` filtre sur le texte."""
    limit = max(1, min(int(limit), 500))
    query = db.query(AdminLog)
    if q.strip():
        like = "%" + q.strip() + "%"
        query = query.filter(AdminLog.summary.ilike(like) | AdminLog.path.ilike(like) | AdminLog.payload.ilike(like))
    return [{"id": r.id, "at": r.at.isoformat(), "action": r.summary, "result": ("OK" if 200 <= r.status < 300 else "ÉCHEC %d" % r.status), "status": r.status,
             "route": r.path, "payload": r.payload} for r in query.order_by(AdminLog.id.desc()).limit(limit).all()]


# ------------------------------------------------------------------ tableau de bord
def _item(label, value, hint=""):
    return {"label": label, "value": value, "hint": hint}


@router.get("/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats(db: Session = Depends(get_db)):
    """Le tableau de bord : des rubriques de chiffres lisibles (les comptes de test ne comptent pas, sauf mention)."""
    from .main import leaderboard                                    # (import tardif : main importe ce module)
    now = datetime.utcnow(); d1, d7 = now - timedelta(days=1), now - timedelta(days=7)
    real = db.query(User).filter(User.is_test == False)              # noqa: E712
    n_real, n_test = real.count(), db.query(User).filter(User.is_test == True).count()   # noqa: E712
    new1, new7 = real.filter(User.created_at >= d1).count(), real.filter(User.created_at >= d7).count()
    per_day = []
    for k in range(6, -1, -1):
        a = (now - timedelta(days=k)).replace(hour=0, minute=0, second=0, microsecond=0)
        per_day.append("%s : %d" % (a.strftime("%d/%m"), real.filter(User.created_at >= a, User.created_at < a + timedelta(days=1)).count()))
    seen = dict(db.query(sessions.UserSession.user_id, func.max(sessions.UserSession.last_seen)).group_by(sessions.UserSession.user_id).all())
    real_ids = {u.id for u in real.all()}
    act1 = sum(1 for uid, t in seen.items() if uid in real_ids and t and t >= d1); act7 = sum(1 for uid, t in seen.items() if uid in real_ids and t and t >= d7)
    today = game_logic.today_paris().isoformat()
    packs_today = 0
    for row in db.query(missions.UserDaily).filter(missions.UserDaily.day == today).all():
        try:
            packs_today += int(json.loads(row.progress or "{}").get("open_packs", 0))
        except Exception:
            pass
    packs_total = int(db.query(func.coalesce(func.sum(profiles.UserCounter.value), 0)).filter(profiles.UserCounter.key == "open_packs").scalar() or 0)
    duels_total = db.query(Duel).count(); duels1 = db.query(Duel).filter(Duel.created_at >= d1).count(); duels7 = db.query(Duel).filter(Duel.created_at >= d7).count()
    players7 = set()
    for a, b in db.query(Duel.challenger_id, Duel.defender_id).filter(Duel.created_at >= d7).all():
        players7.update((a, b))
    from .offers import BuyOffer, Trade
    trades_total = db.query(Trade).count(); trades7 = db.query(Trade).filter(Trade.created_at >= d7).count()
    traded7 = int(db.query(func.coalesce(func.sum(Trade.price), 0)).filter(Trade.created_at >= d7).scalar() or 0)
    rows = leaderboard(db)
    credits = [r["credits"] for r in rows]
    reserved = sum(duel_engine.reserved_credits(db).values()) if rows else 0
    top = sorted(rows, key=lambda r: -r["credits"])[:5]
    wg = welcome.remaining(db)
    given = int(db.query(func.count()).select_from(profiles.UserCounter).filter(profiles.UserCounter.key == "welcome_gift", profiles.UserCounter.value == 1).scalar() or 0)
    return {"generated_at": now.isoformat(), "sections": [
        {"title": "Joueurs", "items": [_item("Comptes joueurs", n_real, "%d compte(s) de test en plus" % n_test), _item("Nouveaux (24 h)", new1), _item("Nouveaux (7 jours)", new7, " · ".join(per_day)),
                                         _item("Actifs (24 h)", act1, "au moins une visite"), _item("Actifs (7 jours)", act7)]},
        {"title": "Packs et collection", "items": [_item("Packs ouverts aujourd'hui", packs_today, "d'après les missions du jour"), _item("Packs ouverts au total", packs_total, "depuis l'arrivée des succès"),
                                                   _item("Collection moyenne", ("%.1f %%" % (sum(r["completion_pct"] for r in rows) / len(rows))) if rows else "—"), _item("Succès moyens", ("%.1f / %d" % (sum(r["achievements"] for r in rows) / len(rows), rows[0]["achievements_total"])) if rows else "—")]},
        {"title": "Matchs 1v1", "items": [_item("Matchs joués (total)", duels_total), _item("Matchs (24 h)", duels1), _item("Matchs (7 jours)", duels7), _item("Joueurs ayant joué (7 jours)", len(players7)),
                                         _item("Défis ouverts", db.query(MatchProposal).count())]},
        {"title": "Marché", "items": [_item("Annonces en vente", db.query(Listing).count()), _item("Offres d'achat ouvertes", db.query(BuyOffer).count()), _item("Échanges (7 jours)", trades7, "%d au total" % trades_total), _item("Crédits échangés (7 jours)", traded7)]},
        {"title": "Crédits en circulation", "items": [_item("Total (joueurs)", sum(credits), "mises et offres comprises"), _item("Moyenne par joueur", round(statistics.mean(credits), 1) if credits else 0), _item("Médiane", statistics.median(credits) if credits else 0),
                                                       _item("Bloqués (défis, offres)", reserved), _item("Les plus riches", " · ".join("%s %d" % (r["pseudo"], r["credits"]) for r in top) or "—")]},
        {"title": "Accueil", "items": [_item("Packs ultra de bienvenue restants", wg), _item("Packs ultra de bienvenue donnés", given)]},
    ]}
