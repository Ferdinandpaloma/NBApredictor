// The Tennis tab: ATP and WTA match predictions, ratings and the model's record.
// Data comes from site/tennis/{atp,wta}.json (scripts/build_tennis.py); live scores from ESPN.
import { loadTennis } from "./live.js";

const T = { tour:"atp", view:"matches", data:{}, err:{}, sel:null, total:{}, hcap:{}, rsort:"elo", all:false };
const TOURS = { atp:"ATP", wta:"WTA" };
const SURF = { hard:"Hard", clay:"Clay", grass:"Grass" };
// Live scores: cards leave a [data-tm] slot that paintLive fills in place (no re-render, so open
// lines and inputs stay put). Polled every 30 seconds while a match is on, else every 5 minutes.
const LIVE = { tour:{}, timer:0, el:null, esc:null, busy:false };

// Over/under (and push) on a distribution stored as { from, p: [...] }.
function overUnder(d, line) {
  let o = 0, u = 0;
  d.p.forEach((p, i) => { const v = d.from + i; if (v > line) o += p; else if (v < line) u += p; });
  return [o, u];
}
const median = d => { let c = 0; for (let i = 0; i < d.p.length; i++) { c += d.p[i]; if (c >= .5) return d.from + i; } return d.from; };
const mean = d => d.p.reduce((a, p, i) => a + p * (d.from + i), 0);

// Set scores from player 1's side, in betting order: 2-0, 2-1, 1-2, 0-2 (or 3-0 ... 0-3).
function setRows(m) {
  const need = m.best_of === 5 ? 3 : 2;
  const keys = Object.keys(m.sets).sort((a, b) => (+b[0] - +b[2]) - (+a[0] - +a[2]) || +b[0] - +a[0]);
  return keys.filter(k => +k[0] === need || +k[2] === need).map(k => [k, m.sets[k]]);
}

function load(tour, rerender) {
  if (T.data[tour] || T.err[tour]) return;
  T.data[tour] = null;
  fetch(`tennis/${tour}.json`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { T.data[tour] = d; }).catch(e => { delete T.data[tour]; T.err[tour] = `Couldn't load ${TOURS[tour]} data (${e.message}).`; })
    .then(rerender);
}

