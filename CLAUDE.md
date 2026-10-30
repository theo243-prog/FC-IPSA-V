# FC IPSA V — jeu de cartes à collectionner du club

Site web (PWA) où les membres du club ouvrent des packs de cartes des vrais joueurs, complètent leur collection, échangent au marché et s'affrontent en matchs 1v1 simulés. Tout le code, les commentaires et les messages sont en français.

## Règles de travail

- **Réponds en français, de façon directe.**
- **Version** : à chaque changement visible, monte la version dans `app/version.py` (`VERSION`) **et** dans `SITE_VERSION` de `frontend/index.html`, avec **le même numéro** (format `AAAA.MM.JJ.N`, ex. `2026.10.19.3`). Le pied de page du site compare les deux.
- **Ne modifie jamais `app/seed_data.py`** (il efface toute la base).
- **Avant chaque proposition d'envoi (commit / push), lance `.venv/Scripts/python.exe tests/run_tests.py`** et ne propose l'envoi que si le résultat est « TOUT EST VERT ».
- **Ne touche pas au guide « Commandes site.md »** (dans le dossier : `Commandes site (1).md`, non suivi par git) sauf si je le demande.
- **Aucun secret dans le dépôt : il est public.** Pas de clé admin, d'URL de base avec mot de passe, de clé VAPID ni de sauvegarde `.json.gz`. Les secrets vivent dans les variables d'environnement de Railway.

## Décisions de jeu (à respecter, ne pas « corriger »)
- Prix boutique : classique 50, rare 100, épique 300, légendaire 500, ultra 500 crédits.
- Pass de saison : 30 niveaux de 100 points ; le niveau N s'ouvre le jour N du mois ; Premium 300 crédits ; acheter le niveau suivant 20 crédits ; dernière semaine du mois = points ×2 ; rattrapage 7 jours ; une étoile permanente par Pass terminé.
- Pass, « Récupérer tout » : un bouton en haut de la fenêtre du Pass récupère d'un coup toutes les récompenses débloquées et pas encore prises du Pass affiché (gratuites, Premium si acheté, paliers du club), avec un seul récapitulatif. Route `POST /pass/claim-all {season?}` (vide : le Pass du mois et, pendant le rattrapage, le précédent). Tout ou rien : si une récompense échoue, aucune n'est versée. Les récompenses passent par la même fonction que « Récupérer » (`battlepass._claim_one`).
- Packs match : 5 par jour au maximum et par joueur (MATCH_PACK_DAILY_CAP dans duel_engine.py) ; au-delà, un pack classique, qu'on gagne ou qu'on perde.
- Parrainage : un pack ultra pour le parrain et le filleul ; 3 filleuls maximum par code (referral.py).
- Mini-jeu du jour : 5 questions (quiz) ou 5 tirs au but (but à 6 zones, probabilité d'arrêt réglée côté serveur) ; 10 points de Pass par bonne réponse ou but, 50 au maximum ; il remplace l'ancien défi quotidien « marché ».
- Enchères : cartes rares ou mieux, durée de 15 min à 24 h choisie par le vendeur, enchère suivante +5 % au moins, prolongation de 2 min si enchère dans les 2 dernières minutes.
- Événements éphémères (promo boutique, Pass ×2, pack gratuit par jour) pilotés depuis la page d'administration.
- Sauvegarde automatique de la base chaque jour dès 4 h ; export depuis l'administration.
- Photos des joueurs : fichiers dans frontend/photos/, chemin enregistré sous la forme /photos/nom.ext ; photo par rareté : nom-rareté.ext.
- Sons d'ouverture de packs : un son par thème de Pass (objet de type « sound », « Son d'ouverture <Thème> »), fichier `frontend/sounds/<id du thème>.mp3`, au niveau 18 de la piste Premium à partir du Pass de novembre 2026 (`pass_catalog.SOUND_LEVEL`, `SOUND_FROM`) ; octobre 2026 garde sa couleur de pseudo au niveau 18. Le choix est enregistré sur le compte (table `pass_sound`, route `POST /pass/sound`, renvoyé par `/me` dans `open_sound`). Le site charge seulement le son choisi et joue le hurlement du loup (`sounds/loup.mp3`, sinon un son fabriqué) si le fichier manque ; le bouton 🔊/🔇 coupe tout. Le code ne dépend jamais de la présence des fichiers de sons. Ne pas modifier `pass_catalog.CYCLE` : les objets déjà réclamés en dépendent.
- Tests : dossier tests/, lancer `python tests/run_tests.py` avant tout envoi.
- Idée en attente de ma décision : un défi permanent « Affronter l'équipe du club ».

