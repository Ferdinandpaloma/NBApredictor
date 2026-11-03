"""Sportsbook player-prop lines from The Odds API (the-odds-api.com).

Needs a key: set ODDS_API_KEY, or put it in ~/.config/nba-predictor/odds_api_key
(outside the repo, so it's never committed). Without one, nothing is fetched.

Cost: each game costs one credit per market returned (one region, "us"). The
free plan has 500 credits a month, enough for MARKETS (two markets) once a day;
a paid plan can take more via ODDS_MARKETS. `fetch_slate` stops before it would
run the month's credits down below what the remaining days need.
"""
from __future__ import annotations

import json
import os
import statistics
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .injuries import name_key

API = "https://api.the-odds-api.com/v4/sports/basketball_nba"
KEY_FILE = Path.home() / ".config" / "nba-predictor" / "odds_api_key"
STAT = {
    "player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3m",
    "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr",
    "player_points_assists": "pa", "player_rebounds_assists": "ra",
}
MARKETS = ["player_points", "player_points_rebounds_assists"]  # fits the free plan once a day
RESERVE_GAMES = 6  # credits kept per remaining day of the month, per market (a slate averages ~7.5 games)
TEAMS = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def api_key() -> str | None:
    k = os.environ.get("ODDS_API_KEY", "").strip()
    if not k and KEY_FILE.exists():
        k = KEY_FILE.read_text().strip()
    return k or None


def markets() -> list[str]:
    env = os.environ.get("ODDS_MARKETS", "").strip()
    return [m for m in env.split(",") if m in STAT] if env else MARKETS


def _get(path: str, key: str, **params) -> tuple[object, int | None]:
    q = urllib.parse.urlencode({"apiKey": key, **params})
    with urllib.request.urlopen(f"{API}/{path}?{q}", timeout=30) as r:
        left = r.headers.get("x-requests-remaining")
        return json.load(r), (int(float(left)) if left is not None else None)


def parse(event: dict) -> list[dict]:
    """One row per (bookmaker, player, market): the line and both prices (American)."""
    rows = []
    for bk in event.get("bookmakers", []):
        for m in bk.get("markets", []):
            stat = STAT.get(m.get("key"))
            if not stat:
                continue
            sides = defaultdict(dict)
            for o in m.get("outcomes", []):
                if o.get("point") is None or not o.get("description"):
                    continue
                sides[(o["description"], o["point"])][o["name"].lower()] = o["price"]
            for (player, line), pr in sides.items():
                if "over" in pr and "under" in pr:
                    rows.append({"player": player, "key": name_key(player), "stat": stat, "book": bk["title"],
                                 "line": float(line), "over": int(pr["over"]), "under": int(pr["under"])})
    return rows


def consensus(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Per (player key, stat): the line most books post, median prices at that line, and
    the best price on each side across all books at that line."""
    by = defaultdict(list)
    for r in rows:
        by[(r["key"], r["stat"])].append(r)
    out = {}
    for k, rs in by.items():
        counts = Counter(r["line"] for r in rs)
        line = max(counts, key=lambda x: (counts[x], -abs(x - statistics.median(r["line"] for r in rs))))
        at = [r for r in rs if r["line"] == line]
        bo, bu = max(at, key=lambda r: _payout(r["over"])), max(at, key=lambda r: _payout(r["under"]))
        out[k] = {"line": line, "over": _median_odds([r["over"] for r in at]),
                  "under": _median_odds([r["under"] for r in at]), "books": len(at),
                  "best_over": [bo["over"], bo["book"]], "best_under": [bu["under"], bu["book"]]}
    return out


def _payout(o: int) -> float:
    return o / 100 if o > 0 else 100 / -o


def _median_odds(xs: list[int]) -> int:
    """Median by payout (American odds jump from -100 to +100, so don't average them)."""
    m = statistics.median(_payout(x) for x in xs)
    return round(m * 100) if m >= 1 else round(-100 / m)


def fetch_slate(day: str, key: str, log=print) -> dict:
    """Lines for every game starting on `day` (US Eastern date, YYYY-MM-DD).
    Returns {(away, home): {(player key, stat): consensus}}."""
    events, left = _get("events", key)  # the events list is free
    et = ZoneInfo("America/New_York")
    todays = [e for e in events
              if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(et).date().isoformat() == day]
    mk = markets()
    if left is not None:
        d = date.fromisoformat(day)
        next_month = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        # Hold back enough for ~RESERVE_GAMES games a day for the rest of the month.
        reserve = max((next_month - d).days - 1, 0) * RESERVE_GAMES * len(mk)
        budget = max(left - reserve, 0) // len(mk)
        if budget < len(todays):
            log(f"odds: {left} credits left this month; fetching {budget} of {len(todays)} games")
            todays = todays[:budget]
    out = {}
    for e in todays:
        home, away = TEAMS.get(e["home_team"]), TEAMS.get(e["away_team"])
        if not home or not away:
            continue
        data, left = _get(f"events/{e['id']}/odds", key, regions="us", markets=",".join(mk), oddsFormat="american")
        out[(away, home)] = consensus(parse(data))
    log(f"odds: {len(out)} games, {sum(len(v) for v in out.values())} player lines; {left} credits left")
    return out