export function renderTennis(el, h, view) {
  if (view) T.view = view;
  const { esc, pct, fairOdds, dayLabel, tipTime } = h;
  const rerender = () => { if (!el.classList.contains("hidden")) renderTennis(el, h); };
  load(T.tour, rerender);
  const D = T.data[T.tour];
  const head = `<div><p class="kicker">Tennis</p><h2 class="head">Who wins, in how many sets, and how many games</h2>
    <p class="deck">Every ATP and WTA match on ESPN's schedule, from a surface-aware Elo rating of each player. Win chances are corrected by how past predictions did; set scores and total games come from simulating the match point by point.</p></div>
    <div class="controls">
      <div class="seg" id="ttour">${Object.entries(TOURS).map(([k, v]) => `<button type="button" data-k="${k}" class="${k === T.tour ? "on" : ""}">${v}</button>`).join("")}</div>
    </div>`;
  let body;
  if (T.err[T.tour]) body = `<div class="warn">${esc(T.err[T.tour])}</div>`;
  else if (!D) body = `<p class="note">Loading…</p>`;
  else body = { matches, ratings, record }[T.view](D);
  el.innerHTML = `<div class="reveal">${head}${body}</div>`;

  el.querySelector("#ttour").onclick = e => { const b = e.target.closest("button"); if (b) { T.tour = b.dataset.k; T.sel = null; T.all = false; rerender(); } };
  el.querySelectorAll(".tmatch[data-m]").forEach(c => c.onclick = () => { T.sel = T.sel === c.dataset.m ? null : c.dataset.m; rerender(); });
  el.querySelectorAll(".tdetail").forEach(d => d.onclick = e => e.stopPropagation());  // taps inside don't close it
  el.querySelectorAll("[data-step]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const [kind, id, d] = b.dataset.step.split("|"), box = T[kind];
    box[id] = +(box[id] + +d).toFixed(1); rerender();
  });
  el.querySelectorAll("input[data-line]").forEach(inp => {
    inp.onclick = e => e.stopPropagation();
    inp.onchange = () => { const [kind, id] = inp.dataset.line.split("|"), v = parseFloat(inp.value); if (!isNaN(v)) { T[kind][id] = v; rerender(); } };
  });
  el.querySelectorAll("#rsort button").forEach(b => b.onclick = () => { T.rsort = b.dataset.k; rerender(); });
  const more = el.querySelector("#tall"); if (more) more.onclick = () => { T.all = !T.all; rerender(); };
  LIVE.el = el; LIVE.esc = esc;
  paintLive();
  if (!LIVE.timer || (T.data[T.tour] && !LIVE.tour[T.tour])) pollLive();  // first time, or a tour not fetched yet

  function nameCell(p, win) {
    return `<span class="${win ? "win" : ""}">${esc(p.name)}</span> <span class="muted small">${esc(p.country)}</span>`;
  }

  function detail(m) {
    const id = m.match_id, p1 = m.p1.name.split(" ").at(-1), p2 = m.p2.name.split(" ").at(-1);
    T.total[id] ??= median(m.totals) + .5;
    const mm = mean(m.margins);
    T.hcap[id] ??= mm >= 0 ? -(Math.round(mm) + .5) : Math.round(-mm) + .5;
    const L = T.total[id], H = T.hcap[id];
    const [o, u] = overUnder(m.totals, L);
    // Handicap H on player 1: they cover if (their games − opponent's) + H > 0.
    const [cov, lose] = overUnder(m.margins, -H);
    const stepper = (kind, v) => `<div class="stepper"><button type="button" data-step="${kind}|${id}|-1" aria-label="Lower">−</button>
      <input type="number" step="0.5" inputmode="decimal" value="${v}" data-line="${kind}|${id}" aria-label="Line"><button type="button" data-step="${kind}|${id}|1" aria-label="Raise">+</button></div>`;
    return `<div class="tdetail">
      <div><h4>Set betting</h4><table class="agate">${setRows(m).map(([k, p]) => `<tr><td>${+k[0] > +k[2] ? esc(p1) : esc(p2)} ${+k[0] > +k[2] ? k : k.split("-").reverse().join("-")}</td>
        <td class="proj">${pct(p)}</td><td class="muted">${fairOdds(p)}</td></tr>`).join("")}</table></div>
      <div><h4>Total games</h4>${stepper("total", L)}
        <p class="tline"><b>Over ${pct(o)}</b> <span class="muted">${fairOdds(o)}</span> · <b>Under ${pct(u)}</b> <span class="muted">${fairOdds(u)}</span></p>
        <p class="note">Expected ${mean(m.totals).toFixed(1)} games. A tiebreak counts as one game.</p></div>
      <div><h4>Games handicap · ${esc(p1)}</h4>${stepper("hcap", H)}
        <p class="tline"><b>${esc(p1)} ${H > 0 ? "+" : ""}${H} ${pct(cov)}</b> <span class="muted">${fairOdds(cov)}</span> · <b>${esc(p2)} ${-H > 0 ? "+" : ""}${-H} ${pct(lose)}</b> <span class="muted">${fairOdds(lose)}</span></p>
        <p class="note">${esc(p1)} covers if they win ${H < 0 ? `by more than ${-H} games` : `or lose by fewer than ${H} games`}.</p></div>
    </div>`;
  }

  function matches(D) {
    if (!D.upcoming.length) return `<p class="deck">No ${TOURS[T.tour]} matches scheduled right now. The tour calendar picks up again in January; ratings and the record are still here.</p>`;
    const groups = {};
    D.upcoming.forEach(m => (groups[m.date + "|" + m.event] ||= []).push(m));
    return Object.entries(groups).map(([k, ms]) => {
      const [d, ev] = k.split("|"), m0 = ms[0];
      return `<h3 class="sub">${esc(ev)}<small>${dayLabel(d)} · ${SURF[m0.surface]} · best of ${m0.best_of}</small></h3>
        <div class="matchups">${ms.map(m => { const fav1 = m.p >= .5;
          return `<div class="matchup tmatch click ${T.sel === m.match_id ? "on" : ""}" data-m="${esc(m.match_id)}">
            <div class="mrow"><span>${nameCell(m.p1, fav1)}</span><span class="muted small">${esc(m.round)}${m.start ? " · " + tipTime(m.start) : ""}${m.state === "in" ? ` · <i class="livedot"></i>live` : ""}</span><span>${nameCell(m.p2, !fav1)}</span></div>
            <div class="tscore" data-tm="${esc(m.match_id)}"></div>
            <div class="wbar"><i style="width:${m.p * 100}%;background:var(--ink)"></i><i style="width:${(1 - m.p) * 100}%;background:var(--muted)"></i></div>
            <div class="mrow small"><span class="${fav1 ? "win" : ""}">${pct(m.p)} · ${fairOdds(m.p)}</span><span class="muted">Elo ${m.p1.elo} – ${m.p2.elo}</span><span class="${!fav1 ? "win" : ""}">${fairOdds(1 - m.p)} · ${pct(1 - m.p)}</span></div>
            ${T.sel === m.match_id ? detail(m) : ""}
          </div>`; }).join("")}</div>`;
    }).join("") + `<p class="note">Tap a match for set betting, total games and the games handicap at any line. Odds shown are fair odds (no bookmaker margin): bet only when your book pays more.</p>`;
  }

  function ratings(D) {
    const key = T.rsort, rows = [...D.ratings].sort((a, b) => b[key] - a[key]);
    const shown = T.all ? rows : rows.slice(0, 50);
    return `<div class="controls"><div class="seg" id="rsort">${[["elo", "Overall"], ["hard", "Hard"], ["clay", "Clay"], ["grass", "Grass"]].map(([k, v]) => `<button type="button" data-k="${k}" class="${k === key ? "on" : ""}">${v}</button>`).join("")}</div></div>
      <div class="scroll"><table class="agate">
      <tr><th></th><th class="tl">Player</th><th>Overall</th><th>Hard</th><th>Clay</th><th>Grass</th><th>Matches</th><th>Last match</th></tr>
      ${shown.map((r, i) => `<tr><td class="muted">${i + 1}</td><td class="tl"><span class="pname">${esc(r.name)}</span> <span class="muted small">${esc(r.country)}</span></td>
        ${["elo", "hard", "clay", "grass"].map(k => `<td class="${k === key ? "proj" : ""}">${r[k]}</td>`).join("")}
        <td class="muted">${r.n}</td><td class="muted">${esc(r.last)}</td></tr>`).join("")}</table></div>
      ${rows.length > 50 ? `<button class="more" id="tall">${T.all ? "Show top 50" : `Show all ${rows.length}`}</button>` : ""}
      <p class="note">Elo: 1500 is a new player; each surface column is what the model uses on that surface (30% surface rating, 70% overall). Players with 20+ matches who played in the last year.</p>`;
  }

  function record(D) {
    const r = D.record, years = Object.keys(D.backtest).sort();
    const recent = T.all ? D.recent : D.recent.slice(0, 40);
    return `<div class="scoreline">
        <div class="fact"><div class="k">Picked right</div><div class="v">${pct(r.correct / r.n, 1)}</div><div class="s">${r.correct.toLocaleString()} of ${r.n.toLocaleString()} since ${years.at(-4) || years[0]}</div></div>
        <div class="fact"><div class="k">Brier score</div><div class="v">${r.brier.toFixed(3)}</div><div class="s">lower is better · coin flip 0.250</div></div>
        ${r.by_conf.slice(-2).map(b => `<div class="fact"><div class="k">${pct(b.lo)}+ favorites</div><div class="v">${pct(b.hit)}</div><div class="s">won · model said ${pct(b.avg_p)} · ${b.n.toLocaleString()} matches</div></div>`).join("")}
      </div>
      <div class="teamcols"><div><h3 class="sub">Recent results<small>last three weeks</small></h3>
        <div class="scroll"><table class="agate">
        <tr><th>Date</th><th class="tl">Winner</th><th class="tl">Loser</th><th>Score</th><th>Model</th></tr>
        ${recent.map(g => `<tr><td class="muted">${esc(g.date.slice(5))}</td><td class="tl"><span class="pname">${esc(g.winner)}</span></td><td class="tl">${esc(g.loser)}</td>
          <td class="muted">${esc(g.score)}</td><td><span class="st ${g.p > .5 ? "won" : "lost"}">${g.p > .5 ? "right" : "wrong"}</span> <span class="muted">${pct(g.p)}</span></td></tr>`).join("")}</table></div>
        ${D.recent.length > 40 ? `<button class="more" id="tall">${T.all ? "Show fewer" : `Show all ${D.recent.length}`}</button>` : ""}</div>
      <div><h3 class="sub">Does a 70% pick win 70%?<small>by confidence</small></h3>
        <table class="agate"><tr><th>Favorite's chance</th><th>Matches</th><th>Model said</th><th>Won</th></tr>
        ${r.by_conf.map(b => `<tr><td>${pct(b.lo)}–${pct(b.hi)}</td><td>${b.n.toLocaleString()}</td><td>${pct(b.avg_p, 1)}</td><td class="proj">${pct(b.hit, 1)}</td></tr>`).join("")}</table>
        <h3 class="sub">By year<small>tested on matches it hadn't seen</small></h3>
        <table class="agate"><tr><th>Year</th><th>Matches</th><th>Picked right</th><th>Brier</th></tr>
        ${years.map(y => { const b = D.backtest[y]; return `<tr><td>${y}</td><td>${b.n.toLocaleString()}</td><td>${pct(b.correct / b.n, 1)}</td><td>${b.brier.toFixed(3)}</td></tr>`; }).join("")}</table></div></div>
      <p class="note">Every completed match, main draw and qualifying, with the chance the model gave the winner before it started (the correction for each year was fitted on earlier years only). Retirements and walkovers aren't graded.</p>`;
  }
}

