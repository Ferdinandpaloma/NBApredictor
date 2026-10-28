"""Player box scores: past seasons from a CSV, new games from NBA's CDN.

Each finished game's box score lives at a static CDN URL, so the daily
build can fetch just the games it hasn't seen yet, even from GitHub Actions.
"""
from __future__ import annotations

import csv
import json
import re
import time
import urllib.request
from pathlib import Path

from .data import HEADERS
from .elo import Game

BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{}.json"

STATS = ["min", "pts", "reb", "oreb", "dreb", "ast", "stl", "blk", "tov",
         "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "pf", "plus_minus"]
FIELDS = ["game_id", "date", "season", "player_id", "player", "team", "opp", "home"] + STATS

# CDN box score key for each of our stat columns.
CDN_KEYS = {
    "pts": "points", "reb": "reboundsTotal", "oreb": "reboundsOffensive",
    "dreb": "reboundsDefensive", "ast": "assists", "stl": "steals", "blk": "blocks",
    "tov": "turnovers", "fgm": "fieldGoalsMade", "fga": "fieldGoalsAttempted",
    "fg3m": "threePointersMade", "fg3a": "threePointersAttempted",
    "ftm": "freeThrowsMade", "fta": "freeThrowsAttempted", "pf": "foulsPersonal",
    "plus_minus": "plusMinusPoints",
}


def parse_minutes(raw: str | float | None) -> float:
    """'PT34M12.00S' (CDN) or '34:12' or 34.2 -> minutes as a float."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    m = re.fullmatch(r"PT(?:(\d+)M)?(?:([\d.]+)S)?", raw)
    if m:
        return int(m.group(1) or 0) + float(m.group(2) or 0) / 60
    if ":" in raw:
        mins, secs = raw.split(":")
        return int(mins) + int(secs) / 60
    return float(raw)


def parse_boxscore(data: dict, game: Game) -> list[dict]:
    """Rows for every player who logged minutes in a CDN box score."""
    g = data["game"]
    rows = []
    for side, opp_side, is_home in (("homeTeam", "awayTeam", 1), ("awayTeam", "homeTeam", 0)):
        team, opp = g[side]["teamTricode"], g[opp_side]["teamTricode"]
        for p in g[side].get("players", []):
            s = p.get("statistics", {})
            mins = parse_minutes(s.get("minutes"))
            if p.get("played") != "1" or mins <= 0:
                continue
            row = {
                "game_id": game.game_id, "date": game.date, "season": game.season,
                "player_id": str(p["personId"]), "player": p.get("name", ""),
                "team": team, "opp": opp, "home": is_home, "min": round(mins, 2),
            }
            row.update({k: int(s.get(v) or 0) for k, v in CDN_KEYS.items()})
            rows.append(row)
    return rows


def fetch_boxscore(game_id: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(BOXSCORE_URL.format(game_id), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def update_logs(rows: list[dict], finished: list[Game], pause: float = 0.2) -> list[dict]:
    """Fetch box scores for finished games that aren't in `rows` yet."""
    have = {r["game_id"] for r in rows}
    missing = [g for g in finished if g.game_id not in have]
    added = []
    for g in missing:
        try:
            added += parse_boxscore(fetch_boxscore(g.game_id), g)
        except Exception as e:  # noqa: BLE001
            print(f"  box score {g.game_id} failed: {e}")
        time.sleep(pause)
    if missing:
        print(f"fetched {len(missing)} box scores ({len(added)} player rows)")
    return merge_logs(rows, added)


def merge_logs(old: list[dict], new: list[dict]) -> list[dict]:
    """Combine rows, letting the newest win on duplicate (game, player)."""
    by_key = {(r["game_id"], r["player_id"]): r for r in old}
    by_key.update({(r["game_id"], r["player_id"]): r for r in new})
    return sorted(by_key.values(), key=lambda r: (r["date"], r["game_id"], r["team"], r["player_id"]))


def load_logs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["home"] = int(r["home"])
        for k in STATS:
            r[k] = float(r[k]) if k == "min" else int(float(r[k]))
    return rows


def save_logs(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(merge_logs([], rows))
