"""ESPN's public NBA injury report, matched to our players by name.

The morning build uses it so players ruled out are flagged (and skipped by the
model's picks); the site also loads it live in the browser for the News tab.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
# ESPN abbreviations that differ from the NBA's.
ESPN_ABBR = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}


def name_key(name: str) -> str:
    """'Nikola Jokić' and 'Nikola Jokic', or 'Jaren Jackson Jr.' and 'Jaren Jackson', match."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s.replace("-", " "))
    return " ".join(w for w in s.split() if w not in {"jr", "sr", "ii", "iii", "iv"})


def fetch(timeout: int = 20) -> dict:
    with urllib.request.urlopen(URL, timeout=timeout) as r:
        return json.load(r)


def parse(raw: dict) -> list[dict]:
    out = []
    for team in raw.get("injuries", []):
        for x in team.get("injuries", []):
            a = x.get("athlete", {})
            abbr = a.get("team", {}).get("abbreviation", "")
            d = x.get("details") or {}
            out.append({
                "name": a.get("displayName", ""), "key": name_key(a.get("displayName", "")),
                "team": ESPN_ABBR.get(abbr, abbr), "status": x.get("status", ""),
                "note": x.get("shortComment", ""), "date": x.get("date", ""),
                "injury": " ".join(filter(None, [d.get("side") if d.get("side") != "Not Specified" else "", d.get("type")])),
                "return": d.get("returnDate", ""),
            })
    return out


def mark_out(rows: list[dict], report: list[dict]) -> int:
    """Flag projection rows (keyed "player") whose player is ruled Out. Returns how many."""
    out = {r["key"] for r in report if r["status"] == "Out"}
    n = 0
    for row in rows:
        if name_key(row["player"]) in out:
            row["out"] = True
            n += 1
    return n


def apply(players: list[dict], report: list[dict]) -> int:
    """Attach each listed player's status; anyone ruled Out is marked likely out. Returns matches."""
    by_key = {r["key"]: r for r in report}
    n = 0
    for p in players:
        r = by_key.get(name_key(p["name"]))
        if not r:
            continue
        p["injury"] = {k: r[k] for k in ("status", "note", "injury", "return", "date")}
        if r["status"] == "Out":
            p["likely_out"] = True
        n += 1
    return n
