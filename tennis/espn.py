"""ATP and WTA singles matches from ESPN's public scoreboard feed.

One request returns every tournament active in a date range, with each
match's players, round and set scores, so a month of tennis is one call.
ESPN doesn't give the surface; see surfaces.py.
"""
from __future__ import annotations

import csv
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={dates}"
TOURS = ("atp", "wta")
SINGLES = {"atp":"mens-singles", "wta":"womens-singles"}
STATUS = {"STATUS_FINAL":"final", "STATUS_RETIRED":"retired", "STATUS_WALKOVER":"walkover"}
FIELDS = ["match_id", "date", "tour", "event_id", "event", "round", "best_of", "status",
          "winner_id", "winner", "winner_country", "loser_id", "loser", "loser_country",
          "w_games", "l_games", "w_tb", "l_tb"]
ET = ZoneInfo("America/New_York")


def et_date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).date().isoformat()


def fetch(tour: str, start: str, end: str) -> dict:
    """Raw scoreboard for tournaments active between two dates (YYYYMMDD)."""
    req = urllib.request.Request(API.format(tour=tour, dates=f"{start}-{end}"), headers={"User-Agent":"nba-predictor"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _player(c: dict) -> dict:
    a = c.get("athlete") or {}
    return {"id":str(c.get("id", "")), "name":a.get("displayName", ""), "country":(a.get("flag") or {}).get("alt", ""),
            "games":[int(l["value"]) for l in c.get("linescores", []) if l.get("value") is not None],
            "tb":[l.get("tiebreak") for l in c.get("linescores", []) if l.get("value") is not None],
            "winner":bool(c.get("winner"))}


def _is_qualifying(rnd: str) -> bool:
    return rnd.lower().startswith("qualif")


def parse(raw: dict, tour: str) -> tuple[list[dict], list[dict]]:
    """(finished matches, upcoming matches) in singles main draws and qualifying.
    Upcoming ones carry both players (TBD slots are skipped) and the match start."""
    done, todo = [], []
    for e in raw.get("events", []):
        for g in e.get("groupings", []):
            if (g.get("grouping") or {}).get("slug") != SINGLES[tour]:
                continue
            for c in g.get("competitions", []):
                ps = [_player(x) for x in c.get("competitors", [])]
                if len(ps) != 2 or any(not p["id"] or p["id"].startswith("-") for p in ps):
                    continue
                st = (c.get("status") or {}).get("type") or {}
                rnd = (c.get("round") or {}).get("displayName", "")
                base = {"match_id":str(c["id"]), "date":et_date(c.get("date") or e["date"]), "tour":tour,
                        "event_id":str(e["id"]), "event":e.get("name", ""), "round":rnd,
                        "best_of":((c.get("format") or {}).get("regulation") or {}).get("periods", 3)}
                if st.get("state") == "post":
                    status = STATUS.get(st.get("name"))
                    w = [p for p in ps if p["winner"]]
                    if not status or len(w) != 1:
                        continue  # cancelled, or no winner recorded
                    w, l = w[0], next(p for p in ps if not p["winner"])
                    done.append({**base, "status":status,
                                 "winner_id":w["id"], "winner":w["name"], "winner_country":w["country"],
                                 "loser_id":l["id"], "loser":l["name"], "loser_country":l["country"],
                                 "w_games":" ".join(map(str, w["games"])), "l_games":" ".join(map(str, l["games"])),
                                 "w_tb":" ".join("" if t is None else str(t) for t in w["tb"]),
                                 "l_tb":" ".join("" if t is None else str(t) for t in l["tb"])})
                elif st.get("state") in ("pre", "in"):
                    todo.append({**base, "state":st["state"], "start":c.get("date") if c.get("timeValid", True) else None,
                                 "p1_id":ps[0]["id"], "p1":ps[0]["name"], "p1_country":ps[0]["country"],
                                 "p2_id":ps[1]["id"], "p2":ps[1]["name"], "p2_country":ps[1]["country"]})
    return done, todo


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["date"], r["event_id"], r["match_id"])))


def merge(old: list[dict], new: list[dict]) -> list[dict]:
    by = {(r["tour"], r["match_id"]): r for r in old}
    by.update({(r["tour"], r["match_id"]): r for r in new})
    return list(by.values())
