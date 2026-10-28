import { TEAM_NAMES, loadInjuries, loadNews, loadTransactions, nameKey } from "./news.js";
import { grade, gradeParlay, parlayOdds, profit, summarize, toAmerican, toDecimal } from "./grade.js";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (x, d = 1) => x == null || isNaN(x) ? "–" : (+x).toFixed(d);
const pct = (p, d = 0) => p == null ? "–" : (p * 100).toFixed(d) + "%";
const SHORT = { pts:"PTS", reb:"REB", ast:"AST", pra:"PRA", pr:"P+R", pa:"P+A", ra:"R+A", fg3m:"3PM",
  stl:"STL", blk:"BLK", stocks:"S+B", tov:"TOV", fgm:"FGM", fga:"FGA", ftm:"FTM", fta:"FTA",
  oreb:"OREB", dreb:"DREB", min:"MIN" };
// Team logos live in site/logos (scripts/fetch_logos.sh); four teams have a separate dark-mode version.
const DARK_LOGOS = new Set(["OKC", "PHI", "TOR", "UTA"]);
const logo = t => !/^[A-Z]{3}$/.test(t || "") ? "" : DARK_LOGOS.has(t)
  ? `<img class="logo has-d" src="logos/${t}.png" alt="" loading="lazy"><img class="logo d" src="logos/dark/${t}.png" alt="" loading="lazy">`
  : `<img class="logo" src="logos/${t}.png" alt="" loading="lazy">`;
// Headshots load straight from the NBA's image server by player id. If one is missing,
// or the server refuses it, the photo is removed and nothing shows in its place.
const face = (id, name, size = "") => `<span class="face ${size}" aria-hidden="true"><img
  src="https://cdn.nba.com/headshots/nba/latest/${size === "lg" ? "1040x760" : "260x190"}/${esc(id)}.png" alt="" loading="lazy"></span>`;
document.addEventListener("error", e => { if (e.target.matches?.(".face img")) e.target.parentNode.remove(); }, true);
// Injury status: the live ESPN report once it has loaded, otherwise what the morning build saw.
let INJ = null;  // Map of name key -> report entry
const injOf = (name, fallback) => INJ ? INJ.get(nameKey(name)) || null : fallback || null;
const backBy = d => d ? new Date(d + "T12:00:00").toLocaleDateString(undefined, { month:"short", day:"numeric" }) : "";
function injTag(i) {
  if (!i) return "";
  const out = i.status === "Out", label = out ? "Out" : i.status === "Day-To-Day" ? "DTD" : i.status;
  const tip = [i.status + (i.injury ? ` · ${i.injury}` : ""), i.return ? `Expected back ~${backBy(i.return)}` : "", i.note].filter(Boolean).map(esc).join("<br>");
  return `<span class="tag ${out ? "out" : "dtd"}" data-tip="${tip}">${esc(label)}</span>`;
}
// The player's injury tag, or the "missed recent games" flag when they aren't on the report.
const statusTag = (p, outLabel = "Likely out") => {
  const i = injOf(p.name, p.injury);
  return i ? injTag(i) : p.likely_out && !p.injury ? `<span class="tag out">${outLabel}</span>` : "";
};
const GROUPS = { main:["pts","reb","ast","fg3m","pra"], combos:["pra","pr","pa","ra","stocks"],
                 more:["stl","blk","tov","fgm","fga","ftm","fta","oreb","dreb"] };
let P, BT, PK = null, INDEX = [];
const S = {
  tab:"slate", game:null, group:"main", showOut:true,
  board:{ stat:"pra", sort:"gap", hideOut:true },
  desk:{ pid:null, stat:"pra", line:null, o:{ sign:-1, abs:"", x:"" }, u:{ sign:-1, abs:"", x:"" }, bet:{ side:null, stake:"1" } },
  file:{ id:null, stat:"pts", all:false, sort:{ col:"date", dir:-1 } },
  rec:{ stat:"pts" },
  user:null, bets:null,  // bets: null until loaded for the signed-in user
};
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch {} } };

// ---------- dates ----------
const today = new Date(); today.setHours(0, 0, 0, 0);
function dayLabel(d) {
  const dt = new Date(d + "T12:00:00"), diff = Math.round((dt - today) / 864e5);
  if (diff === 0) return "Tonight";
  if (diff === 1) return "Tomorrow";
  return dt.toLocaleDateString(undefined, { weekday:"short", month:"short", day:"numeric" });
}
function shortDay(d) {
  const dt = new Date(d + "T12:00:00"), diff = Math.round((dt - today) / 864e5);
  return diff === 0 ? "Tonight" : dt.toLocaleDateString(undefined, { weekday:"short" });
}
const tipTime = t => t ? new Date(t).toLocaleTimeString([], { hour:"numeric", minute:"2-digit" }) : "";
const longDate = d => new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday:"long", month:"long", day:"numeric" });

// ---------- distributions (negative binomial for counts, normal for minutes) ----------
function erf(x) {  // Abramowitz-Stegun 7.1.26
  const s = Math.sign(x); x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x));
}
function dist(stat, mu, param) {
  if (stat === "min") {
    const cdf = x => 0.5 * (1 + erf((x - mu) / (param * Math.SQRT2)));
    const q = p => { let lo = 0, hi = 60; for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; cdf(m) < p ? lo = m : hi = m; } return lo; };
    return { over:L => 1 - cdf(L), under:L => cdf(L), push:() => 0, q,
             bins() { const out = []; for (let k = Math.max(0, Math.floor(q(.005))); k <= Math.ceil(q(.995)); k++) out.push({ k, p:cdf(k + .5) - cdf(k - .5) }); return out; } };
  }
  const n = 1 / param, pr = n / (n + Math.max(mu, 1e-6));
  const pmf = [Math.exp(n * Math.log(pr))], kmax = Math.ceil(mu * 4 + 40);
  for (let k = 0; k < kmax; k++) pmf.push(pmf[k] * (k + n) / (k + 1) * (1 - pr));
  const cdf = []; pmf.reduce((a, v, i) => (cdf[i] = a + v), 0);
  const C = k => k < 0 ? 0 : k >= cdf.length ? 1 : cdf[k];
  const q = p => { const i = cdf.findIndex(c => c >= p); return i < 0 ? kmax : i; };
  return { over:L => 1 - C(Math.floor(L)), under:L => C(Math.ceil(L) - 1), push:L => Number.isInteger(L) ? (pmf[L] || 0) : 0, q,
           bins() { const out = []; for (let k = q(.005); k <= q(.995); k++) out.push({ k, p:pmf[k] }); return out; } };
}
const distOf = (p, s) => dist(s, p.proj[s][0], p.proj[s][1]);
const american = p => p <= 0 || p >= 1 ? "–" : p >= .5 ? "−" + Math.round(100 * p / (1 - p)) : "+" + Math.round(100 * (1 - p) / p);
const implied = o => o < 0 ? -o / (-o + 100) : 100 / (o + 100);
const payout = o => o > 0 ? o : 10000 / -o;  // profit on a $100 stake
// Odds are typed and shown either as American (−110) or as a payout multiplier (1.91x: the
// total returned per 1 staked), for apps that only show multipliers. Stored as American.
let oddsFmt = store.get("propsheet.oddsfmt") === "x" ? "x" : "us";
const showOdds = o => oddsFmt === "x" ? `${+toDecimal(o).toFixed(2)}x` : `${o > 0 ? "+" : "−"}${Math.abs(o)}`;
const fairOdds = p => oddsFmt === "x" ? (p <= 0 || p >= 1 ? "–" : `${+(1 / p).toFixed(2)}x`) : american(p);
const fromMult = v => { const m = parseFloat(String(v).replace(",", ".")); return m > 1 ? toAmerican(m) : NaN; };
const multText = o => String(+toDecimal(o).toFixed(2));
// Stand-in line: the half point where the player's recent form alone is closest to
// 50/50, like a book anchored on form would post (same rule as the model's picks).
function defaultLine(p, s) {
  const form = p.e5?.[s] ?? p.l10[s] ?? p.proj[s][0], D = dist(s, form, p.proj[s][1]);
  const base = Math.floor(form) + 0.5;
  return [base - 1, base, base + 1].filter(c => c > 0)
    .reduce((a, c) => Math.abs(D.over(c) - 0.5) < Math.abs(D.over(a) - 0.5) ? c : a, base);
}

// ---------- tooltip (any element with data-tip) ----------
const tip = $("tip");
function moveTip(e) {
  const t = e.target.closest?.("[data-tip]");
  if (!t) { tip.classList.remove("show"); return; }
  tip.innerHTML = t.dataset.tip;
  const r = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY - r.height - 12;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
  if (y < 8) y = e.clientY + 18;
  tip.style.left = x + "px"; tip.style.top = y + "px"; tip.classList.add("show");
}
document.addEventListener("pointermove", moveTip);
document.addEventListener("pointerdown", moveTip);
document.addEventListener("scroll", () => tip.classList.remove("show"), { passive:true });

