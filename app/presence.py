"""
Joueurs connectés (branche joueurs-connectes, 22/11/2026) : le nombre de joueurs qui ont le site ouvert, et le nombre de joueurs sur la page
du draft, affichés en point vert sur les onglets « Matchs 1v1 » et « Draft ».

- Le site appelle /me toutes les 30 s (signe de vie « site ») ; la page draft appelle GET /draft toutes les 4 s et une partie en cours
  GET /draft/{id} chaque seconde (signe de vie « draft »). Un joueur compte s'il s'est manifesté depuis moins de SITE_WINDOW (2 min) ou
  DRAFT_WINDOW (30 s).
- Gardé en MÉMOIRE du serveur (pas de table, aucune écriture en base) : après un redémarrage, le compte repart de zéro le temps que les
  pages ouvertes se manifestent. Comptes de test exclus. Seulement des nombres, jamais de pseudo.
"""
import threading
from datetime import datetime, timedelta

SITE_WINDOW = timedelta(minutes=2)
DRAFT_WINDOW = timedelta(seconds=30)
_lock = threading.Lock()
_seen = {"site": {}, "draft": {}}          # {lieu: {user_id: dernière fois}}
_now = datetime.utcnow                     # (remplaçable dans les tests)


def mark(user, where: str = "site") -> None:
    """Signe de vie d'un joueur (ignoré pour un compte de test). Ne lève jamais d'exception."""
    try:
        if user is None or getattr(user, "is_test", False):
            return
        now = _now()
        with _lock:
            _seen[where][user.id] = now
            if where == "draft":
                _seen["site"][user.id] = now          # sur la page draft = sur le site
    except Exception:
        pass


def counts() -> dict:
    """{"site": joueurs sur le site, "draft": joueurs sur la page draft} ; les anciens signes de vie sont oubliés au passage."""
    now = _now()
    out = {}
    with _lock:
        for where, window in (("site", SITE_WINDOW), ("draft", DRAFT_WINDOW)):
            d = _seen[where]
            for uid in [u for u, t in d.items() if now - t > window]:
                del d[uid]
            out[where] = len(d)
    return out


def reset() -> None:
    with _lock:
        for d in _seen.values():
            d.clear()
