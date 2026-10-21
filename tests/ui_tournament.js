// Test en vrai navigateur du tournoi. Deux phases, avec l'horloge du serveur figée (FC_FAKE_NOW) : A = inscriptions (3 novembre), B = premier tour (8 novembre, 13h).
// Usage : node tests/ui_tournament.js A   puis   node tests/ui_tournament.js B   (voir tests/LISEZMOI.md)
const chromium = require("@sparticuz/chromium").default || require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core"); const fs = require("fs"); const sleep = ms => new Promise(r => setTimeout(r, ms));
const API = "http://localhost:8765", SITE = "http://localhost:8080", OUT = process.env.SHOTS || "/tmp/shots", PHASE = process.argv[2] || "A";
const fails = [], errors = []; const ok = (c, m) => { console.log((c ? "  OK   " : "  ÉCHEC ") + m); if (!c) fails.push(m); };
const ctx = JSON.parse(fs.readFileSync("/tmp/ctx.json")); fs.mkdirSync(OUT, { recursive: true });
const jf = async (path, who, method = "GET", body) => { const r = await fetch(API + path, { method, headers: { "Content-Type": "application/json", Authorization: "Bearer " + ctx.tokens[who] }, body: body ? JSON.stringify(body) : undefined }); let j = null; try { j = await r.json(); } catch (e) {} return { s: r.status, j }; };
(async () => {
  const browser = await puppeteer.launch({ args: [...chromium.args, "--no-sandbox"], executablePath: await chromium.executablePath(), headless: "shell" });
  const open = async (who, w, h, mobile) => {
    const page = await browser.newPage(); page.on("pageerror", e => errors.push(who + " : " + e.message)); page.on("console", m => { if (m.type() === "error" && !/Failed to load resource|fonts\.g/.test(m.text())) errors.push(who + " : " + m.text()); });
    await page.setViewport({ width: w, height: h, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile });
    await page.evaluateOnNewDocument((t, p) => { localStorage.setItem("fca5_token", t); localStorage.setItem("fca5_pseudo", p); localStorage.setItem("fca5_notif_hint", "1"); localStorage.setItem("fca5_sound", "0"); }, ctx.tokens[who], who);
    await page.goto(SITE, { waitUntil: "networkidle0" }); await sleep(2200); return page;
  };
  const ev = (page, fn, ...a) => page.evaluate(fn, ...a), tab = async (page, k, ms = 2500) => { await ev(page, k => document.querySelector('.tab[data-tab="' + k + '"]').click(), k); await sleep(ms); };
  if (PHASE === "A") {
    console.log("PHASE A : INSCRIPTIONS (le 3 novembre)");
    const P = await open("alice", 390, 844, true); await tab(P, "tournoi");
    const a = await ev(P, () => ({ title: document.querySelector("#tnHead h2").textContent, stats: [...document.querySelectorAll("#tnHead .tn-stat b")].map(b => b.textContent), join: !!document.getElementById("tnJoin"), txt: document.getElementById("tnHead").textContent, chips: document.querySelectorAll("#tnHead .tn-chip").length, prizes: document.getElementById("tnPrizes").textContent, rules: document.querySelectorAll(".tn-rules li").length, bracketHidden: document.getElementById("tnBracketBox").hidden }));
    ok(/Tournoi de novembre 2026/.test(a.title) && a.stats.join() === "20,4,80" && a.join && /Inscriptions ouvertes jusqu'au samedi 7 novembre à minuit/.test(a.txt), "l'onglet Tournoi : droit d'entrée 20, 4 inscrits, cagnotte 80, inscriptions jusqu'au samedi 7 novembre à minuit");
    ok(a.chips === 4 && a.bracketHidden && /Vainqueur/.test(a.prizes) && a.rules === 7, "les 4 inscrits sont listés, pas encore de tableau, gains annoncés, 7 règles expliquées");
    await P.screenshot({ path: OUT + "/tournoi_inscriptions.png", fullPage: true });
    await ev(P, () => document.getElementById("tnJoin").click()); await sleep(700);
    ok(await ev(P, () => document.getElementById("confirmTitle").textContent === "S'inscrire au tournoi ?" && /20 crédits/.test(document.getElementById("confirmBody").textContent) && /Elo/.test(document.getElementById("confirmBody").textContent)), "« S'inscrire » demande confirmation et rappelle le droit d'entrée et que l'Elo n'est pas touché");
    await ev(P, () => document.getElementById("confirmNo").click()); await sleep(300); ok((await jf("/me", "alice")).j.credits === 100, "« Annuler » : rien n'est payé");
    await ev(P, () => document.getElementById("tnJoin").click()); await sleep(500); await ev(P, () => document.getElementById("confirmYes").click()); await sleep(3000);
    const b = await ev(P, () => ({ stats: [...document.querySelectorAll("#tnHead .tn-stat b")].map(b => b.textContent), leave: !!document.getElementById("tnLeave"), txt: document.getElementById("tnHead").textContent, cr: parseInt(document.getElementById("chipCredits").textContent, 10), chips: document.querySelectorAll("#tnHead .tn-chip").length }));
    ok(b.stats.join() === "20,5,100" && b.leave && /Tu es inscrit/.test(b.txt) && b.cr === 80 && b.chips === 6, "alice s'inscrit : 5 inscrits, cagnotte 100, ses crédits 100 → 80, bouton « Se désinscrire »");
    await ev(P, () => document.getElementById("tnLeave").click()); await sleep(500); await ev(P, () => document.getElementById("confirmYes").click()); await sleep(3000);
    ok(await ev(P, () => !!document.getElementById("tnJoin") && parseInt(document.getElementById("chipCredits").textContent, 10) === 100), "elle se désinscrit : remboursée (100 crédits), le bouton « S'inscrire » revient");
    await ev(P, () => document.getElementById("tnJoin").click()); await sleep(500); await ev(P, () => document.getElementById("confirmYes").click()); await sleep(3000);
    ok((await jf("/tournament", "alice")).j.me.joined === true, "elle se réinscrit pour la suite du test");
  } else {
    console.log("PHASE B : PREMIER TOUR (le 8 novembre, 13h)");
    await jf("/tournament", "bob"); const g = (await jf("/tournament", "alice")).j; const dan = g.rounds[0].matches.find(m => m.p1 && m.p2 && [m.p1.pseudo, m.p2.pseudo].includes("dan"));
    const dteam = { formation: "1-2-1", tactic: "contre", slots: (await jf("/collection", "dan")).j.filter(c => c.quantity > 0 && ["Lucas", "Hugo", "Nathan", "Léo", "Enzo"].includes(c.player_name) && c.tier === "commune").map((c, i) => ({ card_id: c.id, slot_category: ["GB", "DEF", "MC", "MC", "ATT"][i] })) };
    ok(g.phase === "running" && g.size === 8 && g.rounds.length === 3, "le tirage a eu lieu : 5 joueurs, tableau de 8, 3 tours");
    ok((await jf("/tournament/matches/" + dan.id + "/team", "dan", "POST", dteam)).j.resolved === false, "dan (adversaire d'alice) valide son équipe par avance");
    const elo0 = (await jf("/me", "alice")).j; const D = await open("alice", 1100, 900, false);
    ok(await ev(D, () => !document.getElementById("tournoiDot").hidden), "le point rouge de l'onglet Tournoi signale un match à composer");
    await tab(D, "tournoi", 3000);
    const m1 = await ev(D, () => ({ head: document.getElementById("tnHead").textContent, mine: document.getElementById("tnMineBox").textContent, cols: [...document.querySelectorAll("#tnBracket .tn-col h4")].map(h => h.textContent), matches: document.querySelectorAll("#tnBracket .tn-match").length, mineBox: !!document.querySelector("#tnBracket .tn-match.mine"), dot: document.getElementById("tournoiDot").hidden, prizes: document.getElementById("tnPrizes").textContent }));
    ok(/Quarts de finale/.test(m1.head) && m1.cols.join() === "Quarts de finale,Demi-finales,Finale" && m1.matches === 7 && m1.mineBox, "le tableau : 3 colonnes (quarts, demi-finales, finale), 7 matchs, le tien est surligné");
    ok(/Ton match : Quarts de finale/.test(m1.mine) && /dan/.test(m1.mine) && /Ton équipe : ❌/.test(m1.mine) && /dan : ✅ prêt/.test(m1.mine) && /forfait/.test(m1.mine) && m1.dot, "« Ton match » : contre dan, ton équipe pas encore composée, dan est prêt, rappel du forfait ; le point rouge s'éteint dans l'onglet");
    await D.screenshot({ path: OUT + "/tournoi_en_cours.png", fullPage: true });
    ok(await ev(D, () => [...document.querySelectorAll("#tnBracket .tn-state")].filter(s => /passe directement/.test(s.textContent)).length === 3), "les 3 têtes de série exemptées sont marquées « passe directement »");
    await ev(D, () => document.getElementById("tnTeam").click()); await sleep(1500);
    const tm = await ev(D, () => ({ open: document.getElementById("teamModal").style.display, title: document.getElementById("tmTitle").textContent, intro: document.getElementById("tmIntro").textContent, stake: document.getElementById("tmStakeRow").style.display, ref: document.getElementById("tmRefRow").style.display, target: document.getElementById("tmTargetRow").style.display, submit: document.getElementById("tmSubmit").textContent }));
    ok(tm.open === "flex" && /Tournoi : Quarts de finale contre dan/.test(tm.title) && /ne compte pas pour l'Elo/.test(tm.intro) && tm.stake === "none" && tm.ref === "none" && tm.target === "none" && tm.submit === "Valider mon équipe", "le formulaire d'équipe du 1v1 s'ouvre en mode tournoi : sans mise, sans arbitre, sans défi privé, bouton « Valider mon équipe »");
    await ev(D, () => { const sels = [...document.querySelectorAll("#tmSlots select")], vals = [...sels[0].options].map(o => o.value).filter(Boolean); sels.forEach((s, i) => { s.value = vals[i]; s.dispatchEvent(new Event("change", { bubbles: true })); }); }); await sleep(300);
    await ev(D, () => document.getElementById("tmSubmit").click()); await sleep(2500);
    await ev(D, () => { const s = document.getElementById("msSkip"); if (s && s.style.display !== "none") s.click(); }); await sleep(800);      // (on passe le récit en direct pour lire le résultat)
    const mm = await ev(D, () => ({ modal: document.getElementById("matchModal").style.display, res: document.getElementById("msResult").textContent, names: document.getElementById("msNameA").textContent + "|" + document.getElementById("msNameB").textContent, rematch: document.getElementById("msRematch").style.display }));
    ok(mm.modal === "flex" && /se qualifie/.test(mm.res) && /Quarts de finale du tournoi de novembre 2026/.test(mm.res) && /ne compte ni pour l'Elo/.test(mm.res) && mm.rematch === "none", "alice valide en dernier : le match se joue et s'affiche en direct, résultat « se qualifie », sans bouton de revanche : " + mm.names);
    await D.screenshot({ path: OUT + "/tournoi_match.png" }); await ev(D, () => document.getElementById("msClose").click()); await sleep(500);
    await sleep(1500); await tab(D, "duels", 500); await tab(D, "tournoi", 2500);
    const m2 = await ev(D, () => ({ mine: document.getElementById("tnMineBox").textContent, replay: !!document.getElementById("tnReplay"), done: [...document.querySelectorAll("#tnBracket .tn-match")].filter(m => m.querySelector(".win")).length }));
    if (!(/(Qualifié|Éliminé|qualifié|éliminé)/.test(m2.mine) && m2.replay)) console.log("   (détail : " + JSON.stringify(m2).slice(0, 400) + ")");
    ok(/(Qualifié|Éliminé|qualifié|éliminé)/.test(m2.mine) && m2.replay && m2.done >= 4, "« Ton match » affiche le résultat (ou « Dernier match » quand le suivant est déjà annoncé) avec « ▶️ Voir le match » ; le tableau montre les vainqueurs (" + m2.done + " matchs terminés, exemptés compris)");
    await ev(D, () => document.getElementById("tnReplay").click()); await sleep(1500); ok(await ev(D, () => document.getElementById("matchModal").style.display === "flex" && /Récap/.test(document.getElementById("msTitle").textContent)), "« Voir le match » rejoue le récit"); await ev(D, () => document.getElementById("msClose").click());
    const el1 = (await jf("/me", "alice")).j; ok(el1.credits === elo0.credits, "aucun crédit gagné ou perdu pour le match");
    const lb = (await (await fetch(API + "/leaderboard")).json()).find(r => r.pseudo === "alice"); ok(lb && true, "alice est toujours au classement");
    const duelHist = await (await fetch(API + "/duel/history")).json(); ok(duelHist.length === 0, "le match n'apparaît PAS dans l'historique des matchs 1v1 (aucun effet sur l'Elo ni les statistiques)");
  }
  console.log("\nerreurs JavaScript :", errors.length ? errors : "aucune"); ok(errors.length === 0, "aucune erreur JavaScript");
  console.log("BILAN TOURNOI (navigateur, phase " + PHASE + ") :", fails.length ? fails.length + " ÉCHEC(S) : " + JSON.stringify(fails) : "TOUT EST VERT"); await browser.close();
})().catch(e => { console.log("ECHEC DU TEST", e.message.split("\n")[0]); process.exit(1); });