// ---------- svg helpers ----------
function bar(x, y, w, h) {  // rounded top, square baseline
  if (h <= 0) return "";
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// Probability of every outcome, split at the line.
function distChart(stat, D, line) {
  const bins = D.bins(), W = 680, H = 220, pl = 6, pr = 6, pt = 26, pb = 26;
  const n = bins.length, bw = (W - pl - pr) / n, k0 = bins[0].k, maxp = Math.max(...bins.map(b => b.p));
  const x = k => pl + (k - k0) * bw, xv = v => pl + (v - k0 + .5) * bw, y = p => pt + (1 - p / maxp) * (H - pt - pb);
  const gap = bw > 6 ? 2 : 1, step = Math.max(1, Math.ceil(n / 9));
  let marks = "", hits = "", ticks = "";
  bins.forEach((b, i) => {
    const over = b.k > line, top = y(b.p);
    marks += `<path class="grow" style="animation-delay:${i * 8}ms" d="${bar(x(b.k) + gap / 2, top, bw - gap, H - pb - top)}" fill="var(${over ? "--over" : "--under"})"/>`;
    hits += `<rect x="${x(b.k)}" y="${pt}" width="${bw}" height="${H - pt - pb}" fill="transparent"
      data-tip="<b>${b.k} ${SHORT[stat]}</b> · ${pct(b.p, 1)} chance<br>${over ? "Over" : "Under"} ${line}"/>`;
    if (i % step === 0) ticks += `<text x="${x(b.k) + bw / 2}" y="${H - 8}" text-anchor="middle">${b.k}</text>`;
  });
  const lx = Math.min(Math.max(xv(line), pl), W - pr);
  return `<div class="chart"><svg class="wide" viewBox="0 0 ${W} ${H}" role="img" aria-label="Chance of each ${SHORT[stat]} outcome">
    ${marks}<line x1="${pl}" x2="${W - pr}" y1="${H - pb}" y2="${H - pb}" stroke="var(--ink)" stroke-width="1"/>
    <line x1="${lx}" x2="${lx}" y1="${pt - 8}" y2="${H - pb}" stroke="var(--ink)" stroke-width="2" stroke-dasharray="4 3"/>
    <text class="lbl" x="${lx}" y="${pt - 12}" text-anchor="middle">LINE ${line}</text>${ticks}${hits}</svg></div>`;
}

// Recent games as bars, with the projection (and optionally a line) as a rule.
function recentChart(games, stat, proj, line) {
  const W = 680, H = 200, pl = 28, pr = 8, pt = 18, pb = 24, n = games.length;
  const vals = games.map(g => g.v ?? 0), max = Math.max(...vals, proj || 0, line || 0, 1) * 1.08;
  const bw = (W - pl - pr) / n, y = v => pt + (1 - v / max) * (H - pt - pb);
  const ticks = [0, max / 2, max].map(v => Math.round(v));
  let out = ticks.map(t => `<line x1="${pl}" x2="${W - pr}" y1="${y(t)}" y2="${y(t)}" stroke="var(--rule)" stroke-width="1"/>
    <text x="${pl - 6}" y="${y(t) + 4}" text-anchor="end">${t}</text>`).join("");
  games.forEach((g, i) => {
    const top = y(g.v ?? 0), cls = line != null ? (g.v > line ? "--over" : "--under") : "--ink-2";
    out += `<path class="grow" style="animation-delay:${i * 18}ms" d="${bar(pl + i * bw + 2, top, bw - 4, H - pb - top)}" fill="var(${cls})"/>
      <rect x="${pl + i * bw}" y="${pt}" width="${bw}" height="${H - pt - pb}" fill="transparent"
        data-tip="<b>${fmt(g.v, stat === "min" ? 1 : 0)} ${SHORT[stat]}</b><br>${esc(g.date)} ${g.home ? "vs" : "@"} ${esc(g.opp)}"/>`;
  });
  const rule = (v, label, dash) => v == null ? "" : `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="var(--ink)" stroke-width="2" ${dash ? 'stroke-dasharray="5 4"' : ""}/>
    <text class="lbl" x="${W - pr}" y="${y(v) - 5}" text-anchor="end">${label}</text>`;
  out += `<line x1="${pl}" x2="${W - pr}" y1="${H - pb}" y2="${H - pb}" stroke="var(--ink)"/>`;
  out += rule(proj, `NEXT GAME ${fmt(proj)}`, true) + (line != null ? rule(line, `LINE ${line}`, false) : "");
  out += `<text x="${pl}" y="${H - 6}">${esc(games[0]?.date || "")}</text><text x="${W - pr}" y="${H - 6}" text-anchor="end">${esc(games[n - 1]?.date || "")}</text>`;
  return `<div class="chart"><svg class="wide" viewBox="0 0 ${W} ${H}" role="img" aria-label="Last ${n} games">${out}</svg></div>`;
}

// Model probability vs how often it actually happened.
function calibChart(cal) {
  const W = 420, H = 340, pl = 40, pr = 12, pt = 12, pb = 36;
  const x = v => pl + v * (W - pl - pr), y = v => pt + (1 - v) * (H - pt - pb);
  let out = [0, .25, .5, .75, 1].map(t => `<line x1="${pl}" x2="${W - pr}" y1="${y(t)}" y2="${y(t)}" stroke="var(--rule)"/>
    <text x="${pl - 6}" y="${y(t) + 4}" text-anchor="end">${t * 100}%</text>
    <text x="${x(t)}" y="${H - 18}" text-anchor="middle">${t * 100}%</text>`).join("");
  out += `<line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="var(--muted)" stroke-dasharray="4 4"/>
    <text x="${x(.9)}" y="${y(.9) + 18}" text-anchor="end">perfect</text>`;
  out += cal.map(c => `<circle cx="${x(c.p)}" cy="${y(c.hit)}" r="${4 + Math.min(4, Math.sqrt(c.n) / 40)}" fill="var(--over)" stroke="var(--card)" stroke-width="2"/>
    <circle cx="${x(c.p)}" cy="${y(c.hit)}" r="14" fill="transparent" data-tip="Model said <b>${pct(c.p, 1)}</b><br>Over hit <b>${pct(c.hit, 1)}</b><br>${c.n.toLocaleString()} games"/>`).join("");
  out += `<text x="${(pl + W - pr) / 2}" y="${H - 2}" text-anchor="middle">MODEL'S P(OVER)</text>
    <text transform="translate(11 ${(pt + H - pb) / 2}) rotate(-90)" text-anchor="middle">ACTUALLY HIT</text>`;
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Calibration">${out}</svg></div>`;
}

// ---------- player files (lazy, cached) ----------
const files = new Map();
const getFile = id => files.get(id) || files.set(id, fetch(`players/${id}.json`).then(r => r.json())).get(id);
const fileRows = f => f.log.map(r => Object.fromEntries(f.cols.map((c, i) => [c, r[i]])));

// ---------- navigation ----------
$("nav").addEventListener("click", e => { const b = e.target.closest("button[data-tab]"); if (b) go(b.dataset.tab); });
function go(tab) {
  S.tab = tab;
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  document.querySelectorAll("main > section").forEach(s => s.classList.toggle("hidden", s.id !== "tab-" + tab));
  ({ slate:renderSlate, board:renderBoard, desk:renderDesk, files:renderFiles, record:renderRecord, bets:renderBets, picks:renderPicks, news:renderNews })[tab]();
  history.replaceState(null, "", "#" + tab);
  renderParlayBar();
}
function openDesk(pid, stat, line) {
  S.desk.pid = pid; S.desk.stat = stat; S.desk.line = line ?? null; go("desk");
  scrollTo({ top:0, behavior:"smooth" });
}
function openFile(id) { S.file.id = id; S.file.all = false; go("files"); scrollTo({ top:0, behavior:"smooth" }); }

// ---------- theme ----------
const THEMES = ["auto", "light", "dark"];
function applyTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  $("theme").textContent = { auto:"Auto", light:"Day ed.", dark:"Night ed." }[t];
}
let theme = store.get("theme") || "auto"; applyTheme(theme);
$("theme").onclick = () => { theme = THEMES[(THEMES.indexOf(theme) + 1) % 3]; store.set("theme", theme); applyTheme(theme); };

// ==================== TONIGHT'S SLATE ====================
function renderSlate() {
  const el = $("tab-slate");
  if (!P.games.length) { el.innerHTML = `<p class="deck">No games on the schedule. Check back closer to the next game day.</p>`; return; }
  const g = P.games.find(x => x.game_id === S.game) || P.games[0]; S.game = g.game_id;
  const fav = g.home_spread == null ? "" : g.home_spread <= 0 ? `${g.home} −${Math.abs(g.home_spread)}` : `${g.away} −${g.home_spread}`;
  const stats = GROUPS[S.group];
  const team = code => {
    let ps = P.players.filter(p => p.game_id === g.game_id && p.team === code);
    if (!S.showOut) ps = ps.filter(p => !p.likely_out);
    ps.sort((a, b) => a.likely_out - b.likely_out || b.proj.min[0] - a.proj.min[0]);
    return `<div><h3 class="sub"><span>${logo(code)} ${code}</span><small>${code === g.home ? "Home" : "Away"} · ${ps.length} players</small></h3>
      <div class="scroll"><table class="agate stack"><tr><th>Player</th><th>Min</th>${stats.map(s => `<th>${SHORT[s]}</th>`).join("")}</tr>
      ${ps.map(p => `<tr class="click ${p.likely_out ? "dim" : ""}" data-pid="${p.id}">
        <td>${face(p.id, p.name)}<span class="pname">${esc(p.name)}</span>${statusTag(p)}</td>
        <td>${fmt(p.proj.min[0], 0)}<span class="minbar"><i style="width:${Math.min(100, p.proj.min[0] / 40 * 100)}%"></i></span></td>
        ${stats.map(s => { const d = p.proj[s][0] - (p.l10[s] ?? p.proj[s][0]);
          return `<td data-tip="${SHORT[s]}: projected <b>${fmt(p.proj[s][0])}</b><br>Last 10: ${fmt(p.l10[s])} · Season: ${fmt(p.sea[s])}">
            <span class="proj">${fmt(p.proj[s][0])}</span><span class="delta">${Math.abs(d) < .05 ? "" : (d > 0 ? "▲" : "▼") + fmt(Math.abs(d))}</span></td>`; }).join("")}
      </tr>`).join("")}</table></div></div>`;
  };
  el.innerHTML = `<div class="reveal">
    <div><p class="kicker">The slate</p><h2 class="head">Next game for all 30 teams</h2>
      <p class="deck">Projections for every rotation player. ▲▼ shows how the projection compares with the player's last 10 games. Tap a player to price a line.</p></div>
    <div class="slate" id="slate">${P.games.map(x => `<button class="ticket ${x.game_id === g.game_id ? "on" : ""}" data-g="${x.game_id}">
        <div class="day">${shortDay(x.date)}${x.tip ? " · " + tipTime(x.tip) : ""}</div>
        <div class="match"><span>${logo(x.away)}${x.away}</span><em>@</em><span>${logo(x.home)}${x.home}</span></div>
        <div class="line">${x.home_spread == null ? "&nbsp;" : "Elo: " + (x.home_spread <= 0 ? `${x.home} −${Math.abs(x.home_spread)}` : `${x.away} −${x.home_spread}`)}</div>
      </button>`).join("")}</div>
    <div class="gamehead">
      <div><p class="kicker">${dayLabel(g.date)}${g.tip ? " · " + tipTime(g.tip) : ""}</p>
        <h2 class="head">${logo(g.away)} ${g.away} at ${logo(g.home)} ${g.home}</h2>
        <p class="note" style="margin:6px 0 0">${longDate(g.date)}${fav ? ` · Elo favorite: ${fav}` : ""}</p></div>
      <div class="controls" style="margin:0">
        <div class="seg" id="groups">${Object.keys(GROUPS).map(k => `<button data-k="${k}" class="${k === S.group ? "on" : ""}">${{ main:"Main", combos:"Combos", more:"More" }[k]}</button>`).join("")}</div>
        <label class="check"><input type="checkbox" id="showout" ${S.showOut ? "checked" : ""}> Show likely out</label>
      </div>
    </div>
    <div class="teams">${team(g.away)}${team(g.home)}</div>
  </div>`;
  $("slate").onclick = e => { const b = e.target.closest(".ticket"); if (b) { S.game = b.dataset.g; renderSlate(); } };
  $("groups").onclick = e => { const b = e.target.closest("button"); if (b) { S.group = b.dataset.k; renderSlate(); } };
  $("showout").onchange = e => { S.showOut = e.target.checked; renderSlate(); };
  el.querySelectorAll("tr[data-pid]").forEach(tr => tr.onclick = () => openDesk(tr.dataset.pid, GROUPS[S.group][0]));
  const on = el.querySelector(".ticket.on"); on?.scrollIntoView({ block:"nearest", inline:"nearest" });
}

