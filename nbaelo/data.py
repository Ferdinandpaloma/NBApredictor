"""Loading games: past seasons from a CSV, current season from NBA's CDN.

The CDN schedule feed (cdn.nba.com) is a static JSON file, so unlike
stats.nba.com it works fine from GitHub Actions runners.
"""
from __future__ import annotations

import csv
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .elo import Game

SCHEDULE_URLS = [
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
]

# NBA's CDN returns 403 to requests that don't look like a browser on nba.com.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}

# gameId prefixes: 001 preseason, 002 regular season, 003 All-Star,
# 004 playoffs, 005 play-in, 006 NBA Cup final. We rate everything but
# preseason and All-Star.
RATED_PREFIXES = ("002", "004", "005", "006")
FINAL = 3

CSV_FIELDS = ["game_id", "date", "season", "home", "away", "home_pts", "away_pts"]


def fetch_schedule(urls: list[str] = SCHEDULE_URLS, timeout: int = 30) -> dict:
    """Try the CDN files, then stats.nba.com via nba_api. Raise if all fail."""
    errors = []
    for url in urls:
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            errors.append(f"  {url}\n    -> {e}")

    print("CDN schedule unavailable; trying stats.nba.com via nba_api...")
    try:
        from .statsapi import fetch_schedule_stats
        return fetch_schedule_stats()
    except ImportError:
        errors.append("  stats.nba.com\n    -> nba_api isn't installed (pip install nba_api pandas)")
    except Exception as e:  # noqa: BLE001
        errors.append(f"  stats.nba.com\n    -> {e}")

    raise RuntimeError("Couldn't download the NBA schedule:\n" + "\n".join(errors))


def _date(game: dict) -> str:
    raw = game.get("gameDateEst") or game.get("gameDateTimeUTC") or ""
    return raw[:10]


def parse_schedule(data: dict) -> tuple[list[Game], list[Game]]:
    """Split the CDN feed into (finished games, upcoming games)."""
    sched = data["leagueSchedule"]
    season = sched["seasonYear"]
    finished, upcoming = [], []
    for day in sched["gameDates"]:
        for g in day["games"]:
            gid = g["gameId"]
            if not gid.startswith(RATED_PREFIXES):
                continue
            home, away = g["homeTeam"], g["awayTeam"]
            if not home.get("teamTricode") or not away.get("teamTricode"):
                continue  # playoff slots with TBD teams
            game = Game(
                game_id=gid,
                date=_date(g),
                season=season,
                home=home["teamTricode"],
                away=away["teamTricode"],
                neutral=bool(g.get("isNeutral", False)),
            )
            if g.get("gameStatus") == FINAL:
                game.home_pts = int(home["score"])
                game.away_pts = int(away["score"])
                finished.append(game)
            elif g.get("gameStatus") == 1:
                upcoming.append(game)
    return finished, upcoming


def load_history(path: Path) -> list[Game]:
    if not path.exists():
        return []
    with path.open() as f:
        return [
            Game(
                game_id=r["game_id"], date=r["date"], season=r["season"],
                home=r["home"], away=r["away"],
                home_pts=int(r["home_pts"]), away_pts=int(r["away_pts"]),
            )
            for r in csv.DictReader(f)
        ]


def save_history(path: Path, games: list[Game]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for g in sorted(games, key=lambda x: (x.date, x.game_id)):
            w.writerow({k: getattr(g, k) for k in CSV_FIELDS})


def merge(history: list[Game], current: list[Game]) -> list[Game]:
    """Combine sources, letting the newest data win on duplicate game ids."""
    by_id = {g.game_id: g for g in history}
    by_id.update({g.game_id: g for g in current})
    return sorted(by_id.values(), key=lambda x: (x.date, x.game_id))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
