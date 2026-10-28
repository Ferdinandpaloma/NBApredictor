import { test } from "node:test";
import assert from "node:assert/strict";
import { nameKey, parseInjuries, parseNews, parseTransactions, teamCode } from "../web/src/news.js";

test("names and team codes match ours", () => {
  assert.equal(nameKey("Nikola Jokić"), nameKey("Nikola Jokic"));
  assert.equal(nameKey("Jaren Jackson Jr."), "jaren jackson");
  assert.equal(nameKey("Karl-Anthony Towns"), "karl anthony towns");
  assert.deepEqual(["GS", "NY", "UTAH", "BOS"].map(teamCode), ["GSW", "NYK", "UTA", "BOS"]);
});

test("feeds parse", () => {
  const inj = parseInjuries({ injuries:[{ injuries:[{ status:"Out", shortComment:"Surgery.", date:"2026-10-19T19:38Z",
    athlete:{ displayName:"Mouhamed Gueye", position:{ abbreviation:"F" }, team:{ abbreviation:"ATL" } },
    details:{ side:"Left", type:"Foot", returnDate:"2026-11-20" } }] }] });
  assert.deepEqual(inj[0], { name:"Mouhamed Gueye", key:"mouhamed gueye", team:"ATL", pos:"F", status:"Out",
    note:"Surgery.", date:"2026-10-19T19:38Z", injury:"Left Foot", return:"2026-11-20" });
  const news = parseNews({ articles:[{ id:"1", type:"Story", headline:"H", published:"2026-10-28T22:26:07Z",
    links:{ web:{ href:"https://espn.com/x" } }, images:[{ url:"https://img" }],
    categories:[{ type:"team", description:"Dallas Mavericks" }, { type:"athlete", description:"A B" }] }, { headline:"no link" }] });
  assert.equal(news.length, 1); assert.deepEqual(news[0].teams, ["Dallas Mavericks"]); assert.equal(news[0].image, "https://img");
  assert.deepEqual(parseTransactions({ transactions:[{ date:"d", team:{ abbreviation:"NY" }, description:"Waived X." }] }),
    [{ date:"d", team:"NYK", text:"Waived X." }]);
});
