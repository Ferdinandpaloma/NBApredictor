import { test } from "node:test";
import assert from "node:assert/strict";
import { etDate, legNow, parseBox, parseScoreboard, parseTennis, statOf } from "../web/src/live.js";

const comp = (abbr, homeAway, score) => ({ homeAway, score:String(score), team:{ abbreviation:abbr } });

test("scoreboard: our team codes and Eastern dates", () => {
  const raw = { events:[{ id:"1", date:"2026-11-05T03:30Z", competitions:[{
    competitors:[comp("LAC", "home", 54), comp("UTAH", "away", 50)],
    status:{ period:2, displayClock:"4:12", type:{ state:"in", shortDetail:"4:12 - 2nd" } } }] }] };
  const [g] = parseScoreboard(raw);
  assert.deepEqual([g.date, g.away, g.home, g.awayScore, g.homeScore, g.state], ["2026-11-04", "UTA", "LAC", 50, 54, "in"]);
  assert.equal(etDate("2026-11-05T04:59:00Z"), "2026-11-04");
});

test("box score rows by name, without players who didn't play", () => {
  const raw = { boxscore:{ players:[{ team:{ abbreviation:"GS" }, statistics:[{
    keys:["minutes", "points", "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "rebounds", "assists", "steals", "blocks"],
    athletes:[{ athlete:{ displayName:"Stephen Curry" }, stats:["30", "27", "5-11", "4", "6", "1", "0"] },
              { athlete:{ displayName:"Bench Guy" }, didNotPlay:true, stats:[] }] }] }] } };
  const box = parseBox(raw);
  assert.equal(box.size, 1);
  const r = box.get("stephen curry");
  assert.deepEqual([r.team, r.pts, r.fg3m, r.fg3a, r.reb, r.ast], ["GSW", 27, 5, 11, 4, 6]);
  assert.equal(statOf(r, "pra"), 37); assert.equal(statOf(r, "stocks"), 1);
});

test("where a bet stands mid-game and at the final", () => {
  const live = { state:"in" }, final = { state:"post" }, row = { pts:20 };
  const over = { stat:"pts", line:24.5, side:"over" }, under = { ...over, side:"under" };
  assert.deepEqual(legNow(over, live, row), { status:"live", cur:20, need:5, final:false });
  assert.equal(legNow(over, live, { pts:25 }).status, "won");    // an over cashes as soon as it's passed
  assert.equal(legNow(under, live, { pts:25 }).status, "lost");  // an under busts as soon as it's passed
  assert.equal(legNow(under, final, row).status, "won");
  assert.equal(legNow({ ...over, line:20 }, final, row).status, "push");
  assert.equal(legNow(over, live, null).status, "dnp");
  assert.equal(legNow(over, final, null).status, "void");
  assert.equal(legNow(over, { state:"pre" }, row).status, "pre");
});

test("tennis scoreboard: set scores, tiebreaks and who's serving by match id", () => {
  const p = (id, games, extra = {}) => ({ id, linescores:games.map(([v, t]) => ({ value:v, ...(t ? { tiebreak:t } : {}) })), ...extra });
  const raw = { events:[{ groupings:[
    { grouping:{ slug:"mens-singles" }, competitions:[
      { id:"186507", status:{ type:{ state:"in", shortDetail:"2nd Set" } },
        competitors:[p("3782", [[7, 7], [3]], { possession:true }), p("2989", [[6, 4], [2]])] }] },
    { grouping:{ slug:"mens-doubles" }, competitions:[{ id:"x", status:{ type:{ state:"in" } }, competitors:[] }] }] }] };
  const m = parseTennis(raw);
  assert.equal(m.size, 1);
  const g = m.get("186507");
  assert.equal(g.state, "in"); assert.equal(g.detail, "2nd Set");
  assert.deepEqual(g.players["3782"], { games:[7, 3], tb:[7, null], winner:false, serving:true });
  assert.deepEqual(g.players["2989"].games, [6, 2]);
});
