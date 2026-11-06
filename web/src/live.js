// Live scores and box scores from ESPN's public feeds, read in the browser while games are on.
// Pure helpers are exported for the tests; nothing here touches the page.
import { nameKey, teamCode } from "./news.js";

const API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/";
const COMBOS = { pra:["pts", "reb", "ast"], pr:["pts", "reb"], pa:["pts", "ast"], ra:["reb", "ast"], stocks:["stl", "blk"] };
// ESPN box score column -> our stat (made-attempted columns give two).
const COLS = { minutes:["min"], points:["pts"], rebounds:["reb"], assists:["ast"], turnovers:["tov"], steals:["stl"],
  blocks:["blk"], offensiveRebounds:["oreb"], defensiveRebounds:["dreb"],
  "fieldGoalsMade-fieldGoalsAttempted":["fgm", "fga"], "threePointFieldGoalsMade-threePointFieldGoalsAttempted":["fg3m", "fg3a"],
  "freeThrowsMade-freeThrowsAttempted":["ftm", "fta"] };

// The US Eastern date of a UTC time, as our game dates are (YYYY-MM-DD).
export const etDate = iso => new Date(iso).toLocaleDateString("en-CA", { timeZone:"America/New_York" });

// One entry per game: teams in our codes, score, and state ("pre", "in" or "post").
export function parseScoreboard(raw) {
  return (raw.events || []).map(e => {
    const c = e.competitions?.[0] || {}, st = c.status || e.status || {};
    const side = h => c.competitors?.find(t => t.homeAway === h) || {};
    const [a, h] = [side("away"), side("home")];
    return { id:e.id, date:etDate(e.date), away:teamCode(a.team?.abbreviation), home:teamCode(h.team?.abbreviation),
      awayScore:+a.score || 0, homeScore:+h.score || 0, state:st.type?.state || "pre",
      detail:st.type?.shortDetail || "", period:st.period || 0, clock:st.displayClock || "" };
  });
}

// Box score: name key -> { team, pts, reb, ... } for everyone who has played.
export function parseBox(raw) {
  const out = new Map();
  for (const t of raw.boxscore?.players || []) {
    const team = teamCode(t.team?.abbreviation);
    for (const s of t.statistics || []) {
      const keys = s.keys || [];
      for (const a of s.athletes || []) {
        if (a.didNotPlay || !a.stats?.length) continue;
        const row = { team, name:a.athlete?.displayName || "" };
        keys.forEach((k, i) => (COLS[k] || []).forEach((ours, j) => { row[ours] = +String(a.stats[i]).split("-")[j] || 0; }));
        out.set(nameKey(row.name), row);
      }
    }
  }
  return out;
}

export const statOf = (row, stat) => COMBOS[stat] ? COMBOS[stat].reduce((a, s) => a + (row[s] || 0), 0) : row[stat] || 0;

// Where a bet stands right now. leg: { stat, line, side }; game: a parseScoreboard entry;
// row: the player's box score row (null if not in the box score).
// status: "pre" (not started), "won"/"lost" (decided: overs cash once passed, unders bust once passed),
// "push", "void" (final, didn't play), "dnp" (live, hasn't played yet) or "live" (still open).
export function legNow(leg, game, row) {
  if (!game || game.state === "pre") return { status:"pre" };
  const final = game.state === "post";
  if (!row) return { status:final ? "void" : "dnp" };
  const cur = statOf(row, leg.stat), over = leg.side === "over";
  if (cur > leg.line) return { status:over ? "won" : "lost", cur, final };
  if (!final) return { status:"live", cur, need:+(Math.floor(leg.line) + 1 - cur).toFixed(1), final };
  if (cur === leg.line) return { status:"push", cur, final };
  return { status:over ? "lost" : "won", cur, final };
}

const get = async path => {
  const r = await fetch(API + path, { cache:"no-store" });
  if (!r.ok) throw new Error(`ESPN ${r.status}`);
  return r.json();
};
export const loadScoreboard = day => get("scoreboard?dates=" + day.replaceAll("-", "")).then(parseScoreboard);
export const loadBox = id => get("summary?event=" + id).then(parseBox);

// Tennis: one scoreboard per tour holds every match of the tournaments on now.
// Returns match id -> { state, detail, players: { espn id: { games, tb, winner, serving } } }.
export function parseTennis(raw) {
  const out = new Map();
  for (const e of raw.events || []) for (const g of e.groupings || []) {
    if (!/singles$/.test(g.grouping?.slug || "")) continue;
    for (const c of g.competitions || []) {
      const st = c.status?.type || {};
      const players = {};
      for (const x of c.competitors || []) {
        const sets = (x.linescores || []).filter(l => l.value != null);
        players[String(x.id)] = { games:sets.map(l => +l.value), tb:sets.map(l => l.tiebreak ?? null),
          winner:!!x.winner, serving:!!x.possession };
      }
      out.set(String(c.id), { state:st.state || "pre", detail:st.shortDetail || st.detail || "", players });
    }
  }
  return out;
}
export const loadTennis = tour => fetch(`https://site.api.espn.com/apis/site/v2/sports/tennis/${tour}/scoreboard`, { cache:"no-store" })
  .then(r => { if (!r.ok) throw new Error(`ESPN ${r.status}`); return r.json(); }).then(parseTennis);
