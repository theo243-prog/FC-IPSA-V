"""
Catalogue du Pass de saison : les thèmes (un par mois, comme les éditions limitées) et les objets décoratifs qui en découlent.

Un THÈME = un nom, un emoji, deux couleurs (+ une d'accent), 12 emojis nommés, 6 titres, et l'édition limitée associée (pour les packs d'édition).
À partir d'un thème, on fabrique automatiquement les 30 objets décoratifs de la piste Premium (un par niveau, donc un par jour, de toutes sortes)
et 3 objets de la piste gratuite. Aucun fichier d'image : tout est dessiné avec des couleurs, des dégradés et des emojis.

Types d'objets : badge (emoji à côté du pseudo), banner (bannière du profil), frame (cadre autour de la photo), name_color (couleur du pseudo),
title (titre sous le pseudo), stickers (emojis du chat), share_bg (fond des images à partager).
"""

THEMES = {
    "halloween": {"name": "Halloween", "emoji": "🎃", "c1": "#1B0B2E", "c2": "#FF8A1F", "accent": "#FF5C00", "edition": "halloween",
                  "emojis": [("🎃", "Citrouille"), ("👻", "Fantôme"), ("🦇", "Chauve-souris"), ("🕷️", "Araignée"), ("🕸️", "Toile"), ("💀", "Crâne"), ("🧙", "Sorcier"), ("🧛", "Vampire"), ("🍬", "Bonbon"), ("🌙", "Pleine lune"), ("⚰️", "Cercueil"), ("🪦", "Pierre tombale")],
                  "titles": ["Chasseur de citrouilles", "Roi des fantômes", "Vampire du terrain", "Sorcier du but", "Gardien du cimetière", "Maître des chauves-souris"]},
    "noel": {"name": "Noël", "emoji": "🎄", "c1": "#7A0A14", "c2": "#1F9D55", "accent": "#FFD54A", "edition": "noel",
             "emojis": [("🎄", "Sapin"), ("🎅", "Père Noël"), ("⛄", "Bonhomme de neige"), ("🎁", "Cadeau"), ("⭐", "Étoile"), ("🔔", "Cloche"), ("🦌", "Renne"), ("❄️", "Flocon"), ("🍪", "Biscuit"), ("🧦", "Chaussette"), ("🕯️", "Bougie"), ("🛷", "Traîneau")],
             "titles": ["Lutin du stade", "Père Noël du foot", "Roi des neiges", "Gardien du sapin", "Maître des cadeaux", "Renne rapide"]},
    "hiver": {"name": "Hiver", "emoji": "❄️", "c1": "#0B2447", "c2": "#6FD3FF", "accent": "#BFEFFF", "edition": None,
              "emojis": [("❄️", "Flocon"), ("⛷️", "Ski"), ("🧣", "Écharpe"), ("☃️", "Bonhomme de neige"), ("🧊", "Glaçon"), ("🌨️", "Neige"), ("🏔️", "Montagne"), ("🥶", "Frisson"), ("☕", "Café chaud"), ("🧤", "Gants"), ("🌬️", "Vent"), ("🏂", "Snowboard")],
              "titles": ["Roi du givre", "Gardien glacé", "Buteur polaire", "Maître des neiges", "Défenseur d'acier", "Esprit d'hiver"]},
    "printemps": {"name": "Printemps", "emoji": "🌸", "c1": "#0F5132", "c2": "#FF8FB8", "accent": "#FFE066", "edition": None,
                  "emojis": [("🌸", "Cerisier"), ("🌷", "Tulipe"), ("🐝", "Abeille"), ("🦋", "Papillon"), ("🌱", "Pousse"), ("☀️", "Soleil"), ("🌈", "Arc-en-ciel"), ("🐣", "Poussin"), ("🌼", "Marguerite"), ("🍀", "Trèfle"), ("🐞", "Coccinelle"), ("🌧️", "Averse")],
                  "titles": ["Jardinier du terrain", "Buteur en fleur", "Roi du printemps", "Gardien fleuri", "Papillon du milieu", "Éclosion de talent"]},
    "ete": {"name": "Été", "emoji": "🏖️", "c1": "#003B6F", "c2": "#FFC93C", "accent": "#FF7A59", "edition": None,
            "emojis": [("🏖️", "Plage"), ("🌴", "Palmier"), ("🍉", "Pastèque"), ("🕶️", "Lunettes"), ("🌊", "Vague"), ("☀️", "Soleil"), ("🍦", "Glace"), ("⛱️", "Parasol"), ("🐚", "Coquillage"), ("🍹", "Cocktail"), ("🦀", "Crabe"), ("🏄", "Surf")],
            "titles": ["Roi de la plage", "Buteur solaire", "Gardien des vagues", "Maître du sable", "Surfeur du milieu", "Légende d'été"]},
    "automne": {"name": "Automne", "emoji": "🍂", "c1": "#3B1D0A", "c2": "#F2994A", "accent": "#FFD27D", "edition": None,
                "emojis": [("🍂", "Feuille"), ("🍁", "Érable"), ("🌰", "Châtaigne"), ("🍄", "Champignon"), ("🍎", "Pomme"), ("🦔", "Hérisson"), ("🌾", "Blé"), ("☔", "Parapluie"), ("🍇", "Raisin"), ("🪵", "Bûche"), ("🦊", "Renard"), ("🍵", "Thé")],
                "titles": ["Roi des feuilles", "Buteur d'automne", "Gardien des bois", "Renard du milieu", "Maître des récoltes", "Défenseur ocre"]},
    "classique": {"name": "Classique", "emoji": "⚽", "c1": "#16112B", "c2": "#E9C46A", "accent": "#FF2FD1", "edition": None,
                  "emojis": [("⚽", "Ballon"), ("🏆", "Trophée"), ("🥅", "But"), ("🧤", "Gants"), ("👟", "Crampons"), ("🎽", "Maillot"), ("🥇", "Médaille d'or"), ("📣", "Mégaphone"), ("🚩", "Corner"), ("🟨", "Carton jaune"), ("⏱️", "Chrono"), ("🔥", "Flamme")],
                  "titles": ["Roi du stade", "Buteur d'élite", "Mur infranchissable", "Chef d'orchestre", "Capitaine de saison", "Légende du club"]},
}
THEME_BY_NAME = {t["name"]: k for k, t in THEMES.items()}
DEFAULT_THEME_BY_MONTH = {1: "hiver", 2: "hiver", 3: "printemps", 4: "printemps", 5: "printemps", 6: "ete", 7: "ete", 8: "ete", 9: "automne", 10: "automne", 11: "halloween", 12: "noel"}
KINDS = ["badge", "banner", "frame", "name_color", "title", "stickers", "share_bg"]
KIND_LABELS = {"badge": "Badge", "banner": "Bannière", "frame": "Cadre", "name_color": "Couleur du pseudo", "title": "Titre", "stickers": "Autocollants", "share_bg": "Fond d'image"}
LEVELS, POINTS_PER_LEVEL = 30, 100
PREMIUM_EXTRAS = {10: {"pack": "rare"}, 15: {"credits": 50}, 20: {"edition_pack": 2}, 25: {"pass_card": True}, 30: {"edition_pack": 3}}
FREE_REWARDS = {1: {"credits": 5}, 4: {"pack": "classique"}, 7: {"credits": 10}, 10: {"free_item": 10}, 13: {"credits": 10}, 16: {"pack": "classique"}, 19: {"credits": 10}, 20: {"free_item": 20},
                23: {"credits": 10}, 26: {"pack": "rare"}, 28: {"pack": "classique"}, 30: {"credits": 10, "free_item": 30}}
