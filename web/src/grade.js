// Grading saved bets against box scores. Pure functions, no Firebase.

// Profit on a winning bet of `stake` units at American odds.
export const winAmount = (odds, stake) => stake * (odds > 0 ? odds / 100 : 100 / -odds);
export const toDecimal = odds => 1 + (odds > 0 ? odds / 100 : 100 / -odds);
export const toAmerican = dec => Math.round(dec >= 2 ? (dec - 1) * 100 : -100 / (dec - 1));
// A parlay's odds from its legs' odds, as a book would price independent legs.
export const parlayOdds = legs => toAmerican(legs.reduce((a, l) => a * toDecimal(l.odds), 1));

// bet: { date, stat, line, side: "over" | "under" }
// rows: the player's game log ({ date, pts, ... }), builtAt: when the data was last built.
// A player with no row once that night's games are in the data didn't play: the bet is void.
export function grade(bet, rows, builtAt) {
  const row = rows.find(r => r.date === bet.date);
  if (!row) {
    const dataCovers = builtAt && Date.parse(builtAt) > Date.parse(bet.date + "T00:00:00Z") + 36 * 36e5;
    return { status: dataCovers ? "void" : "pending" };
  }
  const actual = row[bet.stat];
  if (actual === bet.line) return { status: "push", actual };
  const over = actual > bet.line;
  return { status: over === (bet.side === "over") ? "won" : "lost", actual };
}

// Parlay: { legs: [bet, ...], odds, stake }. Any losing leg loses it; a leg that
// pushes or is void drops out and the odds shrink to the remaining legs, as books do.
// rowsByPid: each leg player's game log. Returns the legs' grades too, and the odds it pays at.
export function gradeParlay(bet, rowsByPid, builtAt) {
  const legs = bet.legs.map(l => grade(l, rowsByPid[l.pid] || [], builtAt));
  const out = legs.filter(g => g.status === "push" || g.status === "void");
  const left = bet.legs.length - out.length;
  const dropped = bet.legs.filter((l, i) => out.includes(legs[i])).reduce((a, l) => a * toDecimal(l.odds), 1);
  const odds = left ? toAmerican(Math.max(toDecimal(bet.odds) / dropped, 1.01)) : bet.odds;
  const status = legs.some(g => g.status === "lost") ? "lost"
    : legs.some(g => g.status === "pending") ? "pending"
    : left ? "won" : "push";
  return { status, legs, odds };
}

export function profit(bet, status, odds = bet.odds) {
  if (status === "won") return winAmount(odds, bet.stake);
  if (status === "lost") return -bet.stake;
  return 0;
}

// Record, units won and ROI over graded bets; also how often the model's side hit
// compared with the probability it gave.
export function summarize(graded) {
  const done = graded.filter(g => g.status === "won" || g.status === "lost" || g.status === "push");
  const won = done.filter(g => g.status === "won").length;
  const lost = done.filter(g => g.status === "lost").length;
  const push = done.filter(g => g.status === "push").length;
  const staked = done.filter(g => g.status !== "push").reduce((a, g) => a + g.bet.stake, 0);
  const units = done.reduce((a, g) => a + profit(g.bet, g.status, g.odds), 0);
  const decided = done.filter(g => g.status !== "push");
  return {
    won, lost, push,
    pending: graded.filter(g => g.status === "pending").length,
    units, roi: staked ? units / staked : null,
    modelP: decided.length ? decided.reduce((a, g) => a + g.bet.modelP, 0) / decided.length : null,
    hitRate: decided.length ? won / decided.length : null,
  };
}