// ==================== THE BOARD ====================
function renderBoard() {
  const b = S.board, el = $("tab-board");
  const rows = P.players.filter(p => !(b.hideOut && p.likely_out) && p.l10[b.stat] != null).map(p => {
    const line = defaultLine(p, b.stat), D = distOf(p, b.stat), over = D.over(line), under = D.under(line);
    return { p, line, over, under, mu:p.proj[b.stat][0], gap:p.proj[b.stat][0] - p.l10[b.stat] };
  });
  const key = { gap:r => -Math.abs(r.gap), over:r => -r.over, under:r => -r.under, proj:r => -r.mu }[b.sort];
  rows.sort((a, c) => key(a) - key(c));
  el.innerHTML = `<div class="reveal">
    <div><p class="kicker">The board</p><h2 class="head">Where the model disagrees with recent form</h2>
      <p class="deck">Every projected player in one market. The line shown is a stand-in: the player's last-10 average rounded to the half point. Open a row in the Line Desk and type your book's line for the real price.</p></div>
    <div class="controls">
      <div class="field" style="min-width:200px"><label>Market</label><select id="bstat">${P.targets.map(t => `<option value="${t}" ${t === b.stat ? "selected" : ""}>${P.labels[t]}</option>`).join("")}</select></div>
      <div class="field"><label>Sort by</label><div class="seg" id="bsort">${[["gap", "Biggest gap"], ["over", "Over"], ["under", "Under"], ["proj", "Projection"]].map(([k, l]) => `<button data-k="${k}" class="${k === b.sort ? "on" : ""}">${l}</button>`).join("")}</div></div>
      <label class="check" style="margin-top:18px"><input type="checkbox" id="bout" ${b.hideOut ? "checked" : ""}> Hide likely out</label>
    </div>
    <div class="scroll"><table class="agate">
      <tr><th>Player</th><th>Game</th><th>Proj</th><th>Last 10</th><th>Season</th><th>Gap</th><th>Line</th><th style="text-align:left">P(over) · lean</th><th><span class="sr">Parlay</span></th></tr>
      ${rows.slice(0, 80).map(r => { const lean = r.over >= r.under ? ["o", "Over", r.over] : ["u", "Under", r.under];
        return `<tr class="click" data-pid="${r.p.id}" data-line="${r.line}">
        <td>${face(r.p.id, r.p.name)}<span class="pname">${esc(r.p.name)}</span> <span class="muted">${logo(r.p.team)}${r.p.team}</span>${statusTag(r.p, "Out?")}</td>
        <td class="muted">${r.p.home ? "vs" : "@"} ${logo(r.p.opp)}${r.p.opp} · ${dayLabel(r.p.date)}</td>
        <td class="proj">${fmt(r.mu)}</td><td>${fmt(r.p.l10[b.stat])}</td><td>${fmt(r.p.sea[b.stat])}</td>
        <td>${r.gap > 0 ? "+" : ""}${fmt(r.gap)}</td><td>${r.line}</td>
        <td style="text-align:left"><span class="pbar" data-tip="Over ${pct(r.over, 1)} · Under ${pct(r.under, 1)}"><i style="width:${r.over * 100}%"></i></span><span class="lean ${lean[0]}">${lean[1]} ${pct(lean[2])}</span></td>
        <td>${addBtn(r.p, b.stat, r.line, lean[1].toLowerCase(), lean[2])}</td></tr>`; }).join("")}
    </table></div>
    <p class="note">Showing ${Math.min(80, rows.length)} of ${rows.length} players. Small gaps are noise: single-game stats swing a lot, so look for big disagreements. Tap + to add the model's lean to your parlay at −110; set your book's odds on the Line Desk.</p>
  </div>`;
  $("bstat").onchange = e => { b.stat = e.target.value; renderBoard(); };
  $("bsort").onclick = e => { const x = e.target.closest("button"); if (x) { b.sort = x.dataset.k; renderBoard(); } };
  $("bout").onchange = e => { b.hideOut = e.target.checked; renderBoard(); };
  el.querySelectorAll("tr[data-pid]").forEach(tr => tr.onclick = () => openDesk(tr.dataset.pid, b.stat, +tr.dataset.line));
  wireAddBtns(el);
}

// ==================== LINE DESK ====================
function renderDesk() {
  const d = S.desk, el = $("tab-desk");
  if (!P.players.length) { el.innerHTML = `<p class="deck">No projections right now.</p>`; return; }
  if (!P.players.some(p => p.id === d.pid)) d.pid = [...P.players].sort((a, b) => b.proj.pra[0] - a.proj.pra[0])[0].id;
  const p = P.players.find(x => x.id === d.pid);
  if (d.line == null) d.line = defaultLine(p, d.stat);
  const byGame = {};
  [...P.players].sort((a, b) => a.name.localeCompare(b.name)).forEach(x => (byGame[x.game_id] ||= []).push(x));
  el.innerHTML = `<div class="reveal">
    <div><p class="kicker">The line desk</p><h2 class="head">Price any prop</h2>
      <p class="deck">Pick a player and market, then type your sportsbook's line. Add the odds to see whether the bet has value.</p></div>
    <div class="desk">
      <div class="desk-form">
        <div class="field"><label>Player</label><select id="dp">${P.games.map(g => byGame[g.game_id] ? `<optgroup label="${g.away} @ ${g.home} · ${dayLabel(g.date)}">
          ${byGame[g.game_id].map(x => `<option value="${x.id}" ${x.id === d.pid ? "selected" : ""}>${esc(x.name)} (${x.team})${x.likely_out ? " – likely out" : ""}</option>`).join("")}</optgroup>` : "").join("")}</select></div>
        <div class="field"><label>Market</label><select id="ds">${P.targets.map(t => `<option value="${t}" ${t === d.stat ? "selected" : ""}>${P.labels[t]}</option>`).join("")}</select></div>
        <div class="field"><label>Line</label><div class="stepper"><button type="button" id="dminus" aria-label="Lower line">−</button>
          <input id="dl" type="number" step="0.5" inputmode="decimal" value="${d.line}"><button type="button" id="dplus" aria-label="Raise line">+</button></div></div>
        <div class="field"><label>Your book shows</label><div class="seg" id="ofmt">
          <button type="button" data-f="us" class="${oddsFmt === "us" ? "on" : ""}">Odds (−110)</button><button type="button" data-f="x" class="${oddsFmt === "x" ? "on" : ""}">Multiplier (1.9x)</button></div></div>
        <div class="two">
          ${["o", "u"].map(k => oddsFmt === "x"
            ? `<div class="field"><label>${k === "o" ? "Over" : "Under"} payout</label><div class="mult">
            <input data-k="${k}" inputmode="decimal" placeholder="1.91" value="${esc(d[k].x)}" aria-label="${k === "o" ? "Over" : "Under"} payout multiplier"><span aria-hidden="true">x</span></div></div>`
            : `<div class="field"><label>${k === "o" ? "Over" : "Under"} odds</label><div class="odds">
            <button type="button" class="sign" data-k="${k}" aria-label="Switch plus or minus">${d[k].sign < 0 ? "−" : "+"}</button>
            <input data-k="${k}" inputmode="numeric" pattern="[0-9]*" placeholder="110" value="${esc(d[k].abs)}" aria-label="${k === "o" ? "Over" : "Under"} odds"></div></div>`).join("")}
        </div>
        <p class="note" style="margin:0">${oddsFmt === "x"
          ? "Payout multiplier: what you get back for each 1 you stake, including the stake (1.91x is the same as −110; 2x is even money). Leave it blank if you don't know it."
          : "American odds: tap the sign to switch between − and +, then type the number (−110, +125)."} With both sides entered, the book's margin is removed before comparing.</p>
        <div id="parlay"></div>
      </div>
      <div id="slip"></div>
    </div></div>`;
  $("dp").onchange = e => { d.pid = e.target.value; d.line = null; d.bet.side = null; renderDesk(); };
  $("ds").onchange = e => { d.stat = e.target.value; d.line = null; d.bet.side = null; renderDesk(); };
  const setLine = v => { if (!isNaN(v)) { d.line = Math.max(0, v); $("dl").value = d.line; renderSlip(); } };
  $("dminus").onclick = () => setLine((+$("dl").value || 0) - .5);
  $("dplus").onclick = () => setLine((+$("dl").value || 0) + .5);
  $("dl").oninput = e => setLine(parseFloat(e.target.value));
  $("ofmt").onclick = e => {
    const b = e.target.closest("button"); if (!b || b.dataset.f === oddsFmt) return;
    const val = k => oddsFmt === "x" ? fromMult(d[k].x) : d[k].abs ? d[k].sign * +d[k].abs : NaN;
    for (const k of ["o", "u"]) {  // carry what's typed over to the other format
      const o = val(k);
      if (Math.abs(o) >= 100) { d[k].x = multText(o); d[k].sign = Math.sign(o); d[k].abs = String(Math.abs(o)); }
    }
    const po = parlayCustom();
    if (Math.abs(po) >= 100) { parlay.odds.x = multText(po); parlay.odds.sign = Math.sign(po); parlay.odds.abs = String(Math.abs(po)); }
    oddsFmt = b.dataset.f; store.set("propsheet.oddsfmt", oddsFmt); saveParlay(); renderDesk();
  };
  $("tab-desk").querySelectorAll(".mult input").forEach(inp => inp.oninput = () => {
    d[inp.dataset.k].x = inp.value.replace(/[^\d.,]/g, ""); renderSlip(); });
  $("tab-desk").querySelectorAll(".odds .sign").forEach(b => b.onclick = () => {
    const o = d[b.dataset.k]; o.sign = -o.sign; b.textContent = o.sign < 0 ? "−" : "+"; renderSlip(); });
  $("tab-desk").querySelectorAll(".odds input").forEach(inp => inp.oninput = () => {
    const o = d[inp.dataset.k], v = inp.value.trim();
    if (/^[-−]/.test(v)) o.sign = -1; else if (/^\+/.test(v)) o.sign = 1;  // typed on a keyboard
    o.abs = v.replace(/\D/g, "");
    if (inp.value !== o.abs) inp.value = o.abs;
    inp.previousElementSibling.textContent = o.sign < 0 ? "−" : "+";
    renderSlip(); });
  renderSlip();
  renderParlay();
}

