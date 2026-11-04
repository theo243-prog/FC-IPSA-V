"""
Cosmétiques de la boutique : 5 pistes (titre, cadre, bannière, couleur du pseudo, badge) de 5 paliers chacune, vendus UNIQUEMENT au shop.

Chaque palier donne un objet unique, au même format que les objets du Pass (pass_catalog.ITEMS les ajoute à son catalogue) : ils s'équipent donc
au même endroit (profil > « 🎨 Titre et cadre ») et s'affichent partout comme les autres. Aucun fichier d'image : couleurs, dégradés et emojis.
Les paliers s'achètent dans l'ordre. Le palier 5 de chaque piste forme l'ensemble « Pigeon » (titre « Pigeon du shop », couleur de pseudo et bannière holographiques).
Ce fichier ne dépend d'aucun autre module (pas d'import circulaire avec pass_catalog).
"""

PRICES = [50, 100, 200, 350, 500]                     # prix des paliers 1 à 5 (crédits), identiques pour toutes les pistes
TRACK_ORDER = ["title", "frame", "banner", "name_color", "badge"]
TRACK_LABELS = {"title": "Titres", "frame": "Cadres de profil", "banner": "Bannières", "name_color": "Couleurs du pseudo", "badge": "Badges"}

HOLO = "#FF6FC4,#FFD36A 18%,#6CFFC4 36%,#6CB6FF 54%,#C46CFF 72%,#FF6FC4 90%"     # les couleurs de la feuille holographique des cartes légendaires

_TRACKS = {
    "title": [
        ("Client fidèle", "🛍️", {"text": "Client fidèle"}),
        ("Habitué de la boutique", "🪙", {"text": "Habitué de la boutique"}),
        ("Gros dépensier", "💰", {"text": "Gros dépensier"}),
        ("Mécène du club", "💎", {"text": "Mécène du club"}),
        ("Pigeon du shop", "🐦", {"text": "Pigeon du shop"}),
    ],
    "frame": [
        ("Cadre Vitrine", "🛍️", {"css": "box-shadow:0 0 0 3px #2EC4B6"}),
        ("Cadre Néon", "💡", {"css": "box-shadow:0 0 0 2px #fff,0 0 10px 3px #00E5FF"}),
        ("Cadre Velours", "🎀", {"css": "box-shadow:0 0 0 3px #8B1E3F,0 0 0 6px #E9C46A"}),
        ("Cadre Platine", "💎", {"css": "box-shadow:0 0 0 2px #E5E4E2,0 0 0 5px #9AA0A6,0 0 14px 4px #E5E4E2"}),
        ("Cadre du Pigeon", "🐦", {"css": "box-shadow:0 0 0 3px #fff,0 0 0 6px #C46CFF,0 0 16px 5px #6CB6FF;animation:shopHoloRing 3s linear infinite"}),
    ],
    "banner": [
        ("Bannière Vitrine", "🛍️", {"bg": "linear-gradient(135deg,#0F4C5C,#2EC4B6)", "emoji": "🛍️"}),
        ("Bannière Néon", "💡", {"bg": "linear-gradient(135deg,#0B0716,#7B2FF7 60%,#00E5FF)", "emoji": "💡"}),
        ("Bannière Velours", "🎀", {"bg": "radial-gradient(circle at 30% 20%,#B23A48,#3D0C1E 70%)", "emoji": "🎀"}),
        ("Bannière Platine", "💎", {"bg": "linear-gradient(120deg,#5F6368,#C9CCCF 40%,#8A9096 60%,#E5E4E2)", "emoji": "💎"}),
        ("Bannière holographique du Pigeon", "🐦", {"bg": "linear-gradient(rgba(0,0,0,.18),rgba(0,0,0,.18)),linear-gradient(125deg,%s)" % HOLO, "emoji": "🐦", "holo": True}),
    ],
    "name_color": [
        ("Pseudo turquoise", "🛍️", {"css": "color:#2EC4B6"}),
        ("Pseudo néon", "💡", {"css": "color:#fff;text-shadow:0 0 6px #00E5FF,0 0 12px #00E5FF"}),
        ("Pseudo velours", "🎀", {"css": "color:#E9C46A;text-shadow:0 1px 0 #8B1E3F"}),
        ("Pseudo platine", "💎", {"css": "background:linear-gradient(90deg,#8A9096,#F5F5F5,#8A9096);-webkit-background-clip:text;background-clip:text;color:transparent;text-shadow:none;filter:drop-shadow(0 1px 1px rgba(0,0,0,.6))"}),
        ("Pseudo holographique", "🐦", {"css": "background:linear-gradient(90deg,%s);background-size:300%% 100%%;-webkit-background-clip:text;background-clip:text;color:transparent;text-shadow:none;filter:drop-shadow(0 1px 1px rgba(0,0,0,.6));animation:shopHoloText 4s linear infinite" % HOLO, "holo": True}),
    ],
    "badge": [
        ("Badge Sac de shopping", "🛍️", {"emoji": "🛍️"}),
        ("Badge Pièce d'or", "🪙", {"emoji": "🪙"}),
        ("Badge Sac de crédits", "💰", {"emoji": "💰"}),
        ("Badge Diamant", "💎", {"emoji": "💎"}),
        ("Badge Pigeon", "🐦", {"emoji": "🐦"}),
    ],
}


def shop_item_id(kind: str, level: int) -> str:
    return "shop-%s-%d" % (kind, level)


SHOP_ITEMS = {}
for _kind in TRACK_ORDER:
    for _i, (_name, _emoji, _style) in enumerate(_TRACKS[_kind]):
        _id = shop_item_id(_kind, _i + 1)
        SHOP_ITEMS[_id] = {"id": _id, "kind": _kind, "name": _name, "emoji": _emoji, "style": _style, "theme": None, "shop": True, "level": _i + 1, "price": PRICES[_i]}