## Défi du club (`app/club.py`)
- Défi permanent contre une équipe fictive du club (pas un compte joueur), jamais mélangé aux défis 1v1 proposés par les joueurs. Panneau « 🏟️ Défi du club » dans l'onglet 1v1.
- 3 niveaux, chacun avec son équipe : Facile (communes et rares), Normal (rares et épiques), Difficile (légendaires et éditions limitées). Jamais de carte secrète, de trophée, ni d'édition pas encore commencée.
- Équipe du jour (jour de Paris) : formation (2-1-1, 1-2-1 ou 1-1-2), tactique et capitaine tirés au hasard, 5 vrais joueurs (`card_kind == "joueur"`) aux postes de la formation, sans doublon. Elle est créée au premier accès et enregistrée (`club_teams`, une ligne par jour et par niveau) : la même pour tous toute la journée. Repli : rareté la plus proche des raretés principales du niveau (éditions exclues du calcul), puis n'importe quelle carte du poste ; sans joueur du poste, un joueur sans poste précis (X), puis n'importe lequel.
- Le club n'utilise que des cartes qui existent dans le jeu, jamais de carte inventée : sans légendaire, le Difficile aligne les meilleures cartes existantes en dessous (épique, puis spéciale…).
- La tactique du club est secrète : `GET /club` ne l'envoie pas (seuls l'admin et le récit d'un match la montrent). Le joueur la cherche avec ses 3 essais.
- Le club a un capitaine tiré au hasard (+10 %). Au niveau Difficile, il a un bonus d'équipe de +15 % (`LEVELS["difficile"]["bonus"]`, passé au moteur par `team_bonus` dans `tournament.simulate`), réglé par simulation : une équipe de légendaires doit gagner environ 35 à 50 % de ses matchs.
- Match : `tournament.simulate` (ni mise, ni arbitre), tirs au but en cas d'égalité. 3 essais par niveau, par jour et par joueur.
- Récompense : uniquement la première victoire du jour de chaque niveau : 5 / 10 / 15 crédits et 10 / 20 / 30 points de Pass (source « club », plafond 60 par jour, doublements habituels). Rejouer reste possible sans gain.
- Aucun effet sur l'Elo, les statistiques et l'historique 1v1, les packs match, les missions du jour ni les points de Pass « duel ».
- Chaque match est enregistré (`club_matches`). Palmarès « Tombeurs du club » : victoires Difficile, puis Normal, puis Facile (top 10, sans les comptes de test). Titre « Tombeur du club » à 10 victoires au niveau Difficile (compteur `club_hard_wins`).
- Admin : `GET /admin/club` (équipes du jour), `POST /admin/club-reset {pseudo}` (rend les essais et la récompense du jour ; les matchs restent au palmarès).
- Cartes les plus utilisées : la table `card_usage` note les cartes alignées au tournoi (les deux équipes, match réellement joué, pas un forfait) et au défi du club (l'équipe du joueur seulement, jamais celle du club). Elle compte dans `/duel/card-stats` (semaine et total) et dans `weekly.window_stats` / `window_tiers`, donc **aussi dans l'attribution des cartes spéciales du vendredi**. Seule l'utilisation compte, pas les buts ni les passes. Les matchs de tournoi joués avant cette fonctionnalité ne sont pas comptés.

## Premiers pas (`app/first_steps.py`)
- 5 objectifs pour les nouveaux joueurs, dans cet ordre : ouvrir un pack, ajouter une photo de profil, jouer un match 1v1 (créateur ou joueur du défi ; ni le défi du club, ni le tournoi), écrire un message de joueur dans le chat (pas une annonce automatique), récupérer une mission du jour (pas la série ni le bonus).
- Indicateurs durables, qui ne se décochent jamais : compteurs à vie de `user_counters` (`open_packs`, `avatar_set`, `chat_messages`, `missions_claimed`) et la table des duels. Pour les comptes qui ont mis une photo ou écrit avant ces compteurs, une photo en place ou un message de joueur encore dans le salon comptent aussi.
- Récompense quand les 5 sont faits, sur appui de « Récupérer » : +20 crédits et 1 pack classique, une seule fois par compte (table `first_steps_claims`, avec la date). Pas de récompense par objectif.
- Visible seulement pour les comptes créés depuis moins de 14 jours, tant que la récompense n'est pas récupérée.
- Routes : `GET /first-steps` (`{"visible": false}` si le compte n'y a pas droit), `POST /first-steps/claim`, admin `POST /admin/first-steps-reset {pseudo}` (efface la récupération ; un compte de plus de 14 jours reste invisible).
- Site : carte « 🚀 Premiers pas · n/5 » au-dessus des missions de l'onglet Packs ; chaque objectif non fait mène au bon endroit.

## Mot de passe oublié
- Les comptes n'ont pas d'e-mail : c'est l'administrateur qui donne un nouveau mot de passe, avec `POST /admin/set-password {pseudo, new_password}` (4 à 72 caractères, pseudo exact). Formulaire dans l'onglet Comptes de la page d'administration.
- Le compte garde tout ; tous ses appareils sont déconnectés (sessions supprimées).
- Le journal de l'administration ne doit jamais contenir de mot de passe : `admin_tools.SECRET_FIELDS` masque `new_password` et `password` (« (masqué) »). Toute nouvelle commande qui reçoit un secret doit utiliser un de ces noms de champ.

## Lancer en local

Environnement : `.venv` (Python 3.13, créé avec `uv`), exclu de git via `.git/info/exclude`.

```bash
uv pip install --python .venv/Scripts/python.exe -r requirements.txt pytest httpx tzdata
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

- Sans `DATABASE_URL`, l'API utilise un fichier SQLite `fc_format_a5.db` créé dans le dossier courant.
- `tzdata` n'est nécessaire que sous Windows (`zoneinfo` « Europe/Paris ») ; il n'est pas dans `requirements.txt`.
- Documentation interactive : http://127.0.0.1:8000/docs ; administration : `/admin-panel`.

## Tests

```bash
.venv/Scripts/python.exe tests/run_tests.py
```

- **À lancer avant chaque proposition d'envoi.** Pour une seule suite : `.venv/Scripts/python.exe tests/run_tests.py test_pass`.
- Le lanceur exécute les suites `test_pass`, `test_social2`, `test_tournament`, `test_duel_packs`, `test_backup`, `test_features2`, `test_club`, `test_first_steps`, `test_admin_password` et `test_smoke_routes`. Chacune tourne sur une base SQLite temporaire, remplie par `tests/seed_test_data.py` (joueurs fictifs, à ne pas confondre avec `app/seed_data.py`). La vraie base n'est jamais touchée.
- Résultat attendu : « TOUT EST VERT ». `test_smoke_routes` affiche « 0 vérifications » : c'est normal, car il n'imprime pas de lignes « OK ». Il appelle toutes les routes GET et échoue seulement en cas d'erreur 500.
- `tests/ui_*.js` et `tests/prep_*_ui.py` servent aux tests d'interface, voir `tests/LISEZMOI.md`.
- Pour les tests, `minigame.RNG` peut être remplacé et `FC_FAKE_NOW` simule la date.

## Architecture

- **Backend** : FastAPI + SQLAlchemy 2 (`app/`), déployé sur Railway (PostgreSQL en production). Point d'entrée : `app/main.py`, qui contient les routes principales (auth, packs, collection, marché, 1v1, shop, classement, `/admin/*`) et inclut les routeurs des autres modules.
- **Frontend** : un seul fichier `frontend/index.html` (HTML/CSS/JS sans framework), qui appelle l'API via `API_BASE` (URL Railway). Il comprend aussi `sw.js` (service worker, notifications push uniquement, aucun cache), `manifest.webmanifest`, `icons/` et `photos/` (photos `.webp` des joueurs, référencées par `/photos/xxx.webp`).
- **Base** : `Base.metadata.create_all` au démarrage. Les colonnes ajoutées après coup se déclarent dans `app/schema_upgrades.py` (`NEW_COLUMNS`, `NEW_TIER_VALUES` pour l'énumération PostgreSQL des raretés). Les fichiers `migrate_*.py` sont d'anciennes migrations ponctuelles.
- **Tâches de fond** : boucle toutes les 60 s dans `main._background_tick` (cartes spéciales du vendredi, enchères, sauvegarde quotidienne, Pass, tournoi, saisons, notifications). Une erreur dans une tâche est ignorée et ne fait jamais tomber le site.
- **Auth** : pseudo + mot de passe (bcrypt), jeton aléatoire en `Authorization: Bearer`, plusieurs sessions par compte (`sessions.py`). Les routes admin exigent l'en-tête `X-Admin-Key` égal à la variable `ADMIN_KEY`, et chaque action admin qui modifie quelque chose est journalisée (`admin_tools.py`).

### Modules (`app/`)

| Module | Rôle |
|---|---|
| `models.py` | Tables principales : Player, Card (rareté `Tier`), User, OwnedCard, PackState, Match, Duel, MatchProposal, Listing… |
| `game_logic.py` | Règles : packs et probabilités, raretés (`TIER_ORDER`), éditions limitées (halloween, noel, ed1–ed12), notes des cartes, fusion des secrètes, revente des doublons, postes |
| `duel_engine.py` | Matchs 1v1 à 5 : formations, tactiques (pierre-feuille-ciseaux), bonus Fan/Loup/Équipement/arbitre, xG + Poisson, Elo, récit |
| `weekly.py` | Cartes spéciales du vendredi 17 h, conversion heure de Paris |
| `seasons.py`, `tournament.py`, `battlepass.py` + `pass_catalog.py` | Saisons mensuelles d'Elo et trophées, tournoi mensuel, Pass de saison |
| `missions.py`, `profiles.py`, `cosmetics.py`, `avatars.py` | Missions du jour et séries, succès et vitrine, titres et cadres, photos de profil |
| `offers.py`, `auctions.py`, `swaps.py`, `collection_tools.py` | Offres d'achat, enchères, échanges de cartes, vente des doublons en bloc |
| `challenges.py`, `chat.py`, `prono.py`, `events.py`, `referral.py`, `welcome.py`, `minigame.py` | Défis privés, chat, pronostics, événements, parrainage, accueil, mini-jeu |
| `push.py` | Web Push (VAPID, clés générées puis stockées en base), file `push_outbox` |
| `backup.py`, `restore_backup.py` | Instantanés quotidiens en base, export, restauration dans une base vide |
| `admin_page.py`, `admin_tools.py` | Page `/admin-panel` (HTML intégré), `/version`, journal et tableau de bord |
| `seed_data.py` | **Ne pas modifier** : remise à zéro initiale de la base |

### Variables d'environnement

`DATABASE_URL`, `ADMIN_KEY`, `VAPID_SUBJECT`, `PUSH_ALLOW_ANY_ENDPOINT`, `WELCOME_ULTRA_GIFTS`, `FC_FAKE_NOW` (tests).

## Conventions

- Garder le style existant : commentaires en français en bout de ligne, messages d'erreur `HTTPException` en français destinés aux joueurs.
- Une carte non débloquée ne doit jamais révéler son nom au navigateur (`locked_out` dans `main.py`) : même règle pour toute nouvelle route publique.
- Une nouvelle colonne sur une table existante va dans `schema_upgrades.NEW_COLUMNS` (pas de migration manuelle). Une nouvelle rareté va dans `Tier` **et** dans `NEW_TIER_VALUES`.
- Les nouvelles commandes admin sont ajoutées aussi dans `admin_page.py` (tableau `A`) et dans `admin_tools.summarize`.
- La suppression d'un compte (`/admin/delete-user`) doit nettoyer les tables de tout nouveau module lié à un utilisateur (fonctions `on_user_deleted`).