function renderSlip() {
  const d = S.desk, p = P.players.find(x => x.id === d.pid), s = d.stat, L = d.line;
  const D = distOf(p, s), over = D.over(L), under = D.under(L), push = D.push(L), mu = p.proj[s][0];
  const read = k => oddsFmt === "x" ? fromMult(d[k].x) : d[k].abs ? d[k].sign * +d[k].abs : NaN;
  const oo = read("o"), uo = read("u");
  const has = o => !isNaN(o) && Math.abs(o) >= 100;
  let ev = "";
  if (has(oo) || has(uo)) {
    const fairO = has(oo) && has(uo) ? implied(oo) / (implied(oo) + implied(uo)) : null;
    const side = (o, pw, pl, name) => {
      if (!has(o)) return "";
      const e = pw * payout(o) - pl * 100, book = fairO == null ? implied(o) : (name === "Over" ? fairO : 1 - fairO);
      return `<div><span class="muted">${name} ${showOdds(o)}</span><br>
        <b class="${e > 0 ? "pos" : "neg"}">${e > 0 ? "▲ +" : "▼ −"}$${Math.abs(e).toFixed(2)}</b> per $100 <span class="muted">· ${e > 0 ? "value" : "no value"}</span><br>
        <span class="muted">Model ${pct(pw, 1)} vs book ${pct(book, 1)}${fairO == null ? "" : " (no-vig)"}</span></div>`;
    };
    ev = `<div class="ev">${side(oo, over, under, "Over")}${side(uo, under, over, "Under")}</div>`;
  }
  // Default side: the one with value if odds are in, otherwise the model's lean.
  const evOf = (o, pw, pl) => has(o) ? pw * payout(o) - pl * 100 : null;
  const evO = evOf(oo, over, under), evU = evOf(uo, under, over);
  const lean = evO != null && evU != null ? (evO >= evU ? "over" : "under") : over >= under ? "over" : "under";
  const bs = d.bet.side || lean;
  const bodds = bs === "over" ? oo : uo;
  const betbox = `<div class="betbox">
      <div class="field"><label>Your bet</label><div class="seg" id="bside">
        <button data-s="over" class="${bs === "over" ? "on" : ""}">Over ${L}</button><button data-s="under" class="${bs === "under" ? "on" : ""}">Under ${L}</button></div></div>
      <div class="field"><label>Stake (units)</label><input id="bstake" inputmode="decimal" value="${esc(d.bet.stake)}"></div>
      <div class="bbtns"><button class="btn accent" id="bsave" type="button">Save to My Bets</button>
        <button class="btn line" id="badd" type="button">${inParlay(p.id, s) ? "Update parlay leg" : "+ Add to parlay"}</button></div>
      <div class="bnote"><div class="small-note" id="bmsg">${has(bodds) ? `At ${showOdds(bodds)}` : `No odds entered: saved at ${showOdds(-110)}`}</div></div>
    </div>`;
  $("slip").innerHTML = `<div class="slip">
    <div class="slip-top">
      <div class="slip-who">${face(p.id, p.name, "md")}<span>${esc(p.name)} · ${logo(p.team)}${p.team} ${p.home ? "vs" : "@"} ${logo(p.opp)}${p.opp} · ${dayLabel(p.date)} · ${P.labels[s]}</span></div>
      <div class="split">
        <div class="side o"><div class="lab">Over ${L}</div><div class="big">${pct(over)}</div><div class="fair">Fair ${oddsFmt === "x" ? "payout" : "odds"} ${fairOdds(over)}</div></div>
        <div class="side u"><div class="lab">Under ${L}</div><div class="big">${pct(under)}</div><div class="fair">Fair ${oddsFmt === "x" ? "payout" : "odds"} ${fairOdds(under)}${push > .001 ? ` · push ${pct(push, 1)}` : ""}</div></div>
      </div>
      <div class="splitbar" aria-hidden="true"><i style="width:${over * 100}%;background:var(--over)"></i><i style="width:${under * 100}%;background:var(--under)"></i></div>
    </div>
    <div class="slip-body">
      ${(i => i ? `<div class="warn"><b>${esc(i.status)}${i.injury ? ` (${esc(i.injury)})` : ""}.</b> ${esc(i.note)}${i.return ? ` Expected back around ${backBy(i.return)}.` : ""}</div>`
        : p.likely_out ? `<div class="warn"><b>Likely out.</b> ${esc(p.name)} has missed their team's last 3+ games. Check the injury report before betting.</div>` : "")(injOf(p.name, p.injury))}
      ${ev}
      ${betbox}
      <div class="facts">
        <div class="fact"><div class="k">Projection</div><div class="v">${fmt(mu)}</div><div class="s">median ${fmt(D.q(.5), 0)}</div></div>
        <div class="fact"><div class="k">80% range</div><div class="v">${fmt(D.q(.1), 0)}–${fmt(D.q(.9), 0)}</div><div class="s">8 games in 10 land here</div></div>
        <div class="fact"><div class="k">Last 10</div><div class="v">${fmt(p.l10[s])}</div><div class="s">season ${fmt(p.sea[s])}</div></div>
        <div class="fact"><div class="k">Minutes</div><div class="v">${fmt(p.proj.min[0], 0)}</div><div class="s">projected</div></div>
      </div>
      <div class="legend"><span><i style="background:var(--over)"></i>Over ${L}</span><span><i style="background:var(--under)"></i>Under</span><span class="muted">Chance of each outcome</span></div>
      ${distChart(s, D, L)}
      <h3 class="sub" style="margin-top:18px">Recent games vs ${L}<small id="hitrate"></small></h3>
      <div class="recent" id="recent"><span class="muted" style="font-weight:400">Loading…</span></div>
      <p class="note">The model can't see injury news or tonight's starting lineups. Treat edges under ~5 points as noise.</p>
    </div></div>`;
  $("bside").onclick = e => { const b = e.target.closest("button"); if (b) { d.bet.side = b.dataset.s; renderSlip(); } };
  $("bstake").oninput = e => { d.bet.stake = e.target.value; };
  const leg = { side:bs, odds:has(bodds) ? bodds : -110, modelP:bs === "over" ? over : under, mu };
  $("bsave").onclick = () => saveCurrentBet({ p, s, L, ...leg });
  $("badd").onclick = () => { addLeg(betOf({ p, s, L, ...leg })); renderSlip(); renderParlay();
    $("parlay").scrollIntoView({ behavior:"smooth", block:"nearest" }); };
  getFile(p.id).then(f => {
    if (S.desk.pid !== p.id || S.desk.stat !== s || S.desk.line !== L) return;
    const rows = fileRows(f), last = rows.slice(-10), season = rows.filter(r => r.date >= (f.seasons.at(-1)?.season.slice(0, 4) + "-08-01"));
    const hit = last.filter(r => r[s] > L).length, sh = season.filter(r => r[s] > L).length;
    $("hitrate").textContent = `Over in ${hit} of last ${last.length}` + (season.length ? ` · ${sh}/${season.length} this season` : "");
    $("recent").innerHTML = last.map(r => `<span class="${r[s] > L ? "o" : "u"}" data-tip="${esc(r.date)} ${r.home ? "vs" : "@"} ${esc(r.opp)}<br>${fmt(r.min, 0)} min">${fmt(r[s], 0)}</span>`).join("")
      + `<button class="more" style="margin:0 0 0 8px" id="tofile">Player file →</button>`;
    $("tofile").onclick = () => openFile(p.id);
  }).catch(() => { $("recent").innerHTML = `<span class="muted">No game log available.</span>`; });
}

// ==================== PLAYER FILES ====================
function renderFiles() {
  const el = $("tab-files");
  el.innerHTML = `<div class="reveal">
    <div><p class="kicker">Player files</p><h2 class="head">Every player since 2018–19</h2>
      <p class="deck">Season averages, the full game log and recent form for ${INDEX.length.toLocaleString()} players.</p></div>
    <div class="finder"><input class="search" id="q" placeholder="Search a player…" autocomplete="off" aria-label="Search players"><div class="sugg hidden" id="sugg"></div></div>
    <div id="file"></div></div>`;
  const q = $("q"), sugg = $("sugg");
  let act = 0, hits = [];
  const norm = s => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const draw = () => {
    sugg.innerHTML = hits.map((h, i) => `<button data-id="${h[0]}" class="${i === act ? "act" : ""}">${esc(h[1])}<small>${h[2]} · ${h[3]}</small></button>`).join("");
    sugg.classList.toggle("hidden", !hits.length);
  };
  q.oninput = () => {
    const t = norm(q.value.trim()); act = 0;
    hits = t ? INDEX.filter(h => norm(h[1]).includes(t)).sort((a, b) => norm(a[1]).startsWith(t) ? -1 : norm(b[1]).startsWith(t) ? 1 : 0).slice(0, 8) : [];
    draw();
  };
  q.onkeydown = e => {
    if (e.key === "ArrowDown") { act = Math.min(act + 1, hits.length - 1); draw(); e.preventDefault(); }
    if (e.key === "ArrowUp") { act = Math.max(act - 1, 0); draw(); e.preventDefault(); }
    if (e.key === "Enter" && hits[act]) { pick(hits[act][0]); }
    if (e.key === "Escape") { hits = []; draw(); }
  };
  sugg.onclick = e => { const b = e.target.closest("button"); if (b) pick(b.dataset.id); };
  const pick = id => { hits = []; draw(); q.value = ""; S.file.id = id; S.file.all = false; drawFile(); };
  if (!S.file.id) S.file.id = [...P.players].sort((a, b) => b.proj.pts[0] - a.proj.pts[0])[0]?.id;
  drawFile();
}

function drawFile() {
  const id = S.file.id, box = $("file");
  if (!id) return;
  box.innerHTML = `<p class="note">Pulling the file…</p>`;
  getFile(id).then(f => {
    if (S.file.id !== id || S.tab !== "files") return;
    const nxt = P.players.find(p => p.id === id), st = S.file.stat, rows = fileRows(f);
    const recent = rows.slice(-20).map(r => ({ v:r[st], date:r.date, opp:r.opp, home:r.home }));
    const seasonCols = ["gp", "min", "pts", "reb", "ast", "pra", "fg3m", "stl", "blk", "tov", "fg_pct", "fg3_pct", "ft_pct"];
    const logCols = ["date", "opp", "min", "pts", "reb", "ast", "pra", "fg3m", "stl", "blk", "tov", "fgm", "fga", "fg3a", "ftm", "fta", "plus_minus"];
    const H = c => ({ gp:"GP", fg_pct:"FG%", fg3_pct:"3P%", ft_pct:"FT%", plus_minus:"+/−", date:"Date", opp:"Opp", fg3a:"3PA" }[c] || SHORT[c] || c);
    const so = S.file.sort;
    const sorted = [...rows].sort((a, b) => (a[so.col] > b[so.col] ? 1 : a[so.col] < b[so.col] ? -1 : 0) * so.dir);
    const shown = S.file.all ? sorted : sorted.slice(0, 25);
    box.innerHTML = `<div class="reveal">
      <div class="profile"><div class="who">${face(id, f.name, "lg")}<div class="nm">${esc(f.name)}</div></div>
        <div class="tm">${logo(f.team)} ${esc(f.team)}<span class="muted" style="font:500 13px var(--ui);letter-spacing:.06em"> · ${f.seasons.length} seasons · ${rows.length} games</span></div></div>
      ${nxt ? `<p class="note">Next: ${nxt.home ? "vs" : "@"} ${logo(nxt.opp)}${nxt.opp}, ${dayLabel(nxt.date)}${nxt.likely_out ? ' <span class="tag out">Likely out</span>' : ""}</p>
        <div class="tiles">${["pts", "reb", "ast", "pra", "fg3m", "min"].map(s => `<div class="fact"><div class="k">${SHORT[s]}</div><div class="v">${fmt(nxt.proj[s][0])}</div><div class="s">L10 ${fmt(nxt.l10[s])}</div></div>`).join("")}</div>` : `<p class="note">No game on the schedule this week.</p>`}
      <div>
        <h3 class="sub">Last ${recent.length} games<small><span class="seg" id="fstat">${["pts", "reb", "ast", "pra", "fg3m", "min"].map(s => `<button data-s="${s}" class="${s === st ? "on" : ""}">${SHORT[s]}</button>`).join("")}</span></small></h3>
        ${recentChart(recent, st, nxt ? nxt.proj[st][0] : null, null)}
        ${nxt ? `<button class="more" id="fdesk">Price a ${SHORT[st]} line →</button>` : ""}
      </div>
      <div><h3 class="sub">Season by season<small>per game</small></h3>
        <div class="scroll"><table class="agate"><tr><th>Season</th><th>Team</th>${seasonCols.map(c => `<th>${H(c)}</th>`).join("")}</tr>
        ${[...f.seasons].reverse().map(s => `<tr><td><b>${s.season}</b></td><td>${esc(s.team)}</td>${seasonCols.map(c =>
          `<td>${c.endsWith("pct") ? (s[c] == null ? "–" : (s[c] * 100).toFixed(1)) : c === "gp" ? s[c] : fmt(s[c])}</td>`).join("")}</tr>`).join("")}</table></div></div>
      <div><h3 class="sub">Game log<small>tap a header to sort</small></h3>
        <div class="scroll"><table class="agate" id="flog"><tr>${logCols.map(c => `<th class="sortable" data-c="${c}">${H(c)}${c === so.col ? (so.dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr>
        ${shown.map(r => `<tr>${logCols.map(c => `<td>${c === "opp" ? (r.home ? "vs " : "@ ") + esc(r.opp) : c === "date" ? esc(r.date) : c === "min" ? fmt(r[c], 0) : r[c] ?? "–"}</td>`).join("")}</tr>`).join("")}</table></div>
        ${rows.length > 25 ? `<button class="more" id="fall">${S.file.all ? "Show fewer" : `Show all ${rows.length} games`}</button>` : ""}</div>
    </div>`;
    $("fstat").onclick = e => { const b = e.target.closest("button"); if (b) { S.file.stat = b.dataset.s; drawFile(); } };
    $("flog").querySelector("tr").onclick = e => { const th = e.target.closest("th"); if (!th) return; const c = th.dataset.c;
      S.file.sort = { col:c, dir:so.col === c ? -so.dir : -1 }; drawFile(); };
    if ($("fall")) $("fall").onclick = () => { S.file.all = !S.file.all; drawFile(); };
    if ($("fdesk")) $("fdesk").onclick = () => openDesk(id, st);
  }).catch(() => { box.innerHTML = `<p class="note">Couldn't load that player's file.</p>`; });
}

