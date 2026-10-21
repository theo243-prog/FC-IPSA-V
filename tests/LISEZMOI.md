# Tests de FC IPSA V

**Pour tout lancer d'un coup (Windows, Mac, Linux)** : `python tests/run_tests.py`  (ou `python tests/run_tests.py test_pass` pour une seule suite).
Chaque suite tourne sur une base jetable, avec les 30 joueurs fictifs de `tests/seed_test_data.py` (à ne pas confondre avec `app/seed_data.py`, qui n'est jamais modifié).
Les fichiers `ui_*.js` et `prep_*.py` sont des tests dans un vrai navigateur (Node.js + Puppeteer) : facultatifs.

# Tests du site FC IPSA V

Ces fichiers ne servent PAS au déploiement (Railway les ignore). Ils permettent de vérifier le site en quelques minutes après une modification.
Ils utilisent une base SQLite jetable : ils ne touchent jamais ta vraie base.

## Tests du serveur (Python)
Depuis le dossier `fc-format-a5-admin-update`, avec un environnement Python qui a les dépendances de `requirements.txt` plus `pillow` et `httpx` :

```
rm -f /tmp/fc_test.db
export ADMIN_KEY=k DATABASE_URL=sqlite:////tmp/fc_test.db PYTHONPATH=. WELCOME_ULTRA_GIFTS=0
python -m app.seed_data                      # 30 joueurs de départ
python tests/test_social2.py                 # titres, chat, échanges de cartes, pronostics
rm -f /tmp/fc_test.db && python -m app.seed_data && python tests/test_smoke_routes.py   # aucune route de consultation ne plante
```
Chaque test se termine par « BILAN … TOUT EST VERT » ou liste ce qui a échoué.

## Tests en vrai navigateur (Node + Chromium)
Il faut `npm i puppeteer-core @sparticuz/chromium` dans un dossier de travail, puis :
1. une base fraîche + `python tests/prep_social2_ui.py` (écrit `/tmp/ctx.json`) ;
2. le serveur : `python -m uvicorn app.main:app --port 8765` ;
3. le site sur `http://localhost:8080` : copie `frontend/index.html`, remplace `https://fc-ipsa-v-production.up.railway.app` par `http://localhost:8765`, retire les deux lignes de polices Google, et sers le dossier (`python -m http.server 8080`) ;
4. `node tests/ui_social2.js` (chat, titres et cadres, pronostics, échanges, mise en page d'Actualité) ou `node tests/ui_smoke.js` (compte neuf : pop-up de bienvenue, tous les onglets, outils de collection, images à partager).

Les captures d'écran sont écrites dans le dossier donné par la variable `SHOTS` (par défaut `/tmp/shots`).

## À savoir
- Un compte tout neuf voit d'abord le pop-up de bienvenue, qui recouvre le site : les tests le marquent comme « vu ».
- `WELCOME_ULTRA_GIFTS=0` désactive le pack ultra offert aux nouveaux comptes pendant les tests.

## Tournoi mensuel
- Serveur : `python tests/test_tournament.py` (horloge simulée dans le test : inscriptions, tirage, exemptés, tirs au but, forfaits, cagnotte, trophée, annulations, beaucoup de joueurs).
- Navigateur : le test fige l'horloge du serveur avec la variable `FC_FAKE_NOW` (réservée aux tests, jamais définie en production). Préparer une base avec `python tests/prep_tournament_ui.py`, lancer le serveur avec `FC_FAKE_NOW=2026-11-03T10:00:00`, puis `node tests/ui_tournament.js A` ; relancer le serveur avec `FC_FAKE_NOW=2026-11-08T13:00:00` et `node tests/ui_tournament.js B`.

## Pass de saison
- Serveur : `python tests/test_pass.py` (30 niveaux, déblocage jour par jour, points et plafonds, doublement de la dernière semaine, Premium, objets, cartes d'édition, étoiles, objectif du club, rattrapage de 7 jours, thèmes).
- Navigateur : `python tests/prep_pass_ui.py` (base propre), serveur avec `FC_FAKE_NOW=2026-11-12T10:00:00` puis `node tests/ui_pass.js A` ; relancer le serveur avec `FC_FAKE_NOW=2026-11-30T10:00:00` puis `node tests/ui_pass.js B`.

## Sauvegarde de la base, packs match
- `python tests/test_backup.py` : export, sauvegarde à la main, instantané quotidien (une fois par jour, 7 gardés), téléchargement, restauration dans une base vide (et refus dans une base non vide).
- `node tests/ui_admin_backup.js` (serveur lancé avec `ADMIN_KEY=k`) : l'onglet « Sauvegardes » de la page d'administration.
- `python tests/test_duel_packs.py` : au plus 5 packs match gagnés par jour en 1v1, un pack classique ensuite, remise à zéro à minuit.
