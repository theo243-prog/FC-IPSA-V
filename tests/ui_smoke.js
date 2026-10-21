// Parcours de contrôle en vrai navigateur : pop-up de bienvenue, tous les onglets, outils de collection, historique des saisons, images à partager.
const chromium = require("@sparticuz/chromium").default || require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core"); const sleep = ms => new Promise(r => setTimeout(r, ms));
const API = "http://localhost:8765", SITE = "http://localhost:8080"; const fails = [], errors = [];
const ok = (c, m) => { console.log((c ? "  OK   " : "  ÉCHEC ") + m); if (!c) fails.push(m); };
(async () => {
  const pseudo = "smoke" + (Date.now() % 100000);
  const reg = await (await fetch(API + "/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pseudo, password: "test1234" }) })).json();
  const browser = await puppeteer.launch({ args: [...chromium.args, "--no-sandbox"], executablePath: await chromium.executablePath(), headless: "shell" });
  const page = await browser.newPage(); page.on("pageerror", e => errors.push(e.message)); page.on("console", m => { if (m.type() === "error" && !/Failed to load resource|fonts\.g/.test(m.text())) errors.push(m.text()); });
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  await page.evaluateOnNewDocument((t, p) => { localStorage.setItem("fca5_token", t); localStorage.setItem("fca5_pseudo", p); localStorage.setItem("fca5_notif_hint", "1"); localStorage.setItem("fca5_sound", "0"); }, reg.token, pseudo);
  await page.goto(SITE, { waitUntil: "networkidle0" }); await sleep(2500);
  const ev = (fn, ...a) => page.evaluate(fn, ...a), tab = async (k, ms = 1800) => { await ev(k => document.querySelector('.tab[data-tab="' + k + '"]').click(), k); await sleep(ms); };
  console.log("1) COMPTE NEUF : POP-UP DE BIENVENUE");
  const w = await ev(() => ({ open: document.getElementById("welcomeModal").style.display, names: [...document.querySelectorAll("#welcomeModal .wl-name")].map(e => e.textContent.trim()).join(" | "), t: document.getElementById("welcomeModal").textContent }));
  ok(w.open === "flex" && w.names === "Théo | Léo & Emrys | Gaëtan" && /manager/.test(w.t) && /tests de développement/.test(w.t) && /idées/.test(w.t), "le pop-up de remerciements s'ouvre : " + w.names);
  await ev(() => document.getElementById("welcomeGo").click()); await sleep(1200); ok(await ev(() => document.getElementById("welcomeModal").style.display === "none"), "« C'est parti ! » le ferme");
  console.log("2) TOUS LES ONGLETS");
  const tabs = await ev(() => [...document.querySelectorAll(".tab")].map(b => b.dataset.tab)); ok(tabs.join() === "pack,collection,marche,shop,classement,actualite,duels,tournoi,chat", "les 9 onglets : " + tabs.join(", "));
  for (const k of tabs) { await tab(k); ok(await ev(k => document.getElementById("tab-" + k).classList.contains("active"), k), "onglet « " + k + " » s'ouvre"); }
  console.log("3) COLLECTION");
  await tab("collection", 2500);
  const n0 = await ev(() => document.querySelectorAll("#collectionByTier .card").length); await page.type("#collSearch", "zzzz"); await sleep(500);
  ok(await ev(() => /Aucune carte ne correspond/.test(document.getElementById("collectionByTier").textContent)), "la recherche d'un nom inconnu ne montre rien");
  await ev(() => { const i = document.getElementById("collSearch"); i.value = ""; i.dispatchEvent(new Event("input", { bubbles: true })); }); await sleep(500);
  await ev(() => document.querySelector('#collFilters button[data-f="missing"]').click()); await sleep(400); ok(await ev(() => [...document.querySelectorAll("#collectionByTier .card")].every(c => c.classList.contains("locked"))), "filtre « Manquantes » : que des cartes inconnues");
  await ev(() => document.querySelector('#collFilters button[data-f="all"]').click()); await sleep(400);
  await ev(() => document.getElementById("collFold").click()); await sleep(300); ok(await ev(() => [...document.querySelectorAll("#collectionByTier .tier-group")].every(g => g.classList.contains("collapsed"))), "« Tout replier » range toutes les raretés");
  await ev(() => document.getElementById("collUnfold").click()); await sleep(300);
  await ev(() => document.getElementById("collSellAll").click()); await sleep(1200); ok(!(await ev(() => document.getElementById("confirmModal").style.display === "flex")) && /aucun doublon/i.test(await ev(() => document.getElementById("toast").textContent)), "« Vendre tous les doublons » sans doublon : simple message, pas de fenêtre");
  console.log("4) PROFIL, SAISONS, IMAGES");
  await ev(() => document.getElementById("chipPseudo").click()); await sleep(2500);
  ok(await ev(() => !!document.getElementById("profAvatarBtn") && !!document.getElementById("profShare") && !!document.getElementById("profCosm")), "mon profil : 📷 photo, 📤 partager, 🎨 titre et cadre");
  await ev(() => document.getElementById("profShare").click()); let ready = false; for (let k = 0; k < 40 && !ready; k++) { ready = await ev(() => { const i = document.getElementById("sharePreview"); return !!(i && i.complete && i.naturalWidth); }); if (!ready) await sleep(500); }
  const im = await ev(() => { const i = document.getElementById("sharePreview"); return i ? [i.naturalWidth, i.naturalHeight] : null; }); ok(im && im[0] === 1080 && im[1] === 1350, "l'image du profil se génère : " + (im && im.join(" × ")));
  await ev(() => { document.getElementById("shareClose").click(); document.getElementById("modalCloseBtn").click(); }); await sleep(300);
  await tab("collection", 1500); await ev(() => document.getElementById("collShare").click()); ready = false; for (let k = 0; k < 60 && !ready; k++) { ready = await ev(() => { const i = document.getElementById("sharePreview"); return !!(i && i.complete && i.naturalWidth); }); if (!ready) await sleep(500); }
  const im2 = await ev(() => { const i = document.getElementById("sharePreview"); return i ? [i.naturalWidth, i.naturalHeight] : null; }); ok(im2 && im2[0] === 1080 && im2[1] > 1500, "l'image de la collection se génère : " + (im2 && im2.join(" × "))); await ev(() => document.getElementById("shareClose").click());
  await tab("duels", 2500); await ev(() => document.getElementById("seasonHistoryBtn").click()); await sleep(1500); ok(await ev(() => document.getElementById("modalTitle").textContent === "Historique des saisons"), "« Historique des saisons » s'ouvre"); await ev(() => document.getElementById("modalCloseBtn").click());
  await tab("classement", 2000); ok(await ev(() => document.querySelectorAll("table.leaderboard tbody tr .av").length >= 1), "le classement affiche les pastilles (photo ou initiale)");
  console.log("\nerreurs JavaScript :", errors.length ? errors : "aucune"); ok(errors.length === 0, "aucune erreur JavaScript");
  console.log("BILAN PARCOURS NAVIGATEUR :", fails.length ? fails.length + " ÉCHEC(S) : " + JSON.stringify(fails) : "TOUT EST VERT"); await browser.close();
})().catch(e => { console.log("ECHEC DU TEST", e.message.split("\n")[0]); process.exit(1); });