// ==================== TRACK RECORD ====================
function renderRecord() {
  const el = $("tab-record");
  if (!BT) { el.innerHTML = `<p class="deck">No backtest published yet. Run <code>python -m scripts.build_props --backtest</code>.</p>`; return; }
  const T = BT.targets, best = m => Math.min(m.mae_season_avg, m.mae_last10, m.mae_ewm5);
  const gain = m => (best(m) - m.mae) / best(m);
  const st = S.rec.stat;
  el.innerHTML = `<div class="reveal">
    <div><p class="kicker">Track record</p><h2 class="head">How it did on ${T.pts.n.toLocaleString()} past games</h2>
      <p class="deck">Seasons ${BT.seasons[0]} through ${BT.seasons.at(-1)}, each predicted only from earlier seasons. The model is compared with three things a bettor might use instead: the season average, the last-10 average and recent form.</p></div>
    <div class="scoreline">
      <div class="fact"><div class="k">Points, avg miss</div><div class="v">${fmt(T.pts.mae, 2)}</div><div class="s">best simple avg ${fmt(best(T.pts), 2)}</div></div>
      <div class="fact"><div class="k">PRA, avg miss</div><div class="v">${fmt(T.pra.mae, 2)}</div><div class="s">best simple avg ${fmt(best(T.pra), 2)}</div></div>
      <div class="fact"><div class="k">Minutes, avg miss</div><div class="v">${fmt(T.min.mae, 2)}</div><div class="s">best simple avg ${fmt(best(T.min), 2)}</div></div>
      <div class="fact"><div class="k">Markets beating baseline</div><div class="v">${P.targets.filter(t => T[t] && gain(T[t]) > 0).length}/${P.targets.filter(t => T[t]).length}</div><div class="s">by average miss</div></div>
    </div>
    <div><h3 class="sub">Every market<small>lower miss is better</small></h3>
      <div class="scroll"><table class="agate"><tr><th>Market</th><th>Model miss</th><th>Season avg</th><th>Last 10</th><th>Recent form</th><th>Gain</th><th>Brier</th><th>Coin flip</th></tr>
      ${P.targets.filter(t => T[t]).map(t => { const m = T[t], g = gain(m);
        return `<tr class="click" data-t="${t}"><td><span class="pname">${P.labels[t]}</span></td><td class="proj">${fmt(m.mae, 2)}</td><td>${fmt(m.mae_season_avg, 2)}</td><td>${fmt(m.mae_last10, 2)}</td><td>${fmt(m.mae_ewm5, 2)}</td>
          <td class="${g > 0 ? "pos" : "neg"}">${g > 0 ? "▲" : "▼"} ${fmt(Math.abs(g) * 100)}%</td><td>${fmt(m.brier, 3)}</td><td class="muted">${fmt(m.brier_coin, 3)}</td></tr>`; }).join("")}</table></div>
      <p class="note">Brier scores the over/under probability at a line of the player's last-10 average; lower is better, and "coin flip" is what you'd get by always guessing the usual over rate. Tap a market to see its calibration.</p></div>
    <div><h3 class="sub">Can you trust the percentages?<small>${P.labels[st]}</small></h3>
      <div class="calib">${calibChart(T[st].calibration)}
        <div><p class="note">Each dot groups games by what the model said the over chance was. Dots on the dashed line mean the percentages are honest: when it says 60%, the over hits about 60% of the time. Bigger dots stand for more games.</p>
          <table class="agate"><tr><th>Model said</th><th>Over hit</th><th>Games</th></tr>
          ${T[st].calibration.map(c => `<tr><td>${pct(c.p, 1)}</td><td>${pct(c.hit, 1)}</td><td>${c.n.toLocaleString()}</td></tr>`).join("")}</table></div></div></div>
  </div>`;
  el.querySelectorAll("tr[data-t]").forEach(tr => tr.onclick = () => { S.rec.stat = tr.dataset.t; renderRecord(); });
}

// ==================== BOOT ====================
Promise.all([
  fetch("props.json").then(r => r.json()),
  fetch("props_backtest.json").then(r => r.ok ? r.json() : null).catch(() => null),
  fetch("players/index.json").then(r => r.ok ? r.json() : []).catch(() => []),
  fetch("picks.json").then(r => r.ok ? r.json() : null).catch(() => null),
]).then(([props, bt, index, picks]) => {
  P = props; BT = bt; INDEX = index; PK = picks;
  const built = new Date(P.built_at);
  $("dateline").innerHTML = `<span>Season <b>${esc(P.season)}</b></span>
    <span>${today.toLocaleDateString(undefined, { weekday:"long", month:"long", day:"numeric", year:"numeric" })}</span>
    <span>Updated <b>${built.toLocaleString(undefined, { month:"short", day:"numeric", hour:"numeric", minute:"2-digit" })}</b></span>
    <span><b>${P.players.length}</b> players · <b>${P.games.length}</b> games</span>`;
  const h = location.hash.slice(1);
  go(["slate", "board", "desk", "files", "record", "bets", "picks", "news"].includes(h) ? h : "slate");
  refreshInjuries();
}).catch(e => { $("dateline").innerHTML = `<span>Couldn't load projections: ${esc(e.message || e)}</span>`; });

// ==================== NEWS ====================
// Headlines, the injury report and transactions, read live from ESPN in the browser.
const NEWS = { items:null, tx:null, inj:null, at:null, live:true, snapAt:null, loading:false, err:"", team:"" };
const ago = iso => {
  const m = Math.round((Date.now() - Date.parse(iso)) / 6e4);
  return m < 1 ? "just now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
};

function setInjuries(list) {
  NEWS.inj = list;
  INJ = new Map(list.map(i => [i.key, i]));
  if (["slate", "board", "desk", "picks"].includes(S.tab)) go(S.tab);  // show the live tags
}
const refreshInjuries = () => loadInjuries().then(r => setInjuries(r.items)).catch(() => {});  // keeps the build's report

async function refreshNews() {
  NEWS.loading = true; NEWS.err = "";
  if (S.tab === "news") renderNews();
  const [n, i, t] = await Promise.allSettled([loadNews(), loadInjuries(), loadTransactions()]);
  const ok = [n, i, t].filter(r => r.status === "fulfilled").map(r => r.value);
  if (n.status === "fulfilled") NEWS.items = n.value.items;
  if (t.status === "fulfilled") NEWS.tx = t.value.items;
  if (i.status === "fulfilled") { NEWS.inj = i.value.items; INJ = new Map(NEWS.inj.map(x => [x.key, x])); }
  NEWS.live = ok.every(r => r.live);
  NEWS.snapAt = ok.find(r => !r.live)?.at || null;
  if ([n, i, t].every(r => r.status === "rejected")) NEWS.err = "Couldn't reach ESPN. Check your connection and try again.";
  NEWS.at = new Date(); NEWS.loading = false;
  if (S.tab === "news") renderNews();
}
// Keep it fresh while the tab is open and visible.
setInterval(() => { if (S.tab === "news" && document.visibilityState === "visible" && !NEWS.loading) refreshNews(); }, 5 * 6e4);