CLUB_TIERS = [(500, {"credits": 10}), (1000, {"pack": "classique"}), (1500, {"credits": 20}), (2000, {"pack": "rare"}), (3000, {"pack": "rare", "credits": 30})]


def item_id(theme: str, n) -> str:
    return "pass-%s-%s" % (theme, n)


def _theme_items(theme_id: str) -> dict:
    t = THEMES[theme_id]; c1, c2, ac = t["c1"], t["c2"], t["accent"]; em = t["emojis"]; out = {}
    adjectives = ["ardent", "brillant", "lumineux", "flamboyant", "mystique"]
    def add(n, kind, name, emoji, style):
        out[item_id(theme_id, n)] = {"id": item_id(theme_id, n), "kind": kind, "name": name, "emoji": emoji, "style": style, "theme": theme_id, "level": n}
    for n in range(1, LEVELS + 1):
        kind = KINDS[(n - 1) % 7]; i = (n - 1) // 7; e, en = em[(n - 1) % 12]
        if kind == "badge": add(n, kind, "Badge %s" % en, e, {"emoji": e})
        elif kind == "banner":
            bg = ["linear-gradient(135deg,%s,%s)" % (c1, c2), "linear-gradient(135deg,%s,%s)" % (c2, c1), "radial-gradient(circle at 20%% 20%%,%s,%s 70%%)" % (c2, c1),
                  "repeating-linear-gradient(45deg,%s 0 14px,%s 14px 28px)" % (c1, ac + "55"), "linear-gradient(90deg,%s,%s,%s)" % (c1, ac, c1)][i % 5]
            add(n, kind, "Bannière %s" % en, e, {"bg": bg, "emoji": e})
        elif kind == "frame":
            css = ["box-shadow:0 0 0 3px %s" % c2, "box-shadow:0 0 0 2px %s,0 0 0 5px %s" % (c1, c2), "box-shadow:0 0 0 3px %s,0 0 12px 3px %s" % (ac, ac),
                   "box-shadow:0 0 0 2px %s,0 0 0 4px %s,0 0 0 6px %s" % (c2, c1, ac), "box-shadow:0 0 0 3px #fff,0 0 14px 4px %s" % c2][i % 5]
            add(n, kind, "Cadre %s" % en, e, {"css": css})
        elif kind == "name_color":
            css = ["color:%s" % c2, "color:%s" % ac, "color:#fff;text-shadow:0 0 6px %s" % c2, "background:linear-gradient(90deg,%s,%s);-webkit-background-clip:text;background-clip:text;color:transparent" % (c2, ac),
                   "background:linear-gradient(90deg,%s,%s,%s);-webkit-background-clip:text;background-clip:text;color:transparent" % (ac, "#fff", c2)][i % 5]
            add(n, kind, "Pseudo %s" % adjectives[i % 5], e, {"css": css})
        elif kind == "title": add(n, kind, t["titles"][i % 6], e, {"text": t["titles"][i % 6]})
        elif kind == "stickers":
            pack = [em[(i * 3 + j) % 12][0] for j in range(6)]; add(n, kind, "Autocollants %s n°%d" % (t["name"], i + 1), pack[0], {"emojis": pack})
        else:
            pair = [(c1, c2), (c2, c1), (c1, ac), ("#0B0716", c2), (c1, "#fff")][i % 5]; add(n, kind, "Fond d'image %s" % en, e, {"c1": pair[0], "c2": pair[1]})
    for n, kind, name, e, style in ((10, "badge", "Badge du Pass %s" % t["name"], t["emoji"], {"emoji": t["emoji"]}), (20, "stickers", "Autocollants du Pass %s" % t["name"], t["emoji"], {"emojis": [x[0] for x in em[:6]]}),
                                    (30, "frame", "Cadre du Pass %s" % t["name"], t["emoji"], {"css": "box-shadow:0 0 0 3px %s,0 0 10px 2px %s" % (c2, c2)})):
        out[item_id(theme_id, "f%d" % n)] = {"id": item_id(theme_id, "f%d" % n), "kind": kind, "name": name, "emoji": e, "style": style, "theme": theme_id, "level": n, "free": True}
    return out


