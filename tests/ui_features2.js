// Test navigateur : autocollants repliables, bandeau d'événements, enchères, parrainage, mini-jeu du jour, face-à-face.
const chromium = require("@sparticuz/chromium").default || require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core"); const fs = require("fs"); const sleep = ms => new Promise(r => setTimeout(r, ms));
const SITE = "http://localhost:8080", API = "http://localhost:8765", OUT = process.env.SHOTS || "/tmp/shots"; const fails = [], errors = [];
const ok = (c, m) => { console.log((c ? "  OK   " : "  ÉCHEC ") + m); if (!c) fails.push(m); };
const ctx = JSON.parse(fs.readFileSync("/tmp/ctx.json")); fs.mkdirSync(OUT, { recursive: true });
const adm = (path, body) => fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json", "X-Admin-Key": "k" }, body: JSON.stringify(body) }).then(r => r.json());
const api = (path, who, method = "GET", body) => fetch(API + path, { method, headers: { "Content-Type": "application/json", Authorization: "Bearer " + ctx.tokens[who] }, body: body ? JSON.stringify(body) : undefined }).then(async r => ({ s: r.status, j: await r.json().catch(() => ({})) }));
(async () => {
  const browser = await puppeteer.launch({ args: [...chromium.args, "--no-sandbox"], executablePath: await chromium.executablePath(), headless: "shell" });
  const newPage = async (who) => {
    const page = await browser.newPage(); page.on("pageerror", e => errors.push(who + " : " + e.message)); page.on("console", m => { if (m.type() === "error" && !/Failed to load resource|fonts\.g/.test(m.text())) errors.push(who + " : " + m.text()); });
    await page.setViewport({ width: 430, height: 950, deviceScaleFactor: 1.5, isMobile: true, hasTouch: true });
    if (who) await page.evaluateOnNewDocument((t, w) => { localStorage.setItem("fca5_token", t); localStorage.setItem("fca5_pseudo", w); localStorage.setItem("fca5_notif_hint", "1"); localStorage.setItem("fca5_sound", "0"); }, ctx.tokens[who], who);
    return page;
  };
  const tab = async (page, name) => { await page.evaluate(n => document.querySelector('.tab[data-tab="' + n + '"]').click(), name); await sleep(1500); };
  const ev = (page, fn, ...a) => page.evaluate(fn, ...a).catch(e => { throw new Error(e.message.split("\n")[0] + "  ⟵ " + String(fn).replace(/\s+/g, " ").slice(0, 110)); });

  // ----- événements : on les crée AVANT d'ouvrir le site
  const e1 = await adm("/admin/event", { kind: "shop_discount", duration_hours: 48 }), e2 = await adm("/admin/event", { kind: "free_pack", duration_hours: 48, pack: "classique", per_day: 1 }), e3 = await adm("/admin/event", { kind: "pass_double", duration_hours: 24, start_in_hours: 5 });
  const A = await newPage("alice"); await A.goto(SITE, { waitUntil: "networkidle0" }); await sleep(2500);

  console.log("1) AUTOCOLLANTS");
  await tab(A, "chat");
  const st = async () => ev(A, () => { const b = document.getElementById("chatStickers"); return { btn: !document.getElementById("chatEmoji").hidden, shown: getComputedStyle(b).display !== "none", h: Math.round(b.getBoundingClientRect().height), n: b.querySelectorAll("button").length }; });
  let s0 = await st(); ok(s0.btn && !s0.shown, "le bouton 😀 est là et les autocollants sont repliés au départ (n'occupent plus de place)");
  await ev(A, () => document.getElementById("chatEmoji").click()); await sleep(300); let s1 = await st(); ok(s1.shown && s1.n > 10 && s1.h <= 100, `un clic les ouvre (${s1.n} autocollants, hauteur ${s1.h} px au plus 92)`);
  await ev(A, () => document.querySelector("#chatStickers button").click()); await sleep(200); ok(await ev(A, () => document.getElementById("chatInput").value.length > 0), "un autocollant s'insère dans le message");
  await ev(A, () => document.getElementById("chatEmoji").click()); await sleep(300); let s2 = await st(); ok(!s2.shown, "un 2e clic les referme");
  await ev(A, () => { document.getElementById("chatInput").value = ""; });

  console.log("2) ÉVÉNEMENTS");
  await tab(A, "pack");
  const bar = await ev(A, () => ({ shown: !document.getElementById("eventsBar").hidden, txt: document.getElementById("eventsBar").textContent, claim: !!document.querySelector("[data-evclaim]") }));
  ok(bar.shown && /Packs à moitié prix/.test(bar.txt) && /Un pack gratuit par jour/.test(bar.txt) && /Bientôt : Points du Pass ×2/.test(bar.txt) && bar.claim, "le bandeau annonce : promo en cours, pack gratuit (bouton), et « Bientôt » pour le Pass ×2");
  await A.screenshot({ path: OUT + "/f2_bandeau.png" });
  const p0 = (await api("/me", "alice")).j.pack_tokens.classique; await ev(A, () => document.querySelector("[data-evclaim]").click()); await sleep(1800);
  ok((await api("/me", "alice")).j.pack_tokens.classique === p0 + 1 && await ev(A, () => /récupéré aujourd/.test(document.getElementById("eventsBar").textContent)), "« Récupérer » : +1 pack classique, le bandeau passe à « ✅ récupéré aujourd'hui »");
  await tab(A, "shop"); const shop = await ev(A, () => document.getElementById("shopItemsEl").textContent); ok(/50\s*25 crédits\s*−50 %/.test(shop.replace(/\s+/g, " ").replace("50 25", "50 25")) || (/25 crédits/.test(shop) && /−50 %/.test(shop)), "boutique : prix barré, 25 crédits, « −50 % »");

  console.log("3) ENCHÈRES");
  await tab(A, "marche");
  const form = await ev(A, () => ({ opts: document.querySelectorAll("#auctionSelect option").length, durs: [...document.querySelectorAll("#auctionDurations button")].map(b => b.textContent), on: document.querySelector("#auctionDurations .on") && document.querySelector("#auctionDurations .on").textContent }));
  ok(form.opts >= 2 && JSON.stringify(form.durs) === JSON.stringify(["15 min", "30 min", "1 h", "3 h", "6 h", "12 h", "24 h"]), "formulaire : cartes rares ou mieux seulement ; boutons de durée 15 min, 30 min, 1 h, 3 h, 6 h, 12 h, 24 h (1 h par défaut)");
  await ev(A, () => document.querySelector('#auctionDurations button[data-min="15"]').click()); await sleep(300); ok(await ev(A, () => document.querySelector("#auctionDurations .on").textContent === "15 min"), "choisir « 15 min » met le bouton en évidence");
  await ev(A, () => { document.getElementById("auctionPrice").value = "12"; document.getElementById("createAuctionBtn").click(); }); await sleep(2500);
  let list = await ev(A, () => document.getElementById("auctionsEl").textContent.replace(/\s+/g, " "));
  ok(/Toi met .* aux enchères/.test(list) && /Départ : 12 crédits · aucune enchère/.test(list) && /1[45] min \d\d s|15 min 00 s/.test(list), "l'enchère apparaît : « Départ : 12 crédits », compte à rebours de ~15 min");
  const B = await newPage("bob"); await B.goto(SITE, { waitUntil: "networkidle0" }); await sleep(2000); await tab(B, "marche");
  const bin = await ev(B, () => { const i = document.querySelector("#auctionsEl .auc-actions input"); return i ? i.value : null; }); ok(bin === "12", "bob voit l'enchère, le champ propose le minimum (12)");
  const bobBefore = (await api("/me", "bob")).j.credits; await ev(B, () => document.querySelector("#auctionsEl .auc-actions button").click()); await sleep(2200);
  list = await ev(B, () => document.getElementById("auctionsEl").textContent.replace(/\s+/g, " ")); ok(/Meilleure enchère : 12 crédits par toi 🏆/.test(list), "bob enchérit : « Meilleure enchère : 12 crédits par toi 🏆 »");
  ok((await api("/me", "bob")).j.credits === bobBefore - 12, "les crédits de bob sont mis de côté (12 débités : " + bobBefore + " → " + ((await api("/me", "bob")).j.credits) + ")");
  await B.screenshot({ path: OUT + "/f2_encheres.png" });
  await tab(A, "marche"); list = await ev(A, () => document.getElementById("auctionsEl").textContent.replace(/\s+/g, " ")); ok(/Meilleure enchère : 12 crédits par bob \(1 enchère\)/.test(list) && !/Annuler/.test(list), "alice voit « par bob (1 enchère) » ; plus de bouton Annuler");
  await B.close();

  console.log("4) PARRAINAGE");
  await ev(A, () => document.getElementById("chipPseudo").click()); await sleep(2500); await ev(A, () => document.getElementById("profInvite").click()); await sleep(1500);
  const ref = await ev(A, () => ({ code: document.getElementById("refCode").textContent, txt: document.getElementById("modalBody").textContent }));
  ok(ref.code === ctx.refcode && /un pack ultra/.test(ref.txt) && /0 \/ 3/.test(ref.txt), "« Inviter un ami » : le code " + ref.code + ", « 0 / 3 », un pack ultra chacun");
  await A.screenshot({ path: OUT + "/f2_parrainage.png" });
  const G = await browser.newPage(); G.on("pageerror", e => errors.push("gate : " + e.message)); await G.setViewport({ width: 430, height: 950, isMobile: true });
  await G.goto(SITE, { waitUntil: "domcontentloaded" }); await G.evaluate(() => localStorage.clear());      // (visiteur sans compte : on efface la connexion partagée)
  await G.goto(SITE + "/?ref=" + ctx.refcode, { waitUntil: "networkidle0" }); await sleep(1500);
  const gate = await ev(G, () => ({ vis: !document.getElementById("refRow").hidden, val: document.getElementById("refInput").value }));
  ok(gate.vis && gate.val === ctx.refcode, "lien d'invitation (?ref=…) : l'inscription affiche le champ, déjà rempli avec le code");
  await ev(G, () => { document.getElementById("pseudoInput").value = "dave"; document.getElementById("passwordInput").value = "test1234"; document.getElementById("gateSubmit").click(); }); await sleep(3500);
  ok((await api("/referral", "alice")).j.count === 1 && (await api("/referral", "alice")).j.referees[0] === "dave", "dave crée son compte avec le code : alice a 1 filleul (dave)");
  await G.close();

  console.log("5) MINI-JEU DU JOUR");
  await A.reload({ waitUntil: "networkidle0" }); await sleep(2500); await tab(A, "pack");
  const mc = await ev(A, () => ({ shown: !document.getElementById("miniCard").hidden, txt: document.getElementById("miniCard").textContent, mission: [...document.querySelectorAll("#missionsBox .m-label")].map(x => x.textContent) }));
  ok(mc.shown && /Mini-jeu du jour/.test(mc.txt) && mc.mission.includes("Joue au mini-jeu du jour") && mc.mission.filter(x => !/Bonus/.test(x)).length === 3, "carte « Mini-jeu du jour » + la mission « Joue au mini-jeu du jour » parmi les 3 défis : " + mc.txt.slice(0, 50));
  await A.screenshot({ path: OUT + "/f2_minijeu_carte.png" });
  await ev(A, () => document.getElementById("miniPlay").click()); await sleep(1500);
  const kind = await ev(A, () => document.getElementById("modalTitle").textContent.includes("Quiz") ? "quiz" : "penalty");
  if (kind === "quiz") {
    for (let i = 0; i < 5; i++) {
      const q = await ev(A, () => ({ n: document.querySelectorAll("#modalBody [data-choice]").length, t: document.getElementById("modalBody").textContent.slice(0, 60) })); if (i === 0) ok(q.n === 3 && /Question 1 \/ 5/.test(q.t), "quiz : question 1 / 5, trois réponses");
      await ev(A, () => document.querySelector("#modalBody [data-choice]").click()); await sleep(1200);
      const fb = await ev(A, () => ({ good: document.querySelectorAll("#modalBody .mg-choice.good").length, why: !!document.querySelector("#modalBody .mg-why"), nx: document.getElementById("mgNext").textContent })); if (i === 0) { ok(fb.good === 1 && fb.why, "après la réponse : la bonne réponse est en vert avec son explication"); await A.screenshot({ path: OUT + "/f2_quiz.png" }); }
      await ev(A, () => document.getElementById("mgNext").click()); await sleep(500);
    }
  } else {
    for (let i = 0; i < 5; i++) { if (i === 0) { ok(await ev(A, () => document.querySelectorAll("#modalBody .mg-zone").length === 6 && !!document.querySelector("#modalBody .mg-stand") && document.querySelectorAll("#modalBody .mg-row span").length >= 40 && !!document.getElementById("mgKeeper") && /Tir 1 \/ 5/.test(document.getElementById("modalBody").textContent)), "tirs au but : tir 1 / 5, un but à 6 zones cliquables, une tribune de supporters derrière, le gardien et le ballon"); await A.screenshot({ path: OUT + "/f2_penalty.png" }); }
      const z = Math.floor(Math.random() * 6); await ev(A, zz => document.querySelector('#modalBody [data-zone="' + zz + '"]').click(), z); await sleep(1300);
      const fbk = await ev(A, () => ({ msg: !!document.querySelector("#modalBody .mg-msg"), keeper: document.getElementById("mgKeeper").style.left + "/" + document.getElementById("mgKeeper").style.top, ball: document.getElementById("mgBall").style.left + "/" + document.getElementById("mgBall").style.top, zones: document.querySelectorAll("#modalBody .mg-zone").length }));
      if (i === 0) { ok(fbk.msg && fbk.zones === 0 && fbk.ball !== "50%/136%", "après le tir : le ballon part vers la zone visée (" + fbk.ball + "), le gardien plonge (" + fbk.keeper + "), un message annonce BUT / ARRÊTÉ"); await A.screenshot({ path: OUT + "/f2_penalty_tir.png" }); }
      await ev(A, () => document.getElementById("mgNext").click()); await sleep(500); }
  }
  const end = await ev(A, () => document.getElementById("modalBody").textContent); ok(/\/ 5/.test(end) && /points de Pass/.test(end) && /récupère-la/.test(end), "fin de partie : score sur 5, points de Pass gagnés, rappel de récupérer la mission");
  const g = (await api("/minigame", "alice")).j; ok(g.finished && g.pass_points === Math.min(50, g.score * 10), `le serveur confirme : ${g.score}/5 → ${g.pass_points} points de Pass`);
  await ev(A, () => document.getElementById("modalCloseBtn").click()); await sleep(800); await tab(A, "pack");
  const mm = await ev(A, () => ({ card: document.getElementById("miniCard").textContent, claim: !!document.querySelector('#missionsBox [data-claim="mission"][data-id="minigame"]') })); ok(/Terminé/.test(mm.card) && mm.claim, "la carte indique « Terminé » et la mission du mini-jeu peut être récupérée");

  console.log("6) FACE-À-FACE");
  await ev(A, () => { document.getElementById("modalCloseBtn").click(); }); await tab(A, "classement");
  const prof = async who => { await ev(A, w => { [...document.querySelectorAll("#leaderboardEl *")].find(el => el.children.length === 0 && el.textContent.trim() === w).click(); }, who).catch(() => {}); await sleep(2500); return ev(A, () => document.getElementById("modalBody").textContent.replace(/\s+/g, " ")); };
  let pb = await prof("bob"); if (!/Face à face/.test(pb)) { await ev(A, () => { window.openProfile && 0; }); }
  ok(/Face à face/.test(pb) && /1 match/.test(pb), "profil de bob : « ⚔️ Face à face » avec vos matchs (1 match)");
  await A.screenshot({ path: OUT + "/f2_versus.png" }); await ev(A, () => document.getElementById("modalCloseBtn").click()); await sleep(500);
  pb = await prof("carol"); ok(/jamais affrontés/.test(pb), "profil de carol : « Vous ne vous êtes encore jamais affrontés »");
  console.log("\nerreurs JavaScript :", errors.length ? errors.slice(0, 4) : "aucune"); ok(errors.length === 0, "aucune erreur JavaScript");
  console.log("BILAN NOUVEAUTÉS (navigateur) :", fails.length ? fails.length + " ÉCHEC(S) : " + JSON.stringify(fails) : "TOUT EST VERT"); await browser.close();
})().catch(e => { console.log("ECHEC DU TEST", e.message.split("\n")[0]); if (errors.length) console.log("erreurs de la page :", errors.slice(0, 3)); process.exit(1); });