function renderNews() {
  const el = $("tab-news");
  if (!NEWS.at && !NEWS.loading) { refreshNews(); return; }
  const next = P.games.length ? new Set(P.games.filter(g => g.date === P.games[0].date).flatMap(g => [g.home, g.away])) : new Set();
  const f = NEWS.team, keep = code => !f || (f === "next" ? next.has(code) : code === f);
  const nextGame = code => { const g = P.games.find(x => x.home === code || x.away === code);
    return g ? `${g.home === code ? "vs" : "@"} ${logo(g.home === code ? g.away : g.home)}${g.home === code ? g.away : g.home} · ${dayLabel(g.date)}` : ""; };
  const ids = new Map(INDEX.map(([id, name]) => [nameKey(name), id]));
  const names = new Set(Object.entries(TEAM_NAMES).filter(([c]) => keep(c)).map(([, n]) => n));
  const items = (NEWS.items || []).filter(a => !f || a.teams.some(t => names.has(t)));
  const byTeam = {};
  (NEWS.inj || []).filter(i => keep(i.team)).forEach(i => (byTeam[i.team] ||= []).push(i));
  const teams = Object.keys(byTeam).sort((a, b) => next.has(b) - next.has(a) || a.localeCompare(b));
  const tx = (NEWS.tx || []).filter(t => keep(t.team));
  const order = { "Out":0, "Day-To-Day":1 };

  el.innerHTML = `<div class="reveal">
    <div><p class="kicker">The wire</p><h2 class="head">News, injuries &amp; moves</h2>
      <p class="deck">Live from ESPN. It refreshes every few minutes while this page is open, and injury tags across the site update with it.</p></div>
    <div class="controls">
      <div class="field" style="min-width:220px"><label>Team</label><select id="nteam">
        <option value="">All teams</option><option value="next" ${f === "next" ? "selected" : ""}>Teams playing ${P.games[0] ? dayLabel(P.games[0].date).toLowerCase() : "next"}</option>
        ${Object.entries(TEAM_NAMES).map(([c, n]) => `<option value="${c}" ${c === f ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
      <div class="small-note" style="margin-top:18px">${NEWS.loading ? "Updating…" : NEWS.live ? `Live · checked ${NEWS.at.toLocaleTimeString([], { hour:"numeric", minute:"2-digit" })}`
          : `Live feed unavailable: showing the ${NEWS.snapAt ? new Date(NEWS.snapAt).toLocaleString(undefined, { month:"short", day:"numeric", hour:"numeric", minute:"2-digit" }) : "morning"} update`}
        · <button class="link" id="nrefresh" type="button">Refresh</button></div>
    </div>
    ${NEWS.err ? `<div class="warn">${esc(NEWS.err)}</div>` : ""}

    <h3 class="sub">Headlines<small>${items.length} stories</small></h3>
    ${items.length ? `<div class="wire">${items.slice(0, 13).map((a, k) => `<a class="story ${k === 0 ? "lead" : ""}" href="${esc(a.url)}" target="_blank" rel="noopener">
        ${a.image ? `<img src="${esc(a.image)}" alt="" loading="lazy">` : ""}
        <div><p class="kicker">${esc(a.type === "HeadlineNews" ? "Breaking" : a.type === "Recap" ? "Recap" : a.type === "Preview" ? "Preview" : a.type === "Media" ? "Video" : "Story")} · ${ago(a.published)}</p>
          <h4>${esc(a.headline)}</h4>${k < 5 && a.description ? `<p>${esc(a.description)}</p>` : ""}</div></a>`).join("")}</div>`
      : `<p class="note">${NEWS.items ? "No recent stories for this filter." : "Loading…"}</p>`}

    <div class="newscols">
      <div><h3 class="sub">Injury report<small>${(NEWS.inj || []).filter(i => keep(i.team)).length} players</small></h3>
        ${teams.length ? teams.map(code => `<div class="injteam">
          <div class="injhead"><b>${logo(code)} ${esc(TEAM_NAMES[code] || code)}</b><span class="muted">${next.has(code) ? nextGame(code) : nextGame(code) || ""}</span></div>
          ${byTeam[code].sort((a, b) => (order[a.status] ?? 2) - (order[b.status] ?? 2) || a.name.localeCompare(b.name)).map(i => { const id = ids.get(i.key);
            return `<div class="inj ${id ? "click" : ""}" ${id ? `data-pid="${id}"` : ""}>
              ${id ? face(id, i.name) : ""}<div><span class="pname">${esc(i.name)}</span> <span class="muted">${esc(i.pos)}</span>${injTag(i)}
              <div class="small-note" style="margin:2px 0 0">${esc(i.injury || "Undisclosed")}${i.return ? ` · back ~${backBy(i.return)}` : ""} · updated ${ago(i.date)}</div>
              ${i.note ? `<p class="note" style="margin:3px 0 0;font-size:13px">${esc(i.note)}</p>` : ""}</div></div>`; }).join("")}</div>`).join("")
        : `<p class="note">${NEWS.inj ? "No injuries listed for this filter." : "Loading…"}</p>`}</div>
      <div><h3 class="sub">Transactions<small>signings, waivers &amp; trades</small></h3>
        ${tx.length ? `<ul class="tx">${tx.map(t => `<li><span class="muted">${new Date(t.date).toLocaleDateString(undefined, { month:"short", day:"numeric" })}</span>
          <div>${logo(t.team)}<b>${esc(t.team)}</b> ${esc(t.text)}</div></li>`).join("")}</ul>`
        : `<p class="note">${NEWS.tx ? "No recent moves for this filter." : "Loading…"}</p>`}</div>
    </div>
    <p class="note">Source: ESPN. Stories open on espn.com. The model reads the injury report each morning: players ruled out are flagged and left out of Model Picks, but projections don't yet adjust teammates' minutes when someone sits.</p>
  </div>`;
  $("nteam").onchange = e => { NEWS.team = e.target.value; renderNews(); };
  $("nrefresh").onclick = () => { if (!NEWS.loading) refreshNews(); };
  el.querySelectorAll(".inj[data-pid]").forEach(d => d.onclick = () => openFile(d.dataset.pid));
  el.querySelectorAll(".story img").forEach(img => img.onerror = () => img.remove());
}

// ==================== ACCOUNT ====================
// Firebase loads in the background so the page itself stays fast.
let acct = null;
import("./account.js").then(m => {
  acct = m;
  acct.onUser(u => {
    S.user = u; S.bets = null;
    renderAcct();
    if (u) $("signin")?.close();
    loadBets();
  });
}).catch(() => { acct = { configured:false, onUser() {} }; renderAcct(); loadBets(); });

function renderAcct() {
  const el = $("acct");
  if (!S.user) { el.innerHTML = `<button type="button" id="acctbtn">Sign in</button>`; $("acctbtn").onclick = openSignin; return; }
  const who = S.user.displayName || S.user.email || "Account";
  el.innerHTML = `<button type="button" id="acctbtn" class="me"><b>${esc(who[0].toUpperCase())}</b>My bets</button>`;
  $("acctbtn").onclick = () => go("bets");
}

// Bets saved on this device: used when signed out or when the cloud refuses them
// (e.g. Firestore rules not published). They move to the account once it works.
const LOCAL_BETS = "propsheet.bets";
const localBets = () => { try { return JSON.parse(store.get(LOCAL_BETS) || "[]"); } catch { return []; } };
const setLocalBets = list => store.set(LOCAL_BETS, JSON.stringify(list));
const savedAt = b => b.createdAt?.toMillis?.() ?? (Date.parse(b.createdAt) || 0);

async function loadBets() {
  let cloud = [];
  S.cloudError = null;
  if (acct?.configured && S.user) {
    try {
      cloud = await acct.listBets();
      const waiting = localBets();
      if (waiting.length) {  // the cloud works now: move device-only bets up, one at a time
        for (const { id, local, createdAt, ...bet } of waiting) {
          await acct.saveBet(bet);
          setLocalBets(localBets().filter(x => x.id !== id));
        }
        cloud = await acct.listBets();
      }
    } catch (e) { S.cloudError = acct.errorMessage(e); }
  }
  S.bets = [...cloud, ...localBets()].sort((a, b) => savedAt(b) - savedAt(a));
  if (S.tab === "bets") renderBets();
}

const GOOGLE_G = `<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.5z"/></svg>`;

let signinMode = "in";
function openSignin() {
  let dlg = $("signin");
  if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "signin"; document.body.append(dlg); }
  if (!acct || !acct.configured) {
    dlg.innerHTML = `<form method="dialog" class="dlg"><button class="x" aria-label="Close">×</button>
      <p class="kicker">Members</p><h2 class="head">Sign in</h2>
      <p class="note">${acct ? "Sign-in isn't set up on this site yet: the Firebase config hasn't been added. See “Accounts” in the README." : "Still loading, try again in a second."}</p>
      <button class="btn solid">OK</button></form>`;
    dlg.showModal(); return;
  }
  const create = signinMode === "up";
  dlg.innerHTML = `<form class="dlg" id="sform" novalidate>
    <button type="button" class="x" aria-label="Close" id="sclose">×</button>
    <p class="kicker">Members</p><h2 class="head">${create ? "Create account" : "Sign in"}</h2>
    <p class="note" style="margin:0">Save bets from the Line Desk and see how they do once the games are final.</p>
    <button type="button" class="btn line google" id="sgoogle">${GOOGLE_G}Continue with Google</button>
    <div class="or"><span>or with email</span></div>
    ${create ? `<div class="field"><label for="sname">Name</label><input id="sname" autocomplete="name"></div>` : ""}
    <div class="field"><label for="semail">Email</label><input id="semail" type="email" autocomplete="email" autocapitalize="off" inputmode="email" required></div>
    <div class="field"><label for="spass">Password</label><input id="spass" type="password" autocomplete="${create ? "new-password" : "current-password"}" required minlength="6"></div>
    <p id="serr" role="alert"></p>
    <button type="submit" class="btn solid" id="ssubmit">${create ? "Create account" : "Sign in"}</button>
    <div class="dlg-foot">
      ${create ? "" : `<button type="button" class="link" id="sforgot">Forgot password?</button>`}
      <button type="button" class="link" id="smode">${create ? "Have an account? Sign in" : "New here? Create an account"}</button>
    </div></form>`;
  if (!dlg.open) dlg.showModal();
  const err = m => { $("serr").textContent = m; };
  const busy = (on, label) => { $("ssubmit").disabled = on; $("sgoogle").disabled = on; if (label) $("ssubmit").textContent = label; };
  $("sclose").onclick = () => dlg.close();
  $("smode").onclick = () => { signinMode = create ? "in" : "up"; openSignin(); };
  $("sgoogle").onclick = async () => {
    err(""); busy(true);
    try { await acct.signInGoogle(); } catch (e) { err(acct.errorMessage(e)); }
    busy(false);
  };
  if ($("sforgot")) $("sforgot").onclick = async () => {
    const email = $("semail").value.trim();
    if (!email) { err("Type your email above, then tap “Forgot password?” again."); return; }
    try { await acct.resetPassword(email); err(""); $("serr").innerHTML = `<span class="pos">Check ${esc(email)} for a reset link.</span>`; }
    catch (e) { err(acct.errorMessage(e)); }
  };
  $("sform").onsubmit = async e => {
    e.preventDefault(); err("");
    const email = $("semail").value.trim(), pass = $("spass").value;
    busy(true, create ? "Creating…" : "Signing in…");
    try {
      if (create) await acct.signUpEmail(email, pass, $("sname").value.trim());
      else await acct.signInEmail(email, pass);
    } catch (ex) { err(acct.errorMessage(ex)); busy(false, create ? "Create account" : "Sign in"); }
  };
  dlg.onclick = e => { if (e.target === dlg) dlg.close(); };  // tap the backdrop to close
}

const betOf = ({ p, s, L, side, odds, modelP, mu }) => ({ pid:p.id, name:p.name, team:p.team, opp:p.opp, home:p.home,
  game_id:p.game_id, date:p.date, stat:s, line:L, side, odds, modelP:+modelP.toFixed(4), proj:+mu.toFixed(2) });

function saveCurrentBet(leg) {
  const stake = parseFloat(S.desk.bet.stake);
  if (!(stake > 0)) { $("bmsg").innerHTML = `<span class="neg">Enter a stake above 0.</span>`; return; }
  storeBet({ ...betOf(leg), stake }, $("bsave"), $("bmsg"));
}

// Saves to the account, or to this device when signed out or the cloud refuses it.
async function storeBet(bet, btn, msg) {
  const done = note => {
    msg.innerHTML = `<span class="pos">✓ Saved${note}.</span> <a href="#bets" class="seebets">See My Bets</a>`;
    msg.querySelector(".seebets").onclick = e => { e.preventDefault(); go("bets"); };
  };
  btn.disabled = true;
  if (acct?.configured && S.user && !S.cloudError) {
    try { await acct.saveBet(bet); done(""); btn.disabled = false; loadBets(); return true; }
    catch (e) { S.cloudError = acct.errorMessage(e); }
  }
  const saved = { ...bet, id:"local-" + Date.now(), local:true, createdAt:new Date().toISOString() };
  setLocalBets([saved, ...localBets()]);
  S.bets = [saved, ...(S.bets || []).filter(x => x.id !== saved.id)];  // show it right away
  done(S.user ? " on this device (cloud sync is blocked for now)" : " on this device · sign in to keep it across devices");
  btn.disabled = false;
  loadBets();
  return true;
}

// ==================== PARLAY ====================
// Legs collected from the Line Desk, kept on this device until saved as one bet.
const PARLAY = "propsheet.parlay";
const parlay = (() => { try { return { stake:"1", odds:{ sign:1, abs:"" }, ...JSON.parse(store.get(PARLAY) || "{}") }; }
                        catch { return { stake:"1", odds:{ sign:1, abs:"" } }; } })();
parlay.legs ||= [];
const saveParlay = () => { store.set(PARLAY, JSON.stringify(parlay)); renderParlayBar(); };
// The odds typed for the whole parlay, as American (NaN if none).
const parlayCustom = () => oddsFmt === "x" ? fromMult(parlay.odds.x)
  : parlay.odds.abs ? parlay.odds.sign * +parlay.odds.abs : NaN;
const inParlay = (pid, stat) => parlay.legs.some(l => l.pid === pid && l.stat === stat);
function addLeg(leg) {  // one leg per player and market; adding again replaces it
  const i = parlay.legs.findIndex(l => l.pid === leg.pid && l.stat === leg.stat);
  if (i >= 0) parlay.legs[i] = leg; else parlay.legs.push(leg);
  saveParlay();
}

// "+" buttons on The Board and Model Picks: add that side at −110, tap again to take it out.
const sameLeg = (l, pid, stat, line, side) => l.pid === pid && l.stat === stat && l.line === line && l.side === side;
function addBtn(p, stat, line, side, modelP) {
  const on = parlay.legs.some(l => sameLeg(l, p.id, stat, line, side));
  return `<button type="button" class="addp ${on ? "on" : ""}" data-pid="${p.id}" data-g="${p.game_id}" data-s="${stat}" data-l="${line}" data-side="${side}" data-p="${modelP}"
    aria-pressed="${on}" aria-label="${on ? "Remove from" : "Add to"} parlay" title="${on ? "In your parlay: tap to remove" : "Add to parlay"}">${on ? "✓" : "+"}</button>`;
}
function wireAddBtns(el) {
  el.querySelectorAll(".addp").forEach(btn => btn.onclick = e => {
    e.stopPropagation();  // the row itself opens the Line Desk
    const d = btn.dataset, p = P.players.find(x => x.id === d.pid && x.game_id === d.g), line = +d.l;
    const i = parlay.legs.findIndex(l => sameLeg(l, d.pid, d.s, line, d.side));
    if (i >= 0) { parlay.legs.splice(i, 1); saveParlay(); }
    else if (parlay.legs.length >= 12) { alert("A parlay can have at most 12 legs."); return; }
    else addLeg(betOf({ p, s:d.s, L:line, side:d.side, odds:-110, modelP:+d.p, mu:p.proj[d.s][0] }));
    const on = i < 0;
    btn.classList.toggle("on", on); btn.textContent = on ? "✓" : "+";
    btn.setAttribute("aria-pressed", on); btn.setAttribute("aria-label", (on ? "Remove from" : "Add to") + " parlay");
    // a replaced leg (same player and market, other side or line) un-ticks its old button
    el.querySelectorAll(".addp.on").forEach(b => { const x = b.dataset;
      if (!parlay.legs.some(l => sameLeg(l, x.pid, x.s, +x.l, x.side))) { b.classList.remove("on"); b.textContent = "+"; } });
  });
}

// A bar along the bottom on every tab but the Line Desk, while a parlay is being built.
function renderParlayBar() {
  let bar = $("pbar2");
  if (!bar) { bar = document.createElement("div"); bar.id = "pbar2"; document.body.append(bar); }
  const legs = parlay.legs;
  const show = legs.length > 0 && S.tab !== "desk";
  document.body.style.paddingBottom = show ? "72px" : "";  // so the bar never hides the last row
  if (!show) { bar.classList.remove("show"); return; }
  bar.innerHTML = `<div><b>Parlay</b> · ${legs.length} leg${legs.length > 1 ? "s" : ""}${legs.length > 1
      ? ` · pays ${showOdds(parlayOdds(legs))} · model ${pct(legs.reduce((a, l) => a * l.modelP, 1), 1)}` : " · add one more"}</div>
    <button type="button" id="pbaropen">Open slip →</button>`;
  bar.classList.add("show");
  $("pbaropen").onclick = () => { go("desk"); setTimeout(() => $("parlay")?.scrollIntoView({ behavior:"smooth", block:"start" }), 50); };
}

function renderParlay() {
  const el = $("parlay");
  if (!el) return;
  parlay.legs = parlay.legs.filter(l => P.games.some(g => g.game_id === l.game_id));  // drop games that have started
  saveParlay();
  const legs = parlay.legs;
  if (!legs.length) {
    el.innerHTML = `<div class="parlay empty"><h3 class="sub" style="margin-top:4px">Parlay<small>0 legs</small></h3>
      <p class="note" style="margin:0">Group props from different players into one bet: price a prop, then tap “+ Add to parlay”.</p>
      <div class="small-note" id="pmsg"></div></div>`;
    return;
  }
  const book = legs.length > 1 ? parlayOdds(legs) : null;
  const custom = parlayCustom();
  const odds = Math.abs(custom) >= 100 ? custom : book;
  const modelP = legs.reduce((a, l) => a * l.modelP, 1);
  const ev = odds == null ? null : modelP * toDecimal(odds) - 1;
  const sameGame = new Set(legs.map(l => l.game_id)).size < legs.length;
  const o = showOdds;
  el.innerHTML = `<div class="parlay">
    <h3 class="sub" style="margin-top:4px">Parlay<small>${legs.length} leg${legs.length > 1 ? "s" : ""}</small></h3>
    <ol class="legs">${legs.map((l, i) => `<li>
      ${face(l.pid, l.name)}<div><b>${esc(l.name)}</b>${injTag(injOf(l.name))} <span class="muted">${logo(l.team)}${l.team} ${l.home ? "vs" : "@"} ${logo(l.opp)}${l.opp}</span><br>
        ${l.side === "over" ? "Over" : "Under"} ${l.line} ${SHORT[l.stat] || l.stat} <span class="muted">· ${o(l.odds)} · model ${pct(l.modelP)}</span></div>
      <button type="button" class="link" data-i="${i}" aria-label="Remove leg">Remove</button></li>`).join("")}</ol>
    ${legs.length < 2 ? `<p class="note" style="margin:0">Add at least one more leg.</p>` : `
    <div class="facts" style="margin:10px 0 6px">
      <div class="fact"><div class="k">All hit</div><div class="v">${pct(modelP, 1)}</div><div class="s">model · fair ${fairOdds(modelP)}</div></div>
      <div class="fact"><div class="k">Pays</div><div class="v">${o(odds)}</div><div class="s">${odds === book ? "from leg odds" : `legs alone: ${o(book)}`}</div></div>
      <div class="fact"><div class="k">Value</div><div class="v ${ev > 0 ? "pos" : "neg"}">${ev > 0 ? "+" : "−"}$${Math.abs(ev * 100).toFixed(0)}</div><div class="s">per $100</div></div>
    </div>
    ${sameGame ? `<div class="warn">Some legs are in the same game. Their results move together, so “All hit” is only a rough guide, and books price same-game parlays differently: enter your book's odds below.</div>` : ""}
    <div class="two">
      ${oddsFmt === "x" ? `<div class="field"><label>Book's payout</label><div class="mult">
        <input id="podds" inputmode="decimal" placeholder="${multText(book)}" value="${esc(parlay.odds.x)}" aria-label="Parlay payout multiplier"><span aria-hidden="true">x</span></div></div>`
      : `<div class="field"><label>Book's parlay odds</label><div class="odds">
        <button type="button" class="sign" id="psign" aria-label="Switch plus or minus">${parlay.odds.sign < 0 ? "−" : "+"}</button>
        <input id="podds" inputmode="numeric" pattern="[0-9]*" placeholder="${Math.abs(book)}" value="${esc(parlay.odds.abs)}" aria-label="Parlay odds"></div></div>`}
      <div class="field"><label>Stake (units)</label><input id="pstake" inputmode="decimal" value="${esc(parlay.stake)}"></div>
    </div>
    <button class="btn accent" id="psave" type="button" style="margin-top:12px">Save parlay to My Bets</button>`}
    <div class="small-note" id="pmsg"></div>
    <button type="button" class="link" id="pclear">Clear parlay</button></div>`;
  el.querySelectorAll(".legs .link").forEach(b => b.onclick = () => { legs.splice(+b.dataset.i, 1); saveParlay(); renderParlay(); renderSlip(); });
  $("pclear").onclick = () => { parlay.legs = []; parlay.odds.abs = parlay.odds.x = ""; saveParlay(); renderParlay(); renderSlip(); };
  if (legs.length < 2) return;
  if ($("psign")) $("psign").onclick = () => { parlay.odds.sign = -parlay.odds.sign; saveParlay(); renderParlay(); };
  $("podds").onchange = e => { const v = e.target.value.trim();
    if (oddsFmt === "x") { parlay.odds.x = v.replace(/[^\d.,]/g, ""); saveParlay(); renderParlay(); return; }
    if (/^[-−]/.test(v)) parlay.odds.sign = -1; else if (/^\+/.test(v)) parlay.odds.sign = 1;
    parlay.odds.abs = v.replace(/\D/g, ""); saveParlay(); renderParlay(); };
  $("pstake").oninput = e => { parlay.stake = e.target.value; saveParlay(); };
  $("psave").onclick = async () => {
    const stake = parseFloat(parlay.stake);
    if (!(stake > 0)) { $("pmsg").innerHTML = `<span class="neg">Enter a stake above 0.</span>`; return; }
    const date = legs.map(l => l.date).sort()[0];
    await storeBet({ type:"parlay", legs:[...legs], date, odds, stake, modelP:+modelP.toFixed(4) }, $("psave"), $("pmsg"));
    const msg = $("pmsg").innerHTML;
    parlay.legs = []; parlay.odds.abs = parlay.odds.x = ""; saveParlay(); renderParlay(); renderSlip();
    $("pmsg").innerHTML = msg;
    $("pmsg").querySelector(".seebets")?.addEventListener("click", e => { e.preventDefault(); go("bets"); });
  };
}

// ==================== MY BETS ====================
function renderBets() {
  const el = $("tab-bets");
  const head = `<div><p class="kicker">My bets</p><h2 class="head">Your betting record</h2></div>`;
  if (S.bets == null) { el.innerHTML = `<div class="reveal">${head}<p class="note">Loading your bets…</p></div>`; if (!S.user || acct) loadBets(); return; }
  const who = S.user ? esc(S.user.displayName || S.user.email) : null;
  const bets = S.bets;
  const pids = bets.flatMap(b => b.legs ? b.legs.map(l => l.pid) : [b.pid]);
  Promise.all([...new Set(pids)].map(id => getFile(id).then(f => [id, fileRows(f)]).catch(() => [id, []])))
    .then(pairs => {
      if (S.tab !== "bets" || S.bets !== bets) return;
      const rows = Object.fromEntries(pairs);
      const graded = bets.map(b => ({ bet:b, ...(b.legs ? gradeParlay(b, rows, P.built_at) : grade(b, rows[b.pid] || [], P.built_at)) }));
      const t = summarize(graded);
      const u = x => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(2)}u`;
      el.innerHTML = `<div class="reveal">${head}
        <p class="note">${who ? `Signed in as <b>${who}</b> · <button class="link" id="bout">Sign out</button>`
          : `Bets are saved on this device. <button class="link" id="bsign">Sign in</button> to keep them across devices.`}</p>
        ${S.cloudError ? `<div class="warn"><b>Cloud sync is off:</b> ${esc(S.cloudError)} Your bets are saved on this device and move to your account automatically once that's fixed.</div>` : ""}
        <div class="scoreline">
          <div class="fact"><div class="k">Record</div><div class="v">${t.won}–${t.lost}${t.push ? "–" + t.push : ""}</div><div class="s">won–lost${t.push ? "–push" : ""} · ${t.pending} pending</div></div>
          <div class="fact"><div class="k">Profit</div><div class="v ${t.units > 0 ? "pos" : t.units < 0 ? "neg" : ""}">${u(t.units)}</div><div class="s">units</div></div>
          <div class="fact"><div class="k">ROI</div><div class="v">${t.roi == null ? "–" : (t.roi > 0 ? "+" : "") + (t.roi * 100).toFixed(1) + "%"}</div><div class="s">profit ÷ amount staked</div></div>
          <div class="fact"><div class="k">Model vs reality</div><div class="v">${t.hitRate == null ? "–" : pct(t.hitRate)}</div><div class="s">${t.modelP == null ? "hit rate once bets settle" : `hit rate · model said ${pct(t.modelP)}`}</div></div>
        </div>
        ${bets.length ? `<div class="scroll"><table class="agate bets">
          <tr><th>Game</th><th>Player</th><th>Bet</th><th>Odds</th><th>Stake</th><th>Model</th><th>Result</th><th>P/L</th><th></th></tr>
          ${graded.map(g => { const b = g.bet, pl = profit(b, g.status, g.odds);
            const tail = `<td>${showOdds(b.odds)}</td><td>${b.stake}u</td><td>${pct(b.modelP)}</td>
              <td>${g.actual != null ? `<b>${fmt(g.actual, 0)}</b> ` : ""}<span class="st ${g.status}">${g.status}</span></td>
              <td class="${pl > 0 ? "pos" : pl < 0 ? "neg" : "muted"}">${g.status === "pending" ? "–" : u(pl)}</td>
              <td><button class="link del" data-id="${b.id}" aria-label="Delete bet">Delete</button></td></tr>`;
            if (b.legs) return `<tr class="parlay-row"><td class="muted">${esc(b.date)}</td>
              <td><span class="pname">Parlay</span> <span class="muted">${b.legs.length} legs</span>${b.local && S.user ? '<span class="tag" title="Saved on this device, waiting to sync">device</span>' : ""}</td>
              <td>${g.odds !== b.odds && g.status !== "push" ? `<span class="muted">paid at ${showOdds(g.odds)}</span>` : ""}</td>${tail}`
              + b.legs.map((l, i) => `<tr class="leg"><td class="muted">${esc(l.date)}</td>
              <td>${face(l.pid, l.name)}<span class="pname">${esc(l.name)}</span> <span class="muted">${logo(l.team)}${esc(l.team)} ${l.home ? "vs" : "@"} ${logo(l.opp)}${esc(l.opp)}</span></td>
              <td>${l.side === "over" ? "Over" : "Under"} ${l.line} ${SHORT[l.stat] || esc(l.stat)}</td>
              <td class="muted">${showOdds(l.odds)}</td><td></td><td class="muted">${pct(l.modelP)}</td>
              <td>${g.legs[i].actual != null ? `<b>${fmt(g.legs[i].actual, 0)}</b> ` : ""}<span class="st ${g.legs[i].status}">${g.legs[i].status}</span></td><td></td><td></td></tr>`).join("");
            return `<tr><td class="muted">${esc(b.date)}</td>
              <td>${face(b.pid, b.name)}<span class="pname">${esc(b.name)}</span> <span class="muted">${logo(b.team)}${esc(b.team)} ${b.home ? "vs" : "@"} ${logo(b.opp)}${esc(b.opp)}</span>${b.local && S.user ? '<span class="tag" title="Saved on this device, waiting to sync">device</span>' : ""}</td>
              <td>${b.side === "over" ? "Over" : "Under"} ${b.line} ${SHORT[b.stat] || esc(b.stat)}</td>${tail}`; }).join("")}
        </table></div>` : `<p class="deck">No bets yet. Open the <a href="#desk" id="todesk">Line Desk</a>, price a prop and tap “Save to My Bets”.</p>`}
        <p class="note">Bets settle once the morning data update includes that game. If the player doesn't play, the bet is void. A parlay loses if any leg loses; a leg that pushes or is void drops out and the parlay pays on the rest.</p></div>`;
      if ($("bout")) $("bout").onclick = () => acct.signOut();
      if ($("bsign")) $("bsign").onclick = openSignin;
      if ($("todesk")) $("todesk").onclick = e => { e.preventDefault(); go("desk"); };
      el.querySelectorAll(".del").forEach(btn => btn.onclick = async () => {
        if (!confirm("Delete this bet?")) return;
        const id = btn.dataset.id;
        try {
          if (id.startsWith("local-")) setLocalBets(localBets().filter(b => b.id !== id));
          else await acct.deleteBet(id);
          S.bets = S.bets.filter(b => b.id !== id); renderBets();
        }
        catch (e) { alert(acct.errorMessage(e)); }
      });
    });
}

