// ESPN's public NBA feeds (headlines, injury report, transactions), read live in the browser.
// Pure helpers are exported for the tests; nothing here touches the page.
const API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/";
// ESPN abbreviations that differ from the NBA's.
const ESPN_ABBR = { GS:"GSW", NY:"NYK", NO:"NOP", SA:"SAS", UTAH:"UTA", WSH:"WAS" };
export const teamCode = a => ESPN_ABBR[a] || a || "";

// "Nikola Jokić" and "Nikola Jokic", or "Jaren Jackson Jr." and "Jaren Jackson", match.
const SUFFIX = new Set(["jr", "sr", "ii", "iii", "iv"]);
export const nameKey = n => String(n || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
  .replace(/-/g, " ").replace(/[^a-z ]/g, "").split(/\s+/).filter(w => w && !SUFFIX.has(w)).join(" ");

const get = async path => {
  const r = await fetch(API + path, { cache:"no-store" });
  if (!r.ok) throw new Error(`ESPN ${r.status}`);
  return r.json();
};

export function parseInjuries(raw) {
  return (raw.injuries || []).flatMap(t => (t.injuries || []).map(x => {
    const a = x.athlete || {}, d = x.details || {};
    return {
      name:a.displayName || "", key:nameKey(a.displayName), team:teamCode(a.team?.abbreviation),
      pos:a.position?.abbreviation || "", status:x.status || "", note:x.shortComment || "", date:x.date || "",
      injury:[d.side && d.side !== "Not Specified" ? d.side : "", d.type].filter(Boolean).join(" "),
      return:d.returnDate || "",
    };
  }));
}

export function parseNews(raw) {
  return (raw.articles || []).filter(a => a.headline && a.links?.web?.href).map(a => ({
    id:a.id, type:a.type, headline:a.headline, description:a.description || "", published:a.published,
    url:a.links.web.href, image:(a.images || []).find(i => i.url)?.url || "", byline:a.byline || "",
    players:(a.categories || []).filter(c => c.type === "athlete").map(c => c.description),
    teams:(a.categories || []).filter(c => c.type === "team").map(c => c.description),
  }));
}

export function parseTransactions(raw) {
  return (raw.transactions || []).map(t => ({ date:t.date, team:teamCode(t.team?.abbreviation), text:t.description || "" }));
}

// Each loader resolves to { items, live, at }: the live feed if ESPN answers, otherwise the
// copy saved by the morning build (site/news.json). Rejects only if neither is available.
let snap;
const snapshot = () => snap ||= fetch("news.json").then(r => r.ok ? r.json() : {}).catch(() => ({}));
const load = (path, parse, key) => get(path).then(parse).then(items => ({ items, live:true, at:new Date().toISOString() }))
  .catch(async e => {
    const s = await snapshot();
    if (!s[key]) throw e;
    return { items:s[key], live:false, at:s.built_at };
  });
export const loadInjuries = () => load("injuries", parseInjuries, "injuries");
export const loadNews = () => load("news?limit=40", parseNews, "news");
export const loadTransactions = () => load("transactions", parseTransactions, "transactions");

export const TEAM_NAMES = {
  ATL:"Atlanta Hawks", BKN:"Brooklyn Nets", BOS:"Boston Celtics", CHA:"Charlotte Hornets", CHI:"Chicago Bulls",
  CLE:"Cleveland Cavaliers", DAL:"Dallas Mavericks", DEN:"Denver Nuggets", DET:"Detroit Pistons", GSW:"Golden State Warriors",
  HOU:"Houston Rockets", IND:"Indiana Pacers", LAC:"LA Clippers", LAL:"Los Angeles Lakers", MEM:"Memphis Grizzlies",
  MIA:"Miami Heat", MIL:"Milwaukee Bucks", MIN:"Minnesota Timberwolves", NOP:"New Orleans Pelicans", NYK:"New York Knicks",
  OKC:"Oklahoma City Thunder", ORL:"Orlando Magic", PHI:"Philadelphia 76ers", PHX:"Phoenix Suns", POR:"Portland Trail Blazers",
  SAC:"Sacramento Kings", SAS:"San Antonio Spurs", TOR:"Toronto Raptors", UTA:"Utah Jazz", WAS:"Washington Wizards",
};