ITEMS = {}
for _tid in THEMES:
    ITEMS.update(_theme_items(_tid))
CLUB_STICKER = {"id": "pass-club-stickers", "kind": "stickers", "name": "Autocollants de l'objectif du club", "emoji": "🤝", "style": {"emojis": ["🤝", "🎉", "👏", "💪", "⚽", "🏆"]}, "theme": None}
ITEMS[CLUB_STICKER["id"]] = CLUB_STICKER


def premium_reward(theme_id: str, level: int) -> dict:
    r = {"item": item_id(theme_id, level)}; r.update(PREMIUM_EXTRAS.get(level, {})); return r


def free_reward(theme_id: str, level: int):
    r = dict(FREE_REWARDS.get(level) or {})
    if not r: return None
    if "free_item" in r: r["item"] = item_id(theme_id, "f%d" % r.pop("free_item"))
    return r


def reward_label(r: dict, theme_id: str) -> str:
    parts = []
    if r.get("credits"): parts.append("%d crédits" % r["credits"])
    if r.get("pack"): parts.append("1 pack %s" % r["pack"])
    if r.get("edition_pack"): parts.append("pack d'édition limitée (%d cartes)" % r["edition_pack"])
    if r.get("pass_card"): parts.append("carte exclusive du Pass")
    if r.get("item") and r["item"] in ITEMS: it = ITEMS[r["item"]]; parts.append("%s %s : %s" % (it["emoji"], KIND_LABELS[it["kind"]].lower(), it["name"]))
    return " + ".join(parts)