// ==================== MODEL PICKS ====================
// One line over time, with a dashed reference; hover/tap a day for its numbers.
function lineChart(points, ref, refLabel) {
  const W = 680, H = 210, pl = 40, pr = 10, pt = 16, pb = 26, n = points.length;
  const ys = points.map(p => p.y).concat(ref ?? []);
  const lo = Math.max(0, Math.floor((Math.min(...ys) - .05) * 10) / 10), hi = Math.min(1, Math.ceil((Math.max(...ys) + .05) * 10) / 10);
  const x = i => pl + (n < 2 ? 0 : i * (W - pl - pr) / (n - 1)), y = v => pt + (1 - (v - lo) / (hi - lo)) * (H - pt - pb);
  const ticks = [lo, (lo + hi) / 2, hi];
  let out = ticks.map(t => `<line x1="${pl}" x2="${W - pr}" y1="${y(t)}" y2="${y(t)}" stroke="var(--rule)"/>
    <text x="${pl - 6}" y="${y(t) + 4}" text-anchor="end">${Math.round(t * 100)}%</text>`).join("");
  if (ref != null) out += `<line x1="${pl}" x2="${W - pr}" y1="${y(ref)}" y2="${y(ref)}" stroke="var(--ink)" stroke-width="1.5" stroke-dasharray="5 4"/>
    <text class="lbl" x="${W - pr}" y="${y(ref) - 6}" text-anchor="end">${refLabel}</text>`;
  out += `<polyline points="${points.map((p, i) => `${x(i)},${y(p.y)}`).join(" ")}" fill="none" stroke="var(--over)" stroke-width="2" stroke-linejoin="round"/>`;
  const step = Math.max(1, Math.floor(n / 60));  // keep hover targets reasonable on long seasons
  points.forEach((p, i) => { if (i % step === 0 || i === n - 1) out += `<rect x="${x(i) - (W - pl - pr) / n / 2 * step}" y="${pt}" width="${Math.max((W - pl - pr) / n * step, 6)}" height="${H - pt - pb}" fill="transparent" data-tip="${p.tip}"/>`; });
  const last = points[n - 1];
  out += `<circle cx="${x(n - 1)}" cy="${y(last.y)}" r="4.5" fill="var(--over)" stroke="var(--card)" stroke-width="2"/>`;
  out += `<text x="${pl}" y="${H - 6}">${esc(points[0].label)}</text><text x="${W - pr}" y="${H - 6}" text-anchor="end">${esc(last.label)}</text>`;
  return `<div class="chart"><svg class="wide" viewBox="0 0 ${W} ${H}" role="img" aria-label="Hit rate over time">${out}</svg></div>`;
}