const lastName = n => String(n || "").split(" ").at(-1);

function scoreHTML(m, g, esc) {
  if (!g || g.state === "pre") return "";
  const row = p => {
    const x = g.players[p.id] || { games:[], tb:[] };
    const serve = x.serving && g.state === "in" ? `<i class="serve" title="Serving"></i>` : "";
    return `<div class="tsr ${x.winner ? "win" : ""}"><span class="tsn">${serve}${esc(lastName(p.name))}</span>${x.games.map((v, i) =>
      `<b>${v}${x.tb[i] != null ? `<sup>${x.tb[i]}</sup>` : ""}</b>`).join("")}</div>`;
  };
  let tail = "";
  if (g.state === "in") tail = `<i class="livedot"></i>${esc(g.detail || "Live")}`;
  else {
    const won = [m.p1, m.p2].find(p => g.players[p.id]?.winner);
    const fav = m.p >= .5 ? m.p1 : m.p2;
    tail = esc(g.detail || "Final") + (won ? ` <span class="st ${won.id === fav.id ? "won" : "lost"}">model ${won.id === fav.id ? "right" : "wrong"}</span>` : "");
  }
  return `<div class="tsrows">${row(m.p1)}${row(m.p2)}</div><div class="tstat">${tail}</div>`;
}

