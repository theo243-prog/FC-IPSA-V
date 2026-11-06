# FC IPSA V — jeu de cartes à collectionner du club

Site web (PWA) où les membres du club ouvrent des packs de cartes des vrais joueurs, complètent leur collection, échangent au marché et s'affrontent en matchs 1v1 simulés. Tout le code, les commentaires et les messages sont en français.

## Règles de travail

- **Réponds en français, de façon directe.**
- **Version** : à chaque changement visible, monte la version dans `app/version.py` (`VERSION`) **et** dans `SITE_VERSION` de `frontend/index.html`, avec **le même numéro** (format `AAAA.MM.JJ.N`, ex. `2026.10.19.3`). Le pied de page du site compare les deux.
- **Ne modifie jamais `app/seed_data.py`** (il efface toute la base).
- **Avant chaque proposition d'envoi (commit / push), lance `.venv/Scripts/python.exe tests/run_tests.py`** et ne propose l'envoi que si le résultat est « TOUT EST VERT ».
- **Ne touche pas au guide « Commandes site.md »** (dans le dossier : `Commandes site (1).md`, non suivi par git) sauf si je le demande.
- **Aucun secret dans le dépôt : il est public.** Pas de clé admin, d'URL de base avec mot de passe, de clé VAPID ni de sauvegarde `.json.gz`. Les secrets vivent dans les variables d'environnement de Railway.

## Façon de travailler (décidée avec moi)
- Une fonctionnalité = une branche dédiée (ex. `defi-du-club`, `premiers-pas`). Si je le demande, présenter d'abord un plan court et attendre mon accord avant de modifier le code.
- Avant de fusionner : tests verts, vérification dans le navigateur intégré, puis rapport (fichiers modifiés, ce qui est vérifié ou non, effets de bord). Ne fusionner dans `main` qu'après mon accord ; ensuite relancer les tests sur `main` et pousser.
- Avant toute fusion ou envoi, récupérer d'abord ce qui a changé sur GitHub (j'y ajoute parfois des photos et des sons directement).
- Ne JAMAIS envoyer une modification de `API_BASE` dans `frontend/index.html`. Pour tester en local, servir une copie temporaire du site (hors du dépôt) dont l'adresse de l'API pointe vers le serveur local, avec une base SQLite jetable et des comptes de test.
- Ne pas créer de fichiers audio ou image soi-même : seulement le code.

