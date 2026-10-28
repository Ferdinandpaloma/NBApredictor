// Grading saved bets against box scores. Pure functions, no Firebase.

// Profit on a winning bet of `stake` units at American odds.
export const winAmount = (odds, stake) => stake * (odds > 0 ? odds / 100 : 100 / -odds);

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

export function profit(bet, status) {
  if (status === "won") return winAmount(bet.odds, bet.stake);
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
  const units = done.reduce((a, g) => a + profit(g.bet, g.status), 0);
  const decided = done.filter(g => g.status !== "push");
  return {
    won, lost, push,
    pending: graded.filter(g => g.status === "pending").length,
    units, roi: staked ? units / staked : null,
    modelP: decided.length ? decided.reduce((a, g) => a + g.bet.modelP, 0) / decided.length : null,
    hitRate: decided.length ? won / decided.length : null,
  };
}
