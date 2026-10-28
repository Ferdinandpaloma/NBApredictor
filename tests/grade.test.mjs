import { test } from "node:test";
import assert from "node:assert/strict";
import { grade, gradeParlay, parlayOdds, profit, summarize, winAmount } from "../web/src/grade.js";

test("grading, profit and summary", () => {
  const rows = [{ date:"2026-10-25", pts:30 }, { date:"2026-10-27", pts:20 }];
  const b = (o) => ({ date:"2026-10-25", stat:"pts", line:24.5, side:"over", odds:-110, stake:1, modelP:0.6, ...o });
  assert.deepEqual(grade(b(), rows), { status:"won", actual:30 });
  assert.equal(grade(b({ side:"under" }), rows).status, "lost");
  assert.equal(grade(b({ line:30 }), rows).status, "push");
  assert.equal(grade(b({ date:"2026-10-28" }), rows, "2026-10-28T10:00:00Z").status, "pending");     // data not in yet
  assert.equal(grade(b({ date:"2026-10-26" }), rows, "2026-10-28T16:00:00Z").status, "void");        // didn't play
  assert.equal(winAmount(-110, 1).toFixed(4), "0.9091"); assert.equal(winAmount(150, 2), 3);
  assert.equal(profit(b(), "lost"), -1); assert.equal(profit(b(), "push"), 0);
  const t = summarize([{ bet:b(), status:"won" }, { bet:b({ odds:150 }), status:"lost" }, { bet:b(), status:"push" }, { bet:b(), status:"pending" }]);
  assert.deepEqual([t.won, t.lost, t.push, t.pending], [1, 1, 1, 1]);
  assert.equal(t.units.toFixed(4), "-0.0909"); assert.equal(t.roi.toFixed(4), "-0.0455"); assert.equal(t.hitRate, 0.5);
});

test("parlays", () => {
  const rows = { a:[{ date:"2026-10-25", pts:30, reb:5 }], b:[{ date:"2026-10-25", pts:12, reb:9 }] };
  const leg = (o) => ({ pid:"a", date:"2026-10-25", stat:"pts", line:24.5, side:"over", odds:-110, modelP:0.6, ...o });
  const par = (legs, o) => ({ legs, odds:parlayOdds(legs), stake:1, ...o });
  assert.equal(parlayOdds([leg(), leg()]), 264);                                           // -110 x -110
  const two = par([leg(), leg({ pid:"b", stat:"reb", line:7.5 })]);
  const g = gradeParlay(two, rows);
  assert.equal(g.status, "won"); assert.deepEqual(g.legs.map(x => x.status), ["won", "won"]);
  assert.equal(profit(two, g.status, g.odds), 2.64);
  assert.equal(gradeParlay(par([leg(), leg({ pid:"b", side:"over", line:15.5 })]), rows).status, "lost");
  // a push drops out: the parlay pays as the remaining single leg
  const pushed = gradeParlay(par([leg(), leg({ pid:"b", stat:"reb", line:9 })]), rows);
  assert.equal(pushed.status, "won"); assert.equal(pushed.odds, -110);
  assert.equal(gradeParlay(par([leg({ line:30 }), leg({ pid:"b", stat:"reb", line:9 })]), rows).status, "push");
  assert.equal(gradeParlay(par([leg(), leg({ pid:"c" })]), rows, "2026-10-25T10:00:00Z").status, "pending");
  assert.equal(gradeParlay(par([leg({ side:"under" }), leg({ pid:"c" })]), rows, "2026-10-25T10:00:00Z").status, "lost");
  const t = summarize([{ bet:two, ...g }]);
  assert.equal(t.units, 2.64);
});
