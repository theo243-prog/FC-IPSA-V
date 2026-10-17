"""
La page d'administration (/admin-panel) et le numéro de version (/version).

La page est servie par l'API elle-même, donc ses boutons parlent directement au serveur, sans réglage. Elle ne contient AUCUN
secret : la clé admin se tape dans la page (champ « clé ») et reste seulement dans l'onglet du navigateur (sessionStorage).
Chaque formulaire envoie exactement la même requête que les commandes de « Commandes site.md ».
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .version import VERSION

router = APIRouter()


@router.get("/version")
def get_version():
    """Le numéro de version du serveur (le site affiche le sien à côté : les deux doivent être identiques)."""
    return {"version": VERSION}


@router.get("/admin-panel", response_class=HTMLResponse)
def admin_panel():
    return HTMLResponse(ADMIN_HTML.replace("__VERSION__", VERSION), headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


ADMIN_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Administration · FC IPSA V</title>
<style>
  :root{--bg:#1B0A28;--panel:#2A1240;--panel2:#331852;--text:#FCE6F2;--muted:#C79ABA;--accent:#F8B4D6;--ok:#6FD79A;--bad:#FF7B86;--line:rgba(252,194,226,.22);}
  *{box-sizing:border-box;} body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
  header{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;}
  header h1{font-size:20px;margin:0;} header .ver{font-size:12px;color:var(--muted);}
  .keybox{display:flex;gap:8px;margin-left:auto;align-items:center;flex-wrap:wrap;} .keybox input[type=password]{width:230px;}
  input,select,textarea,button{font:inherit;color:var(--text);background:#1F0C30;border:1px solid var(--line);border-radius:8px;padding:8px 10px;}
  textarea{width:100%;min-height:84px;resize:vertical;font-family:ui-monospace,Consolas,monospace;font-size:13px;} select,input[type=text],input[type=number],input[type=password],input[type=date]{width:100%;} input[type=color]{width:100%;height:42px;padding:3px;}
  button{cursor:pointer;background:var(--accent);color:#2A0F3D;font-weight:700;border:none;} button.ghost{background:transparent;color:var(--text);border:1px solid var(--line);} button.danger{background:var(--bad);color:#33060B;} button:disabled{opacity:.5;cursor:default;}
  nav{display:flex;gap:6px;flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5;}
  nav button{background:transparent;color:var(--muted);border:1px solid var(--line);} nav button.on{background:var(--accent);color:#2A0F3D;border-color:var(--accent);}
  main{padding:14px 16px 60px;max-width:980px;margin:0 auto;} .locked main{opacity:.4;pointer-events:none;}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:0 0 14px;}
  .card h2{font-size:17px;margin:0 0 4px;} .card p.d{margin:0 0 10px;color:var(--muted);font-size:13px;}
  .fld{margin:0 0 10px;} .fld label{display:block;font-size:12.5px;color:var(--muted);margin:0 0 3px;} .fld.chk label{display:flex;gap:8px;align-items:center;color:var(--text);} .fld.chk input{width:auto;}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:0 12px;} @media(max-width:620px){.row{grid-template-columns:1fr;} .keybox{margin-left:0;width:100%;} .keybox input[type=password]{flex:1;width:auto;}}
  .out{margin-top:10px;font-size:13px;} .out .st{font-weight:800;} .out .st.ok{color:var(--ok);} .out .st.bad{color:var(--bad);}
  pre{background:#14071f;border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;max-height:340px;margin:6px 0 0;white-space:pre-wrap;word-break:break-word;font-size:12.5px;}
  .tw{overflow:auto;max-height:380px;margin-top:6px;border:1px solid var(--line);border-radius:8px;} table{border-collapse:collapse;width:100%;font-size:12.5px;} th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap;} th{position:sticky;top:0;background:var(--panel2);}
  .tab{display:none;} .tab.on{display:block;} .warn{color:var(--bad);font-size:12.5px;}
  .stats-sec{margin:12px 0 4px;font-weight:800;font-size:14px;color:var(--accent);} .stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;}
  .tile{background:#14071f;border:1px solid var(--line);border-radius:10px;padding:10px;} .tile b{display:block;font-size:21px;line-height:1.15;word-break:break-word;} .tile span{font-size:12px;color:var(--muted);} .tile small{display:block;margin-top:3px;font-size:11px;color:var(--muted);line-height:1.3;}
</style>
</head>
<body class="locked">
<header>
  <h1>⚙️ Administration FC IPSA V</h1>
  <span class="ver">Serveur : version <b id="verServer">__VERSION__</b></span>
  <div class="keybox"><input id="key" type="password" placeholder="Clé admin" autocomplete="off"><button id="login">Se connecter</button><span id="loginMsg" class="ver"></span></div>
</header>
<nav id="nav"></nav>
<main id="main"></main>
<script>
(function(){
  "use strict";
  var $ = function(s, r){ return (r || document).querySelector(s); };
  var KEY_STORE = 'fca5_admin_key', keyInput = $('#key');
  var TIERS = ['commune','rare','halloween','noel','ed1','ed2','ed3','ed4','ed5','ed6','gold','secrete','speciale','epique','saison','legendaire'];
  var PACKS = ['classique','rare','epique','legendaire','ultra','match'];
  function lines(v){ return String(v || '').split(/\r?\n/).map(function(x){ return x.trim(); }).filter(Boolean); }
  function pairs(v){ return lines(v).map(function(l){ return l.split(';').map(function(x){ return x.trim(); }); }); }
  function json(v, def){ v = String(v || '').trim(); return v ? JSON.parse(v) : def; }

  // ---- toutes les actions : une carte par commande ----
  // f = champs : n (nom), l (libellé), t (text|int|bool|select|lines|json|date|area), o (options), req, d (valeur par défaut), ph (exemple)
  var A = [
   {tab:'Tableau de bord', id:'stats', title:'Tableau de bord', desc:'Joueurs, activité, packs, matchs 1v1, marché et crédits en circulation. Les comptes de test ne comptent pas.', method:'GET', path:'/admin/stats', render:'stats', f:[], go:'Actualiser'},
   {tab:'Tableau de bord', id:'log', title:'Journal des actions de l\'administration', desc:'Qui a fait quoi, quand, et si ça a réussi : toutes les commandes qui modifient quelque chose (la plus récente en premier). Les tentatives sans la bonne clé y figurent aussi.', method:'GET', path:'/admin/log', table:true, cols:['at','action','result'], f:[{n:'limit',l:'Nombre de lignes',t:'int',d:50,q:1},{n:'q',l:'Chercher dans le journal (facultatif)',t:'text',q:1,ph:'cible, crédits, supprimé…'}], go:'Afficher'},
   {tab:'Comptes', id:'users', title:'Voir les comptes', desc:'Pseudos, crédits, packs et nombre de cartes de chaque joueur.', method:'GET', path:'/admin/users', table:true, f:[], go:'Afficher'},
   {tab:'Comptes', id:'credits', title:'Donner ou retirer des crédits', desc:'Un nombre négatif retire des crédits.', path:'/admin/grant-credits', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1},{n:'amount',l:'Crédits (négatif pour en retirer)',t:'int',req:1}]},
   {tab:'Comptes', id:'packs', title:'Offrir des packs', desc:'S\'ajoutent aux packs bonus du joueur.', path:'/admin/grant-packs', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1},{n:'count',l:'Nombre de packs',t:'int',d:1,req:1},{n:'pack_type',l:'Type de pack',t:'select',o:PACKS,d:'classique'}]},
   {tab:'Comptes', id:'packs-all', title:'Offrir des packs à TOUS les comptes', desc:'Idéal un jour de match. Les comptes de test sont inclus.', custom:'packsAll', f:[{n:'count',l:'Nombre de packs par compte',t:'int',d:1,req:1},{n:'pack_type',l:'Type de pack',t:'select',o:PACKS,d:'classique'}], danger:1},
   {tab:'Comptes', id:'welcome-gift-view', title:'Pack ultra de bienvenue : où j\'en suis', desc:'Combien de PROCHAINS nouveaux comptes recevront encore un pack ultra offert à leur création, et combien en ont déjà reçu un.', method:'GET', path:'/admin/welcome-gift', f:[], go:'Afficher'},
   {tab:'Comptes', id:'welcome-gift-set', title:'Pack ultra de bienvenue : régler le nombre', desc:'Les N prochains comptes créés recevront un pack ultra tout de suite. Mets 30 pour lancer une nouvelle série, 0 pour arrêter.', path:'/admin/welcome-gift', f:[{n:'remaining',l:'Nombre de prochains comptes',t:'int',d:30,req:1}]},
   {tab:'Comptes', id:'remove-avatar', title:'Retirer la photo de profil d\'un joueur', desc:'Pour une photo inappropriée : elle disparaît du profil et du classement (le joueur peut en choisir une autre).', path:'/admin/remove-avatar', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1}], danger:1},
   {tab:'Tournoi', id:'tournament-view', title:'Le tournoi du mois', desc:'Où il en est : phase, inscrits, cagnotte, taille du tableau. Le tournoi se gère tout seul (inscriptions du 1er au 7, tirage le 8, tours de 24 h).', method:'GET', path:'/admin/tournament', f:[], go:'Afficher'},
   {tab:'Tournoi', id:'tournament-fee', title:'Droit d\'entrée du tournoi', desc:'Le prix que paieront les PROCHAINS inscrits (ceux déjà inscrits gardent ce qu\'ils ont payé). 20 par défaut ; la cagnotte = tous les droits payés.', path:'/admin/tournament-settings', f:[{n:'entry_fee',l:'Droit d\'entrée (crédits)',t:'int',d:20,req:1}]},
   {tab:'Tournoi', id:'tournament-bonus', title:'Bonus du club sur la cagnotte', desc:'Des crédits offerts, ajoutés à la cagnotte du tournoi de ce mois (ou du prochain s\'il n\'a pas encore ouvert). 0 pour retirer.', path:'/admin/tournament-settings', f:[{n:'bonus',l:'Bonus (crédits)',t:'int',d:100,req:1}]},
   {tab:'Tournoi', id:'tournament-cancel', title:'Annuler le tournoi du mois', desc:'Tous les droits d\'entrée sont remboursés et le tournoi s\'arrête (inscriptions ou tournoi en cours).', path:'/admin/tournament-cancel', f:[], danger:1},
   {tab:'Comptes', id:'unlock-cosmetics', title:'Débloquer tous les titres et cadres (pour les essayer)', desc:'Pour ton compte de test ou d\'administration : tous les titres et cadres de profil deviennent choisissables (bouton « 🎨 Titre et cadre » du profil). Mets 0 pour revenir au déblocage normal.', path:'/admin/unlock-cosmetics', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1},{n:'enabled',l:'1 = tout débloquer, 0 = retirer',t:'int',d:1,req:1}]},
   {tab:'Comptes', id:'chat-delete', title:'Supprimer un message du chat', desc:'Le numéro du message se lit dans le chat (ou via l\'API).', path:'/admin/chat-delete', f:[{n:'id',l:'Numéro du message',t:'int',req:1}], danger:1},
   {tab:'Comptes', id:'chat-mute', title:'Rendre un joueur muet dans le chat', desc:'Il ne peut plus écrire pendant la durée choisie (il lit toujours).', path:'/admin/chat-mute', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1},{n:'hours',l:'Heures (1 à 720)',t:'int',d:24,req:1}]},
   {tab:'Comptes', id:'chat-unmute', title:'Redonner la parole à un joueur', desc:'Annule un « muet ».', path:'/admin/chat-unmute', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1}]},
   {tab:'Matchs réels', id:'prono-bonus', title:'Bonus du club sur un pronostic', desc:'Ajoute des crédits offerts à la cagnotte d\'un match à venir (l\'identifiant se lit dans « Prochains matchs » via /matches/upcoming).', path:'/admin/prono-bonus', f:[{n:'upcoming_id',l:'Identifiant du match à venir',t:'text',req:1},{n:'bonus',l:'Bonus (crédits)',t:'int',d:50,req:1}]},
   {tab:'Comptes', id:'test', title:'Compte de test', desc:'Un compte de test a des packs illimités et n\'apparaît pas dans le classement.', path:'/admin/set-test-account', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1},{n:'is_test',l:'C\'est un compte de test',t:'bool',d:true}]},
   {tab:'Comptes', id:'reset-missions', title:'Remettre à zéro missions et série', desc:'Ne touche ni aux crédits ni aux packs.', path:'/admin/reset-missions', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1}]},
   {tab:'Comptes', id:'delete-user', title:'⚠ Supprimer un compte', desc:'Définitif : cartes, matchs et succès de ce joueur disparaissent.', path:'/admin/delete-user', f:[{n:'pseudo',l:'Pseudo',t:'text',req:1}], danger:1},

   {tab:'Cartes', id:'players', title:'Voir les joueurs et leurs cartes', desc:'Noms exacts, postes, numéros, surnoms et raretés existantes.', method:'GET', path:'/admin/players', table:true, f:[{n:'kind',l:'Filtrer par type (facultatif)',t:'select',o:['','joueur','fan','mascotte','equipement','stade','moment'],q:1}], go:'Afficher'},
   {tab:'Cartes', id:'create-player', title:'Créer un joueur ou un fan', desc:'Poste : GB, DEF, MC, ATT, X (polyvalent) ou FAN. Ses cartes (commune, rare, secrète) sont créées toutes seules.', path:'/admin/create-player', f:[{n:'name',l:'Prénom',t:'text',req:1},{n:'poste',l:'Poste',t:'text',d:'X'},{n:'numero',l:'Numéro de maillot',t:'text'},{n:'surnom',l:'Surnom',t:'text'},{n:'photo_url',l:'Photo (ex. /photos/leo.jpg)',t:'text'},{n:'grant_to_pseudo',l:'Offrir ses cartes à (pseudo)',t:'text'}]},
   {tab:'Cartes', id:'create-card', title:'Créer une carte et l\'offrir', desc:'Pour une carte qui n\'existe pas encore (légendaire, spéciale, saison…) ou pour en offrir un exemplaire.', path:'/admin/create-card', f:[{n:'player_name',l:'Joueur (nom exact)',t:'text',req:1},{n:'tier',l:'Rareté',t:'select',o:TIERS,req:1},{n:'grant_to_pseudo',l:'Offrir à (pseudo)',t:'text'}]},
   {tab:'Cartes', id:'info', title:'Surnoms et numéros de maillot', desc:'Une ligne par personne : Prénom;Numéro;Surnom (numéro ou surnom peuvent rester vides). Le prénom est reconnu même avec des majuscules ou sans accents.', path:'/admin/set-player-info', build:function(v){ return {players: pairs(v.lines).map(function(p){ return {name:p[0], numero:p[1] === undefined ? null : p[1], surnom:p[2] === undefined ? null : p[2]}; }), dry_run: !!v.dry_run}; }, f:[{n:'lines',l:'Une personne par ligne',t:'area',ph:'Théo;6;TO\nSoël;4;Noëls\nGaëtan;007;Gaytan',req:1},{n:'dry_run',l:'Aperçu seulement (n\'enregistre rien)',t:'bool',d:true}]},
   {tab:'Cartes', id:'photo', title:'Photo d\'un joueur', desc:'Sans rareté : photo par défaut. Avec une rareté : photo propre à cette rareté.', path:'/admin/set-player-photo', f:[{n:'player_name',l:'Joueur',t:'text',req:1},{n:'photo_url',l:'Photo (ex. /photos/leo.jpg)',t:'text',req:1},{n:'tier',l:'Rareté (facultatif)',t:'select',o:[''].concat(TIERS),q:1}]},
   {tab:'Cartes', id:'poste', title:'Poste d\'un joueur', desc:'GB, DEF, MC, ATT, X ou FAN.', path:'/admin/set-player-poste', f:[{n:'player_name',l:'Joueur',t:'text',req:1},{n:'poste',l:'Poste',t:'text',req:1}]},
   {tab:'Cartes', id:'mascot', title:'Créer la mascotte', desc:'Relançable sans risque.', path:'/admin/create-mascot', f:[{n:'name',l:'Nom',t:'text',d:'Le Loup'},{n:'grant_to_pseudo',l:'Offrir à (pseudo)',t:'text'}]},
   {tab:'Cartes', id:'equipment', title:'Créer les 11 équipements officiels', desc:'6 communes, 4 rares, 1 épique. Relançable sans risque : ne crée que ce qui manque.', path:'/admin/create-equipment', f:[{n:'grant_to_pseudo',l:'Offrir à (pseudo)',t:'text'}]},
   {tab:'Cartes', id:'delete-card', title:'⚠ Supprimer une carte', desc:'Retire la carte à tous les joueurs ; les défis, annonces et offres qui l\'utilisent sont annulés et remboursés.', path:'/admin/delete-card', f:[{n:'player_name',l:'Joueur',t:'text',req:1},{n:'tier',l:'Rareté',t:'select',o:TIERS,req:1}], danger:1},
   {tab:'Cartes', id:'delete-player', title:'⚠ Supprimer un joueur', desc:'Supprime le joueur et toutes ses cartes.', path:'/admin/delete-player', f:[{n:'player_name',l:'Joueur',t:'text',req:1}], danger:1},

   {tab:'Éditions', id:'editions', title:'Voir les éditions limitées', desc:'Dates, état et joueurs de chaque édition.', method:'GET', path:'/admin/editions', f:[], go:'Afficher'},
   {tab:'Éditions', id:'define-edition', title:'Créer une nouvelle édition (nouveau thème)', desc:'Ex. Saint-Valentin 💘, Pâques 🐣, Été ☀️… Tu choisis le nom, un emoji, deux couleurs (une foncée, une claire) et les dates. L\'édition prend le premier emplacement libre (12 au total : ed1 à ed12). Ensuite, crée ses cartes avec « Créer les cartes d\'une édition ». Tant qu\'elle n\'a aucune carte, tu peux la relancer pour changer son nom, ses couleurs ou ses dates.', path:'/admin/define-edition', build:function(v){ return {label:v.label.trim(), icon:v.icon.trim(), color1:v.color1, color2:v.color2, start:v.start, end:v.end, slot:v.slot}; }, after:true, f:[{n:'label',l:'Nom (24 caractères maximum)',t:'text',req:1,ph:'Saint-Valentin'},{n:'icon',l:'Emoji',t:'text',req:1,d:'🎁'},{n:'color1',l:'Couleur foncée',t:'color',d:'#B0124F'},{n:'color2',l:'Couleur claire',t:'color',d:'#FF6FA5'},{n:'start',l:'Premier jour',t:'date',req:1},{n:'end',l:'Dernier jour',t:'date',req:1},{n:'slot',l:'Emplacement',t:'select',o:['auto','ed1','ed2','ed3','ed4','ed5','ed6','ed7','ed8','ed9','ed10','ed11','ed12'],d:'auto'}]},
   {tab:'Éditions', id:'edition-slots', title:'Voir les 12 emplacements d\'éditions libres', desc:'Lesquels sont pris (nom, emoji, état, nombre de cartes) et lesquels sont libres.', method:'GET', path:'/admin/edition-slots', table:true, f:[], go:'Afficher'},
   {tab:'Éditions', id:'remove-edition', title:'⚠ Supprimer une édition libre', desc:'Seulement si elle n\'a plus aucune carte (supprime-les d\'abord avec « Supprimer une carte », rareté = l\'emplacement). Halloween et Noël ne se suppriment pas.', path:'/admin/remove-edition', after:true, f:[{n:'edition',l:'Emplacement',t:'select',o:['ed1','ed2','ed3','ed4','ed5','ed6','ed7','ed8','ed9','ed10','ed11','ed12'],req:1}], danger:1},
   {tab:'Éditions', id:'edition-dates', title:'Dates d\'une édition', desc:'Laisse vide pour ne pas changer ; « revenir aux dates d\'origine » efface les dates choisies.', path:'/admin/set-edition-dates', f:[{n:'edition',l:'Édition',t:'select',o:['halloween','noel'],req:1},{n:'start',l:'Premier jour',t:'date'},{n:'end',l:'Dernier jour',t:'date'},{n:'reset',l:'Revenir aux dates d\'origine',t:'bool'}]},
   {tab:'Éditions', id:'edition-cards', title:'Créer les cartes d\'une édition', desc:'Un prénom par ligne. Le site cache ces cartes jusqu\'au premier jour.', path:'/admin/create-edition-cards', f:[{n:'edition',l:'Édition',t:'select',o:['halloween','noel'],req:1},{n:'players',l:'Joueurs et fans (un par ligne)',t:'lines',req:1,ph:'Léo\nMathis\nNathalie'},{n:'grant_to_pseudo',l:'Offrir à (pseudo)',t:'text'}]},

   {tab:'1v1 et saisons', id:'proposals', title:'Voir les défis ouverts', desc:'Tous les défis en attente, y compris les défis privés, avec leur mise et leur enveloppe.', method:'GET', path:'/admin/proposals', table:true, f:[], go:'Afficher'},
   {tab:'1v1 et saisons', id:'cancel-proposal', title:'Annuler un défi', desc:'Recopie l\'identifiant (colonne id) depuis la liste ci-dessus. La mise et l\'enveloppe sont rendues.', path:'/admin/cancel-proposal', f:[{n:'proposal_id',l:'Identifiant du défi',t:'text',req:1}]},
   {tab:'1v1 et saisons', id:'seasons', title:'La saison en cours', desc:'Classement du mois et ce que gagneraient les 3 premiers. Les cartes trophées (« Vainqueur de saison (mois) »…) sont créées toutes seules à la clôture : rien à régler.', method:'GET', path:'/admin/seasons', f:[], go:'Afficher'},
   {tab:'1v1 et saisons', id:'weekly', title:'Cartes spéciales de la semaine', desc:'Rejoue le calcul des stars du 1v1 (normalement automatique le vendredi à 17 h).', path:'/admin/run-weekly-specials', f:[{n:'days',l:'Jours à examiner',t:'int',d:7},{n:'dry_run',l:'Aperçu seulement',t:'bool',d:true}]},
   {tab:'1v1 et saisons', id:'reset-1v1', title:'⚠ Ménage des matchs 1v1', desc:'Efface des matchs 1v1 et recalcule l\'Elo. « test » = les matchs où un compte de test a joué. Commence toujours par un aperçu.', path:'/admin/reset-1v1', f:[{n:'scope',l:'Quels matchs',t:'select',o:['test','all','none'],d:'test'},{n:'recompute_elo',l:'Recalculer l\'Elo',t:'bool',d:true},{n:'dry_run',l:'Aperçu seulement (décoche pour effacer vraiment)',t:'bool',d:true}], dangerIf:function(v){ return !v.dry_run; }},

   {tab:'Matchs réels', id:'upcoming', title:'Annoncer un prochain match', desc:'Apparaît dans l\'onglet Actualité.', path:'/admin/add-upcoming-match', f:[{n:'date',l:'Date',t:'date',req:1},{n:'opponent',l:'Adversaire',t:'text',req:1},{n:'location',l:'Lieu (facultatif)',t:'text'}]},
   {tab:'Matchs réels', id:'del-upcoming', title:'Retirer un prochain match', desc:'Par date et adversaire.', path:'/admin/delete-upcoming-match', f:[{n:'date',l:'Date',t:'date',req:1},{n:'opponent',l:'Adversaire',t:'text',req:1}]},
   {tab:'Matchs réels', id:'record-match', title:'Enregistrer un match joué', desc:'Les noms de joueurs doivent être exacts. Un joueur qui marque pour la première fois reçoit sa carte épique ; chaque « moment » crée une carte gold.', path:'/admin/record-match', build:function(v){ var b = {date:v.date, opponent:v.opponent, score_us:parseInt(v.score_us,10)||0, score_them:parseInt(v.score_them,10)||0, lineup:lines(v.lineup), cartons_jaunes:lines(v.jaunes), cartons_rouges:lines(v.rouges), buteurs:json(v.buteurs,[]), passeurs:json(v.passeurs,[]), moments:json(v.moments,[])}; if ((v.stade || '').trim()) b.stade = v.stade.trim(); if ((v.hdm || '').trim()) b.homme_du_match = v.hdm.trim(); return b; }, f:[{n:'date',l:'Date',t:'date',req:1},{n:'opponent',l:'Adversaire',t:'text',req:1},{n:'score_us',l:'Nos buts',t:'int',d:0,req:1},{n:'score_them',l:'Leurs buts',t:'int',d:0,req:1},{n:'stade',l:'Stade',t:'text'},{n:'hdm',l:'Homme du match',t:'text'},{n:'lineup',l:'Joueurs présents (un par ligne)',t:'lines'},{n:'jaunes',l:'Cartons jaunes (un par ligne)',t:'lines'},{n:'rouges',l:'Cartons rouges (un par ligne)',t:'lines'},{n:'buteurs',l:'Buteurs (JSON)',t:'json',ph:'[{"player_name":"Léo","count":2}]'},{n:'passeurs',l:'Passeurs (JSON)',t:'json',ph:'[{"player_name":"Côme","count":1}]'},{n:'moments',l:'Moments gold (JSON)',t:'json',ph:'[{"player_name":"Mathis","action":"Petit pont"}]'}]},
   {tab:'Matchs réels', id:'del-match', title:'⚠ Supprimer un match', desc:'Pour corriger une erreur de saisie : supprime puis ré-enregistre.', path:'/admin/delete-match', f:[{n:'date',l:'Date',t:'date',req:1},{n:'opponent',l:'Adversaire',t:'text',req:1}], danger:1},

   {tab:'Notifications', id:'push', title:'Envoyer une notification', desc:'À tous les joueurs qui ont activé les notifications, ou à un seul (pseudo).', path:'/admin/push-broadcast', f:[{n:'title',l:'Titre',t:'text',req:1},{n:'body',l:'Message',t:'text',req:1},{n:'url',l:'Lien à l\'ouverture',t:'text',d:'/'},{n:'pseudo',l:'À un seul joueur (facultatif)',t:'text'}]}
  ];

  // ---- affichage ----
  var tabs = [], main = $('#main'), nav = $('#nav');
  A.forEach(function(a){ if (tabs.indexOf(a.tab) < 0) tabs.push(a.tab); });
  tabs.forEach(function(t, i){ var b = document.createElement('button'); b.textContent = t; b.dataset.tab = t; if (!i) b.className = 'on'; b.onclick = function(){ show(t); }; nav.appendChild(b); var d = document.createElement('div'); d.className = 'tab' + (i ? '' : ' on'); d.dataset.tab = t; main.appendChild(d); });
  function show(t){ nav.querySelectorAll('button').forEach(function(b){ b.classList.toggle('on', b.dataset.tab === t); }); main.querySelectorAll('.tab').forEach(function(d){ d.classList.toggle('on', d.dataset.tab === t); }); }

  function fieldHTML(f, aid){
    var id = aid + '__' + f.n, v = f.d === undefined ? '' : f.d, h = '<div class="fld' + (f.t === 'bool' ? ' chk' : '') + '">';
    if (f.t === 'bool') return h + '<label><input type="checkbox" id="' + id + '"' + (v ? ' checked' : '') + '> ' + f.l + '</label></div>';
    h += '<label for="' + id + '">' + f.l + (f.req ? ' *' : '') + '</label>';
    if (f.t === 'select') h += '<select id="' + id + '">' + f.o.map(function(o){ return '<option value="' + o + '"' + (o === v ? ' selected' : '') + '>' + (o || '— tous —') + '</option>'; }).join('') + '</select>';
    else if (f.t === 'lines' || f.t === 'json' || f.t === 'area') h += '<textarea id="' + id + '" placeholder="' + (f.ph || '').replace(/"/g, '&quot;') + '"></textarea>';
    else h += '<input id="' + id + '" type="' + (f.t === 'int' ? 'number' : f.t === 'date' ? 'date' : f.t === 'color' ? 'color' : 'text') + '" value="' + String(v).replace(/"/g, '&quot;') + '">';
    return h + '</div>';
  }
  A.forEach(function(a){
    var box = document.createElement('section'); box.className = 'card'; box.id = 'card-' + a.id;
    var half = a.f.length > 3 && !a.f.some(function(f){ return f.t === 'area' || f.t === 'lines' || f.t === 'json'; });
    box.innerHTML = '<h2>' + a.title + '</h2><p class="d">' + a.desc + '</p>' + (half ? '<div class="row">' : '') + a.f.map(function(f){ return fieldHTML(f, a.id); }).join('') + (half ? '</div>' : '') +
      '<button class="' + (a.danger ? 'danger' : '') + '" data-run="' + a.id + '">' + (a.go || 'Exécuter') + '</button><div class="out" id="out-' + a.id + '"></div>';
    main.querySelector('.tab[data-tab="' + a.tab + '"]').appendChild(box);
  });

  function values(a){
    var v = {};
    a.f.forEach(function(f){ var el = document.getElementById(a.id + '__' + f.n); v[f.n] = f.t === 'bool' ? el.checked : el.value; });
    return v;
  }
  function payloadOf(a, v){
    if (a.build) return a.build(v);
    var b = {};
    a.f.forEach(function(f){
      var x = v[f.n];
      if (f.t === 'bool') { b[f.n] = !!x; return; }
      if (f.t === 'lines') { b[f.n] = lines(x); return; }
      if (f.t === 'json') { b[f.n] = json(x, []); return; }
      if (f.t === 'int') { if (String(x).trim() === '') { if (f.req) throw new Error('« ' + f.l + ' » est obligatoire'); return; } b[f.n] = parseInt(x, 10); return; }
      x = String(x).trim(); if (x === '') { if (f.req) throw new Error('« ' + f.l + ' » est obligatoire'); return; }
      b[f.n] = x;
    });
    return b;
  }
  function headers(){ return {'Content-Type': 'application/json', 'X-Admin-Key': keyInput.value.trim()}; }
  function escapeHtml(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function fmtAt(v){ var d = new Date(String(v) + 'Z'); return isNaN(d) ? v : d.toLocaleString('fr-FR', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit'}); }
  function tableOf(rows, only){
    if (!rows.length) return '<p class="ver">Aucune ligne.</p>';
    var cols = only || Object.keys(rows[0]);
    return '<div class="tw"><table><thead><tr>' + cols.map(function(c){ return '<th>' + escapeHtml(c) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.map(function(r){ return '<tr>' + cols.map(function(c){ var x = c === 'at' ? fmtAt(r[c]) : r[c]; return '<td>' + escapeHtml(x !== null && typeof x === 'object' ? JSON.stringify(x) : (x === null ? '' : x)) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
  }
  function show_result(a, status, data){
    var out = $('#out-' + a.id), ok = status >= 200 && status < 300;
    out.innerHTML = '<div class="st ' + (ok ? 'ok' : 'bad') + '">' + (ok ? '✅ ' : '❌ ') + status + (data && data.detail && !ok ? ' · ' + escapeHtml(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : '') + '</div>' +
      (ok && a.render === 'stats' && data && data.sections ? statsHTML(data) : ok && a.table && Array.isArray(data) ? tableOf(data, a.cols) : '<pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>');
  }
  function statsHTML(d){
    return d.sections.map(function(sec){
      return '<div class="stats-sec">' + escapeHtml(sec.title) + '</div><div class="stats-grid">' + sec.items.map(function(i){
        return '<div class="tile"><b>' + escapeHtml(i.value) + '</b><span>' + escapeHtml(i.label) + '</span>' + (i.hint ? '<small>' + escapeHtml(i.hint) + '</small>' : '') + '</div>';
      }).join('') + '</div>';
    }).join('');
  }
  var CUSTOM = {
    packsAll: async function(a, v){
      var r = await fetch('/admin/users', {headers: headers()}); var users = await r.json();
      if (!r.ok) return {status: r.status, data: users};
      var done = 0, fail = [];
      for (var i = 0; i < users.length; i++) {
        var g = await fetch('/admin/grant-packs', {method: 'POST', headers: headers(), body: JSON.stringify({pseudo: users[i].pseudo, count: parseInt(v.count, 10) || 1, pack_type: v.pack_type})});
        if (g.ok) done++; else fail.push(users[i].pseudo);
      }
      return {status: fail.length ? 207 : 200, data: {comptes_servis: done, echecs: fail}};
    }
  };
  async function run(a){
    var out = $('#out-' + a.id), v = values(a);
    try {
      if ((a.danger || (a.dangerIf && a.dangerIf(v))) && !window.confirm('Confirmer : ' + a.title.replace('⚠ ', '') + ' ?\n\nCette action peut être définitive.')) return;
      out.textContent = '…';
      if (a.custom) { var c = await CUSTOM[a.custom](a, v); return show_result(a, c.status, c.data); }
      var url = a.path, init = {headers: headers()};
      if (a.method === 'GET') { var q = a.f.filter(function(f){ return f.q && String(v[f.n]).trim() !== ''; }).map(function(f){ return encodeURIComponent(f.n) + '=' + encodeURIComponent(String(v[f.n]).trim()); }).join('&'); if (q) url += '?' + q; }
      else { init.method = 'POST'; init.body = JSON.stringify(payloadOf(a, v)); }
      var r = await fetch(url, init), data = null; try { data = await r.json(); } catch (e) { data = null; }
      show_result(a, r.status, data);
      if (a.after && r.ok) refreshEditionSelects();
    } catch (e) { out.innerHTML = '<div class="st bad">❌ ' + escapeHtml(e.message) + '</div>'; }
  }
  main.addEventListener('click', function(e){ var b = e.target.closest('button[data-run]'); if (b) { var a = A.filter(function(x){ return x.id === b.dataset.run; })[0]; run(a); } });

  // ---- les listes « Édition » (dates, cartes) proposent Halloween, Noël et toutes les éditions déjà créées ----
  async function refreshEditionSelects(){
    try {
      var r = await fetch('/admin/editions', {headers: headers()}); if (!r.ok) return; var list = await r.json();
      ['edition-dates__edition', 'edition-cards__edition'].forEach(function(id){
        var sel = document.getElementById(id); if (!sel) return; var cur = sel.value;
        sel.innerHTML = list.map(function(e){ return '<option value="' + e.key + '">' + escapeHtml((e.icon || '') + ' ' + e.label + ' (' + e.key + ')') + '</option>'; }).join('');
        if (list.some(function(e){ return e.key === cur; })) sel.value = cur;
      });
    } catch (e) { /* les listes de départ restent */ }
  }
  window.__admin_refresh = refreshEditionSelects;

  // ---- connexion ----
  async function login(){
    var k = keyInput.value.trim(); $('#loginMsg').textContent = '…';
    try {
      var r = await fetch('/admin/users', {headers: headers()});
      if (r.ok) { sessionStorage.setItem(KEY_STORE, k); document.body.classList.remove('locked'); $('#loginMsg').textContent = '✅ connecté'; refreshEditionSelects(); var st = A.filter(function(x){ return x.id === 'stats'; })[0]; if (st) run(st); }
      else { document.body.classList.add('locked'); $('#loginMsg').textContent = '❌ clé refusée'; }
    } catch (e) { $('#loginMsg').textContent = '❌ serveur injoignable'; }
  }
  $('#login').onclick = login; keyInput.addEventListener('keydown', function(e){ if (e.key === 'Enter') login(); });
  var saved = sessionStorage.getItem(KEY_STORE); if (saved) { keyInput.value = saved; login(); }
  window.__admin = {actions: A.map(function(a){ return a.id; })};
})();
</script>
</body>
</html>
"""