// Cumulative hit rate, day by day.
function hitSeries(daily) {
  let w = 0, l = 0;
  return daily.map(d => { w += d.won; l += d.lost;
    return { y:w / (w + l), label:d.date, tip:`<b>${esc(d.date)}</b><br>That day ${d.won}–${d.lost}<br>Season so far ${pct(w / (w + l), 1)} (${w}–${l})` }; });
}

function accuracyTables(s) {
  const row = (label, b) => b.n ? `<tr><td><span class="pname">${label}</span></td><td>${b.n}</td><td>${b.won}–${b.lost}</td>
    <td class="proj">${pct(b.hit, 1)}</td><td>${pct(b.avg_p, 1)}</td>
    <td class="${b.hit >= b.avg_p - .02 ? "pos" : "neg"}">${b.hit >= b.avg_p ? "▲" : "▼"} ${fmt(Math.abs(b.hit - b.avg_p) * 100)} pts</td></tr>` : "";
  const head = `<tr><th></th><th>Picks</th><th>Record</th><th>Hit rate</th><th>Model said</th><th>Difference</th></tr>`;
  return `<div class="two-col">
    <div><h3 class="sub">By confidence<small>is the model honest?</small></h3><div class="scroll"><table class="agate">${head}
      ${s.by_conf.map(b => row(`${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%`, b)).join("")}</table></div></div>
    <div><h3 class="sub">By market</h3><div class="scroll"><table class="agate">${head}
      ${Object.entries(s.by_market).map(([t, b]) => row(P.labels[t], b)).join("")}</table></div></div></div>`;
}

const pickText = x => `${x.side === "over" ? "Over" : "Under"} ${x.line} ${SHORT[x.stat] || x.stat}`;

function renderPicks() {
  const el = $("tab-picks");
  if (!PK) { el.innerHTML = `<p class="deck">No picks published yet. They appear after the next data update.</p>`; return; }
  const L = PK.live, sim = PK.sim, r = PK.rules;
  const pending = L.picks.filter(x => !x.result), graded = L.picks.filter(x => x.result);
  const byId = Object.fromEntries(P.players.map(p => [p.id + "|" + p.game_id, p]));
  el.innerHTML = `<div class="reveal">
    <div><p class="kicker">Model picks</p><h2 class="head">The model's picks, graded</h2>
      <p class="deck">Every morning the model picks up to ${r.per_day} over/unders where it disagrees most with a player's recent form. Picks lock when they're published and are graded from the box score after the game, so the record can't be cherry-picked.</p></div>

    <div><h3 class="sub">${pending.length ? `Open picks · ${dayLabel(pending[0].date)}` : "Open picks"}<small>${pending.length} pending</small></h3>
    ${pending.length ? `<div class="scroll"><table class="agate">
      <tr><th>Player</th><th>Game</th><th>Pick</th><th>Model</th><th>Form said</th><th>Proj</th><th>Form avg</th><th><span class="sr">Parlay</span></th></tr>
      ${pending.map(x => `<tr class="click" data-pid="${esc(x.player_id)}" data-g="${esc(x.game_id)}" data-s="${x.stat}" data-l="${x.line}">
        <td>${face(x.player_id, x.player)}<span class="pname">${esc(x.player)}</span> <span class="muted">${logo(x.team)}${esc(x.team)}</span>${injTag(injOf(x.player, byId[x.player_id + "|" + x.game_id]?.injury))}</td>
        <td class="muted">${x.home ? "vs" : "@"} ${logo(x.opp)}${esc(x.opp)} · ${dayLabel(x.date)}</td>
        <td><b class="lean ${x.side === "over" ? "o" : "u"}">${pickText(x)}</b></td>
        <td class="proj">${pct(x.p)}</td><td class="muted">${x.form_p ? pct(x.form_p) : "–"}</td>
        <td>${fmt(x.proj)}</td><td class="muted">${fmt(x.form)}</td>
        <td>${byId[x.player_id + "|" + x.game_id] ? addBtn(byId[x.player_id + "|" + x.game_id], x.stat, x.line, x.side, x.p) : ""}</td></tr>`).join("")}</table></div>
      <p class="note">“Form said” is the chance recent form alone gives that side (about 50%, by design). Tap a pick to price it against your book's line, or + to add it to your parlay.</p>`
      : `<p class="note">No open picks right now. The next slate's picks are published with the morning update.</p>`}</div>

    <div><h3 class="sub">Live record<small>since picks started</small></h3>
      <div class="scoreline">
        <div class="fact"><div class="k">Graded picks</div><div class="v">${L.n}</div><div class="s">${L.push ? L.push + " push · " : ""}${L.void ? L.void + " void · " : ""}${L.pending} pending</div></div>
        <div class="fact"><div class="k">Record</div><div class="v">${L.n ? `${L.won}–${L.lost}` : "–"}</div><div class="s">won–lost</div></div>
        <div class="fact"><div class="k">Hit rate</div><div class="v">${L.n ? pct(L.hit, 1) : "–"}</div><div class="s">${L.n ? `model said ${pct(L.avg_p, 1)}` : "first results after the games"}</div></div>
        <div class="fact"><div class="k">Days tracked</div><div class="v">${L.daily.length}</div><div class="s">with graded picks</div></div>
      </div>
      ${L.daily.length >= 2 ? `<div class="legend" style="margin-top:12px"><span><i style="background:var(--over)"></i>Hit rate so far</span><span class="muted">dashed: what the model predicted</span></div>${lineChart(hitSeries(L.daily), L.avg_p, `MODEL SAID ${pct(L.avg_p)}`)}` : ""}
      ${L.n ? accuracyTables(L) : ""}</div>

    ${sim?.n ? `<div><h3 class="sub">Simulated: the same rules on ${esc(sim.seasons.join(", "))}<small>${sim.n.toLocaleString()} picks · ${sim.daily.length} days</small></h3>
      <p class="note">What the picks would have looked like last season, using predictions from a model that hadn't seen those games. A guide, not a live record.</p>
      <div class="scoreline">
        <div class="fact"><div class="k">Record</div><div class="v">${sim.won.toLocaleString()}–${sim.lost.toLocaleString()}</div><div class="s">won–lost</div></div>
        <div class="fact"><div class="k">Hit rate</div><div class="v">${pct(sim.hit, 1)}</div><div class="s">model said ${pct(sim.avg_p, 1)}</div></div>
        <div class="fact"><div class="k">Picks a day</div><div class="v">${fmt(sim.n / sim.daily.length)}</div><div class="s">average</div></div>
        <div class="fact"><div class="k">Best market</div><div class="v" style="font-size:22px">${(() => { const e = Object.entries(sim.by_market).filter(([, b]) => b.n >= 50).sort((a, b) => b[1].hit - a[1].hit)[0]; return e ? `${SHORT[e[0]]} ${pct(e[1].hit)}` : "–"; })()}</div><div class="s">50+ picks</div></div>
      </div>
      <div class="legend" style="margin-top:12px"><span><i style="background:var(--over)"></i>Hit rate so far</span><span class="muted">dashed: what the model predicted</span></div>
      ${lineChart(hitSeries(sim.daily), sim.avg_p, `MODEL SAID ${pct(sim.avg_p)}`)}
      ${accuracyTables(sim)}</div>` : ""}

    <div class="warn"><b>Read this before betting on it.</b> These picks are graded against a line set from recent form, not a sportsbook's. Books know about injuries, role changes and new teams, so their lines are sharper and the model's edge against them is much smaller than these hit rates. Use the Line Desk with your book's actual line and odds.</div>

    ${graded.length ? `<div><h3 class="sub">Results<small>${graded.length} graded</small></h3><div class="scroll"><table class="agate">
      <tr><th>Date</th><th>Player</th><th>Pick</th><th>Model</th><th>Actual</th><th>Result</th></tr>
      ${graded.slice(0, S.picksAll ? graded.length : 30).map(x => `<tr><td class="muted">${esc(x.date)}</td>
        <td>${face(x.player_id, x.player)}<span class="pname">${esc(x.player)}</span> <span class="muted">${logo(x.team)}${esc(x.team)} ${x.home ? "vs" : "@"} ${logo(x.opp)}${esc(x.opp)}</span></td>
        <td>${pickText(x)}</td><td>${pct(x.p)}</td><td><b>${x.actual === "" ? "–" : fmt(x.actual, 0)}</b></td>
        <td><span class="st ${x.result}">${x.result}</span></td></tr>`).join("")}</table></div>
      ${graded.length > 30 ? `<button class="more" id="pall">${S.picksAll ? "Show fewer" : `Show all ${graded.length}`}</button>` : ""}</div>` : ""}
  </div>`;
  el.querySelectorAll("tr[data-pid]").forEach(tr => tr.onclick = () => {
    if (byId[tr.dataset.pid + "|" + tr.dataset.g]) openDesk(tr.dataset.pid, tr.dataset.s, +tr.dataset.l);
  });
  if ($("pall")) $("pall").onclick = () => { S.picksAll = !S.picksAll; renderPicks(); };
  wireAddBtns(el);
}