## Décisions de jeu (à respecter, ne pas « corriger »)
- Prix boutique : classique 50, rare 100, épique 300, légendaire 500, ultra 500 crédits.
- Pass de saison : 30 niveaux de 100 points ; le niveau N s'ouvre le jour N du mois ; Premium 300 crédits ; acheter le niveau suivant 20 crédits ; dernière semaine du mois = points ×2 ; rattrapage 7 jours ; une étoile permanente par Pass terminé.
- Pass, « Récupérer tout » : un bouton en haut de la fenêtre du Pass récupère d'un coup toutes les récompenses débloquées et pas encore prises du Pass affiché (gratuites, Premium si acheté, paliers du club), avec un seul récapitulatif. Route `POST /pass/claim-all {season?}` (vide : le Pass du mois et, pendant le rattrapage, le précédent). Tout ou rien : si une récompense échoue, aucune n'est versée. Les récompenses passent par la même fonction que « Récupérer » (`battlepass._claim_one`).
- Packs gagnés en 1v1 : **10 par jour au maximum et par joueur**, tous types confondus : un pack match si on gagne, un classique si on perd ou fait nul (il n'y a plus de limite séparée de 5 packs match). `DUEL_PACK_DAILY_CAP` dans duel_engine.py, compteur du jour `duel_packs` de `missions.daily_count`, remis à zéro à minuit heure de Paris. Au-delà, le match se joue normalement (mises, Elo, missions) et rapporte **1 à 5 crédits au hasard** (`AFTER_CAP_CREDITS`, sans limite) à la place du pack, à chacun des deux joueurs, pour ne pas distribuer trop de cartes ; le résultat l'indique dans `pack_none_to` et `credits_instead`. Le compteur n'existe que depuis cette règle : les packs déjà gagnés le jour de sa mise en ligne ne sont pas comptés.
- Parrainage : un pack ultra pour le parrain et le filleul ; 3 filleuls maximum par code (referral.py).
- Mini-jeu du jour : 5 questions (quiz) ou 5 tirs au but (but à 6 zones, probabilité d'arrêt réglée côté serveur) ; 10 points de Pass par bonne réponse ou but, 50 au maximum ; il remplace l'ancien défi quotidien « marché ».
- Enchères : cartes rares ou mieux, durée de 15 min à 24 h choisie par le vendeur, enchère suivante +5 % au moins, prolongation de 2 min si enchère dans les 2 dernières minutes.
- Événements éphémères (promo boutique, Pass ×2, pack gratuit par jour) pilotés depuis la page d'administration.
- Sauvegarde automatique de la base chaque jour dès 4 h ; export depuis l'administration.
- Photos des joueurs : fichiers dans frontend/photos/, chemin enregistré sous la forme /photos/nom.ext ; photo par rareté : nom-rareté.ext.
- Sons d'ouverture de packs : un son par thème de Pass (objet de type « sound », « Son d'ouverture <Thème> »), fichier `frontend/sounds/<id du thème>.mp3`, au niveau 18 de la piste Premium à partir du Pass de novembre 2026 (`pass_catalog.SOUND_LEVEL`, `SOUND_FROM`) ; octobre 2026 garde sa couleur de pseudo au niveau 18. Le choix est enregistré sur le compte (table `pass_sound`, route `POST /pass/sound`, renvoyé par `/me` dans `open_sound`). Le site charge seulement le son choisi et joue le hurlement du loup (`sounds/loup.mp3`, sinon un son fabriqué) si le fichier manque ; le bouton 🔊/🔇 coupe tout. Le code ne dépend jamais de la présence des fichiers de sons. Ne pas modifier `pass_catalog.CYCLE` : les objets déjà réclamés en dépendent.
- Cosmétiques du shop (`shop_catalog.py`, `shop_cosmetics.py`) : 5 pistes (titre, cadre, bannière, couleur du pseudo, badge) de 5 paliers à 50 / 100 / 200 / 350 / 500 crédits, achetés dans l'ordre, vendus uniquement au shop (jamais dans le Pass), prix fixes (les promotions ne touchent que les packs). Le palier 5 forme l'ensemble « Pigeon » : titre « Pigeon du shop », couleur du pseudo et bannière holographiques (couleurs des cartes légendaires). Ils s'ajoutent à `pass_catalog.ITEMS` (identifiants `shop-<piste>-<palier>`) et s'équipent comme les objets du Pass. Admin : `GET /admin/shop-cosmetics` (ventes), `POST /admin/shop-cosmetics-refund {pseudo, item_id}` (palier le plus haut d'une piste seulement).
- Annonces automatiques du chat : un compte peut avoir ses annonces coupées (compte d'administration) avec `POST /admin/chat-silent {pseudo, enabled}` (compteur `chat_silent` de `user_counters`). `chat.add_event` ne publie alors rien à son nom (succès, légendaire, Pass, enchères, échanges via `also`…) ; ses messages écrits à la main restent publiés.
- Cartes spéciales du vendredi 17 h (`weekly.py`) : « la plus utilisée » a **un gagnant par groupe de rareté** (`weekly.RARITY_GROUPS` : commune, rare, épique, légendaire, édition limitée = halloween + noel + ed1–ed12 ensemble) ; gold, secrète, spéciale et trophée de saison sont ignorées. Un groupe ne compte que ses propres cartes (1v1, tournoi, défi du club) ; groupe sans utilisation : pas de carte. Meilleur buteur et meilleur passeur : un seul gagnant chacun, toutes raretés confondues. Départage : le plus utilisé, puis l'ordre alphabétique. +1 par victoire (un joueur n°1 de deux groupes gagne +2). Au plus 7 cartes spéciales par semaine. `/duel/card-stats?scope=week` renvoie `most_used_groups` (le classement de tous les temps garde `most_used`).
- Notes : les éditions limitées (halloween, noel, ed1–ed12) valent 85, comme la rare. Leur bonus de Fan et de mascotte (Loup) est de **+8 %** (`TIER_FAN_BONUS` / `TIER_MASCOT_BONUS`, aussi pour ed1–ed12). Les anciens matchs ne sont pas recalculés.
- Chances des packs (`game_logic.py`) : gold fréquent, éditions limitées rares. Pendant une édition en cours, par carte tirée : pack classique gold 8 %, édition 3,5 % ; pack match gold 10 %, édition 6 % (`EDITION_SHARE` = 0,035 / 0,06). Poids de départ (total 100) : classique `TIER_WEIGHTS` commune 71,21, rare 18, gold 8,29 (= 8 / 0,965), épique 2, légendaire 0,5 ; match commune 46,36, rare 30, gold 10,64 (= 10 / 0,94), spéciale 8, épique 4, légendaire 1. La commune absorbe la différence. Pack ultra : structure inchangée, sa case « gold, édition limitée ou mieux » tire parmi gold, édition, épique et légendaire avec ces poids (édition ≈ 25 % de cette case pendant une édition). Vérifié par `tests/test_pack_odds.py`.
- Cartes gold sans match : `POST /admin/create-gold {moments: [{player_name, action}], date?}` (formulaire « Ajouter des cartes gold (sans match) », onglet Matchs réels, une ligne « Joueur ; Action »). Même fonction que les moments d'un match (`main.create_moment_card`) : fiche MOMENT « Action — Joueur » avec la photo du joueur, date ajoutée si le nom existe déjà ; tout ou rien. Collection : une rareté de plus de 40 cartes est repliée par défaut (sauf recherche ou choix du joueur) et résumée dans l'image de partage (4 rangées puis « +N autres »).
- Moteur de match moins aléatoire (`duel_engine.py`) : `XG_EXPONENT` 3,0 (avant 1,5), `FORMATION_SKEW` 0,25 (avant 0,5), `BASE_XG` 3,0, `FIXED_GOALS_SHARE` 0,5. Les buts d'une équipe se tirent avec `draw_goals(xg)` = floor(0,5 × xg) buts acquis + Poisson(le reste) : même moyenne, moins de variance (Poisson pur sous 2 buts attendus). Raison : le niveau des cartes et les choix pèsent davantage sans changer les buts (avec l'exposant 3, le skew 0,25 garde le même effet de formation, r^0,75 : 1,4 / 2,0 / 2,6 buts par équipe en 2-1-1 / 1-2-1 / 1-1-2 à cartes égales, 1,9 en 1-1-2 contre 2-1-1). Résultats : cartes égales ~40 / 20 / 39 ; favori 90 contre 80 ~70 % de victoires (53 % avant), ~14 % de défaites. Utilisé par le 1v1 (`play_proposal`) et `tournament.simulate` (tournoi et défi du club) ; les tirs au but ne changent pas. Les tests qui imposent un score remplacent `duel_engine.draw_goals`. Vérifié par `tests/test_engine_variance.py`.
- Classement des pronostiqueurs (`GET /prono/ranking`) : TOUS ceux qui ont pronostiqué, sans limite, avec matchs joués, scores exacts, bons résultats (bon vainqueur ou bon nul), mauvais pronostics et gain net. Un match où tout le monde est remboursé compte en mauvais pronostics ; un match supprimé sans résultat ne compte pas. Ordre : scores exacts, bons résultats, gain net, moins d'erreurs, pseudo.
- Stats des joueurs (onglet Actualité, `/players/stats`) : colonnes cartons jaunes 🟨 et rouges 🟥, en plus de M, ⚽, PD et 🏅.
- Onglet Classement : la bannière (Pass ou shop) s'affiche derrière le nom de chaque joueur, avec la couleur de son pseudo (fond sombre derrière le nom pour rester lisible) ; `/leaderboard` renvoie `banner`.
- Photos des cartes : la photo du joueur remplit toute la carte (voile sombre en bas pour le nom), recadrée sur la partie visible de la photo détourée avec de l'air au-dessus de la tête ; la taille réelle de la carte est mesurée (pas celle à l'écran pendant qu'elle se retourne). Sur les cartes Noël avec photo, la neige du bas passe derrière la photo.
- Prochain match en double (même date, même adversaire) : le retirer par son identifiant (`/matches/upcoming` puis `POST /admin/delete-upcoming-match {upcoming_id}`).
- **Jamais de taxe** (marché, enchères, mises, cagnotte) pour retirer des crédits : seulement des dépenses volontaires.
- Tests : dossier tests/, lancer `python tests/run_tests.py` avant tout envoi.
- Défi permanent « Affronter l'équipe du club » : décidé et réalisé (section « Défi du club » ci-dessous).

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

## Homme du match (`app/motm.py`)
- Ouverture : case « Match officiel : ouvrir le vote » du formulaire « Enregistrer un match joué » (`open_vote` de `/admin/record-match`). Vote ouvert tout de suite pour 24 h exactement. On ne vote que pour les présents de CE match (champ « Joueurs présents », `Match.lineup_json`), vrais joueurs seulement (`card_kind == "joueur"`) ; au moins 3, sinon refus (400) et rien n'est enregistré. Les pronostics sont réglés comme avant, sans lien avec le vote.
- Bulletin : tout compte connecté, un par match, 3 joueurs différents parmi les présents (1er 5 points, 2e 3, 3e 1), places obligatoires, modifiable tant que le vote est ouvert. `POST /motm/{id}/vote` (401 sans compte, 404 vote inconnu ou annulé, 400 vote fermé ou bulletin invalide).
- Secret : pendant le vote, `GET /motm` ne donne ni nom classé ni point (présents, votants, échéance, mon bulletin). À la fermeture : podium (3 premiers avec points) et cartes. Les autres joueurs votés ne sont jamais publiés ; leurs points restent dans `motm_points`. Départage : points, 1res places, 2es, 3es, ordre alphabétique.
- Fermeture : tâche de fond (`motm.tick`) ET premier accès après l'échéance ; appliquée une seule fois (passage atomique du statut `open` à `closing`). Moins de `MIN_BULLETINS` (3) bulletins : clôturé sans résultat ni carte, message « pas assez de votes » dans le chat et ligne dans le journal de l'administration.
- Cartes : on parcourt le classement complet ; chaque joueur qui a déjà sa légendaire gagne +2 de note, jusqu'au premier qui n'en a pas : sa légendaire est créée (carte du jeu, donnée à personne) et on s'arrête. Tous en ont une : tous +2. **Pas de plafond** (une légendaire peut dépasser 99). La note propre d'une légendaire est `card.note` (vide = 95, `CARD_NOTE`), lue par `card_note()` : elle vaut pour tous ses propriétaires. La carte créée prend la photo générale du joueur (ou `nom-legendaire.ext` si elle est reliée).
- Homme du match des statistiques : si le champ « Homme du match » du match est vide, le 1er du vote le devient (`motm_player_id`, `homme_du_match_count`) ; s'il est rempli, il reste.
- Supprimer un match dont le vote est ouvert annule ce vote (pas de carte) ; un vote clôturé reste acquis. Il n'y a pas de commande pour corriger un score : supprimer puis ré-enregistrer (recocher la case pour un nouveau vote).
- Annonces chat et notifications : ouverture (« Votez pour l'homme du match, 24 h »), résultat (podium, carte créée, notes +2), « pas assez de votes ».
- Saison des votes (privée) : `POST /admin/motm-season-create {name, starts, ends}` ; chaque vote clôturé avec résultat ajoute les points de TOUS ses joueurs votés à la saison ouverte qui couvre la date de fermeture. `GET /admin/motm-season` (admin seulement, jamais montré aux joueurs), `POST /admin/motm-season-close` (fige le classement, montre à l'admin l'homme de la saison, le 2e et le 3e ; aucune récompense ni annonce), `POST /admin/motm-season-publish` (publie le podium dans le chat, sur commande).
- Admin des votes : `GET /admin/motm` (classement complet, même pendant le vote), `POST /admin/motm-extend {vote_id?, hours}`, `/admin/motm-close {vote_id?}`, `/admin/motm-cancel {vote_id?}` (identifiant vide : le vote ouvert s'il n'y en a qu'un).
- Site : panneau « 🏅 Homme du match » de l'onglet Actualité (toucher 3 noms dans l'ordre, valider, modifier ; podium et historique), point rouge `newsDot` quand `/me` renvoie `motm_todo`.

## Niveaux de cartes (`app/card_levels.py`)
- Une copie d'une carte monte de 0 à 5 niveaux (`MAX_LEVEL`) ; chaque niveau = +1 de note en match, ajouté AVANT le malus hors poste et le bonus de capitaine (`duel_engine.build_members(..., levels)`), pour les deux équipes du 1v1, au tournoi et pour l'équipe du joueur au défi du club (jamais pour le club), au moment où le match est joué. La collection renvoie `level` et une `display_note` qui inclut le niveau (`main.with_level`), ce qui fait suivre la composition, la fiche et l'image de partage.
- Éligibles : vrais joueurs en commune, rare ou édition limitée (halloween, noel, ed1–ed12). Refus avec raison pour gold, secrète, épique, légendaire, spéciale, trophée, fan, mascotte, équipement, stade, moment (`ineligible_reason`).
- Pour acheter le niveau n : payer `DUPES_REQUIRED` doublons (quantité - 1), qui sont **consommés** (la copie évoluée reste), au choix du joueur entre niveaux et doublons gardés pour la revente ou les secrètes — commune 5/10/20/50/100, rare 1/3/5/12/25, édition 1/3/5/8/10 — et payer `COSTS` — commune 30/60/120/200/320, rare 45/90/180/300/480, édition 60/120/240/400/640. Au plus `DAILY_UPGRADES` = 2 par jour (jour de Paris, compteur `card_levels` de `missions.daily_count`).
- Tables : `card_levels` (joueur, carte, niveau ; une copie évoluée par carte et par joueur), `listing_levels`, `auction_levels`, `trade_levels` (le niveau d'une annonce, d'une enchère, d'une vente de l'historique).
- Le niveau suit la carte : `copy_leaving` (la copie évoluée part si le vendeur la choisit — `evolved` de `/market/list` et `/auctions` — ou si c'est sa dernière copie ; ses autres copies repassent au niveau 0) et `copy_arriving` (l'acheteur garde son meilleur niveau ; annonce annulée ou enchère sans preneur : la carte revient avec son niveau). Offre d'achat acceptée : copie normale si possible, sinon la dernière (évoluée). Échanges, « vendre mes doublons » et fusion des secrètes ne prennent que des doublons : le niveau reste. Suppression d'une carte ou d'un compte : niveaux supprimés.
- Routes : `GET /cards/{id}/level` (niveau, paliers, « tu en as N sur M », coût, raison), `POST /cards/{id}/evolve`, admin `POST /admin/set-card-level {pseudo, player_name, tier, level}` (sans paiement). Site : badge « Niv. N », bloc « ⬆️ Niveau » dans la fiche d'une de mes cartes, choix « ma carte évoluée / un doublon normal » à la mise en vente, niveau affiché dans les annonces et enchères. Simulation : 5 cartes à 85 niveau 5 contre niveau 0 : ~54 % de victoires, ~22 % de nuls, ~24 % de défaites.

## Forme des cartes en 1v1 (`app/fatigue.py`)
- Chaque carte utilisée dans un match 1v1 (les 5 joueurs, le Fan, le Loup et l'équipement) perd `FORM_LOSS_PER_MATCH` = 1 % de forme, pour les deux équipes du défi, au moment où le match est joué (`fatigue.record_match` dans `play_proposal`). Compté par joueur du site et par carte (table `card_fatigue` : joueur, carte, jour de Paris, matchs du jour) ; une ligne d'un autre jour ne compte plus : **retour à 100 % chaque jour à minuit**, heure de Paris. Plancher `MIN_FORM` = 50 %.
- La forme multiplie la note en 1v1 : (note + niveau) × forme, puis malus hors poste, puis capitaine (`build_members(..., forms)`) ; elle multiplie aussi le bonus d'un Fan, d'un Loup ou d'un équipement (`team_powers(..., forms)`). Le **tournoi et le défi du club** jouent toujours à 100 % et ne fatiguent pas. But : faire tourner les cartes, gardien compris.
- La collection renvoie `form` (en %) pour les cartes possédées ; `/duel/config` renvoie `form_loss_per_match` et `min_form`. Site : barre de forme sous la note d'une carte qui a joué aujourd'hui, note « du moment » dans la composition (1v1 seulement), forme dans le récit, et bouton « ⚡ Meilleure équipe » qui remplit chaque poste avec la meilleure note du moment (cartes du poste, puis la meilleure restante, un poste X n'étant jamais pénalisé) et choisit le capitaine.

## Notifications du site (`app/inbox.py`)
- Encadré « 🔔 Notifications » en haut du site (sous l'en-tête) : les nouvelles notifications (5 au plus), « Tout marquer comme lu », « Historique » (les 30 dernières) ; le bouton 📬 de l'en-tête (point rouge s'il y a du nouveau) ouvre l'historique. Toucher une notification ouvre l'onglet concerné et la marque comme lue.
- Tout message envoyé à UN joueur par `push.enqueue` (défi relevé, défi privé, carte vendue, enchère dépassée / gagnée / terminée, offre acceptée, échange, pronostic, tournoi, parrainage, saison…) est aussi rangé dans la table `user_notices`, même sans téléphone abonné. Pas les rappels de packs (`SKIP_KINDS`) ni les annonces générales (`push.notify_users` / `notify_all` passent `inbox=False`). Au plus `KEEP` = 60 par joueur.
- Routes : `GET /notifications` (`unread`, `items`), `POST /notifications/read {ids}` (vide : toutes). `/me` renvoie `notices_unread`.

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
- Le lanceur exécute les suites `test_pass`, `test_social2`, `test_tournament`, `test_duel_packs`, `test_backup`, `test_features2`, `test_club`, `test_first_steps`, `test_admin_password`, `test_shop_cosmetics`, `test_chat_silent`, `test_weekly_rarity`, `test_motm`, `test_pack_odds`, `test_engine_variance`, `test_card_levels`, `test_fatigue`, `test_inbox` et `test_smoke_routes`. Chacune tourne sur une base SQLite temporaire, remplie par `tests/seed_test_data.py` (joueurs fictifs, à ne pas confondre avec `app/seed_data.py`). La vraie base n'est jamais touchée.
- Résultat attendu : « TOUT EST VERT ». `test_smoke_routes` affiche « 0 vérifications » : c'est normal, car il n'imprime pas de lignes « OK ». Il appelle toutes les routes GET et échoue seulement en cas d'erreur 500.
- `tests/ui_*.js` et `tests/prep_*_ui.py` servent aux tests d'interface, voir `tests/LISEZMOI.md`.
- Pour les tests, `minigame.RNG` peut être remplacé et `FC_FAKE_NOW` simule la date.

## Architecture

- **Backend** : FastAPI + SQLAlchemy 2 (`app/`), déployé sur Railway (PostgreSQL en production). Point d'entrée : `app/main.py`, qui contient les routes principales (auth, packs, collection, marché, 1v1, shop, classement, `/admin/*`) et inclut les routeurs des autres modules.
- **Frontend** : un seul fichier `frontend/index.html` (HTML/CSS/JS sans framework), qui appelle l'API via `API_BASE` (URL Railway). Il comprend aussi `sw.js` (service worker, notifications push uniquement, aucun cache), `manifest.webmanifest`, `icons/`, `photos/` (photos `.webp` des joueurs, référencées par `/photos/xxx.webp`) et `sounds/` (`loup.mp3`, le hurlement par défaut, et les sons d'ouverture `<thème>.mp3`, ajoutés au fil des mois).
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
| `motm.py` | Homme du match : vote 24 h après un match officiel, cartes légendaires ou +2, saison des votes privée |
| `card_levels.py` | Niveaux de cartes : +1 de note par niveau (5 au plus), crédits et doublons consommés, le niveau suit la carte au marché |
| `fatigue.py` | Forme des cartes en 1v1 : -1 % par match, retour à 100 % à minuit, tournoi et défi du club à 100 % |
| `inbox.py` | Notifications du site : encadré en haut de page avec les messages personnels (défis, ventes, enchères…) |
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
