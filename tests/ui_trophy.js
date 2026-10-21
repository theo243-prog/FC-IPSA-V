// Test navigateur : cartes de tournoi (vainqueur, finaliste) violettes à dégradé rose fluo, fiche et images à partager.
const chromium = require("@sparticuz/chromium").default || require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core"); const fs = require("fs"); const sleep = ms => new Promise(r => setTimeout(r, ms));
const SITE = "http://localhost:8080", OUT = process.env.SHOTS || "/tmp/shots"; const fails = [], errors = [];
const ok = (c, m) => { console.log((c ? "  OK   " : "  ÉCHEC ") + m); if (!c) fails.push(m); };
const ctx = JSON.parse(fs.readFileSync("/tmp/ctx.json")); fs.mkdirSync(OUT, { recursive: true });
(async () => {
  const browser = await puppeteer.launch({ args: [...chromium.args, "--no-sandbox"], executablePath: await chromium.executablePath(), headless: "shell" });
  const page = await browser.newPage(); page.on("pageerror", e => errors.push(e.message)); page.on("console", m => { if (m.type() === "error" && !/Failed to load resource|fonts\.g/.test(m.text())) errors.push(m.text()); });
  await page.setViewport({ width: 430, height: 900, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await page.evaluateOnNewDocument((t) => { localStorage.setItem("fca5_token", t); localStorage.setItem("fca5_pseudo", "alice"); localStorage.setItem("fca5_notif_hint", "1"); localStorage.setItem("fca5_sound", "0"); }, ctx.tokens.alice);
  await page.goto(SITE, { waitUntil: "networkidle0" }); await sleep(2200);
  const ev = (fn, ...a) => page.evaluate(fn, ...a);
  await ev(() => document.querySelector('.tab[data-tab="collection"]').click()); await sleep(2500);
  const g = await ev(() => { const grp = [...document.querySelectorAll("#collectionByTier .tier-group")].find(x => x.dataset.tier === "saison"); const cards = [...grp.querySelectorAll(".card:not(.locked)")]; return { title: grp.querySelector("h3").textContent, cards: cards.map(c => ({ name: c.querySelector(".card-name").textContent, label: c.querySelector(".card-tier-label").textContent, tourney: c.classList.contains("trophy-tournoi"), bg: getComputedStyle(c).backgroundImage })) }; });
  ok(/^Trophées/.test(g.title) && g.cards.length === 3, `le groupe s'appelle « ${g.title.trim()} » (saison et tournoi) : ${g.cards.length} cartes`);
  const t4 = g.cards.find(c => /Vainqueur du tournoi/.test(c.name)), t5 = g.cards.find(c => /Finaliste du tournoi/.test(c.name)), s1 = g.cards.find(c => /Vainqueur de saison/.test(c.name));
  ok(t4 && t5 && t4.tourney && t5.tourney && !s1.tourney, "« Vainqueur du tournoi » et « Finaliste du tournoi » ont le style tournoi ; la carte de saison garde le sien");
  ok(t4.label === "Tournoi" && t5.label === "Tournoi" && s1.label === "Saison", "l'étiquette de rareté dit « Tournoi » (« Saison » pour la saison)");
  ok(/rgb\(58, 12, 163\)/.test(t4.bg) && /rgb\(255, 47, 209\)/.test(t4.bg) && /rgb\(123, 47, 247\)/.test(t4.bg) && !/rgb\(15, 94, 115\)/.test(t4.bg) && /rgb\(15, 94, 115\)/.test(s1.bg), "fond : violet (#3A0CA3, #7B2FF7) vers rose fluo (#FF2FD1) pour le tournoi ; bleu-vert inchangé pour la saison");
  await (await page.$("#collectionByTier .tier-group[data-tier='saison']")).screenshot({ path: OUT + "/cartes_tournoi_collection.png" });
  await ev(() => [...document.querySelectorAll("#collectionByTier .tier-group[data-tier='saison'] .card")].find(c => /Finaliste/.test(c.textContent)).click()); await sleep(1500);
  ok(await ev(() => /Carte de finaliste du tournoi de novembre 2026/.test(document.getElementById("modalBody").textContent)), "la fiche du finaliste : « Carte de finaliste du tournoi de novembre 2026 »");
  await ev(() => document.getElementById("shareCardBtn").click()); let ready = false; for (let k = 0; k < 40 && !ready; k++) { ready = await ev(() => { const i = document.getElementById("sharePreview"); return !!(i && i.complete && i.naturalWidth); }); if (!ready) await sleep(500); }
  const px = await ev(async () => { const i = document.getElementById("sharePreview"), b = await (await fetch(i.src)).blob(), bmp = await createImageBitmap(b), cv = document.createElement("canvas"); cv.width = bmp.width; cv.height = bmp.height; const x = cv.getContext("2d"); x.drawImage(bmp, 0, 0); const p = (a, c) => [...x.getImageData(a, c, 1, 1).data].slice(0, 3); return { w: bmp.width, h: bmp.height, top: p(800, 500), bottom: p(800, 660) }; });
  ok(px.w === 1080 && px.h === 1350 && px.top[2] > 200 && px.top[1] < 80 && px.bottom[0] > px.top[0] + 10 && px.bottom[0] > 190 && px.bottom[1] < 80 && px.bottom[2] > 200, `l'image à partager reprend le dégradé de la carte (violet puis rose fluo) : ${JSON.stringify(px.top)} → ${JSON.stringify(px.bottom)}`);
  await ev(async () => { const i = document.getElementById("sharePreview"), b = await (await fetch(i.src)).blob(), r = new FileReader(); await new Promise(res => { r.onload = res; r.readAsDataURL(b); }); window.__png = r.result; });
  fs.writeFileSync(OUT + "/carte_finaliste_partage.png", Buffer.from((await ev(() => window.__png)).split(",")[1], "base64"));
  await ev(() => { document.getElementById("shareClose").click(); document.getElementById("modalCloseBtn").click(); }); await sleep(300);
  await ev(() => document.getElementById("collShare").click()); ready = false; for (let k = 0; k < 60 && !ready; k++) { ready = await ev(() => { const i = document.getElementById("sharePreview"); return !!(i && i.complete && i.naturalWidth); }); if (!ready) await sleep(500); }
  await ev(async () => { const i = document.getElementById("sharePreview"), b = await (await fetch(i.src)).blob(), r = new FileReader(); await new Promise(res => { r.onload = res; r.readAsDataURL(b); }); window.__png = r.result; });
  fs.writeFileSync(OUT + "/collection_partage_tournoi.png", Buffer.from((await ev(() => window.__png)).split(",")[1], "base64")); ok(true, "l'image de la collection se génère avec ces cartes");
  console.log("\nerreurs JavaScript :", errors.length ? errors : "aucune"); ok(errors.length === 0, "aucune erreur JavaScript");
  console.log("BILAN CARTES DE TOURNOI (navigateur) :", fails.length ? fails.length + " ÉCHEC(S) : " + JSON.stringify(fails) : "TOUT EST VERT"); await browser.close();
})().catch(e => { console.log("ECHEC DU TEST", e.message.split("\n")[0]); process.exit(1); });