function paintLive() {
  const el = LIVE.el, D = T.data[T.tour], map = LIVE.tour[T.tour];
  if (!el || !D || !map) return;
  const byId = Object.fromEntries(D.upcoming.map(m => [m.match_id, m]));
  el.querySelectorAll("[data-tm]").forEach(slot => {
    const m = byId[slot.dataset.tm];
    slot.innerHTML = m ? scoreHTML(m, map.get(slot.dataset.tm), LIVE.esc) : "";
  });
}

async function pollLive() {
  clearTimeout(LIVE.timer); LIVE.timer = setTimeout(pollLive, 5 * 6e4);
  const el = LIVE.el, D = T.data[T.tour];
  if (!el || el.classList.contains("hidden") || document.visibilityState !== "visible" || !D?.upcoming.length) return;
  if (LIVE.busy) return;
  const tour = T.tour;
  LIVE.busy = true;
  try { LIVE.tour[tour] = await loadTennis(tour); } catch { return; } finally { LIVE.busy = false; }
  paintLive();
  const soon = Date.now() + 30 * 6e4;
  const busy = D.upcoming.some(m => LIVE.tour[tour].get(m.match_id)?.state === "in" || (m.start && Date.parse(m.start) < soon));
  if (busy) { clearTimeout(LIVE.timer); LIVE.timer = setTimeout(pollLive, 3e4); }
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && LIVE.el) pollLive(); });
