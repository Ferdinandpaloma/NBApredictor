"""Backup schedule source: stats.nba.com via the nba_api package.

Used when cdn.nba.com refuses the request. stats.nba.com's scheduleleaguev2
endpoint returns the same nested JSON as the CDN file, so parse_schedule()
handles both. We take the raw response rather than nba_api's parsed tables,
because its parser breaks on missing fields we don't even use.

Needs `pip install nba_api`. Note that stats.nba.com often blocks cloud
servers (like GitHub Actions) even when it works from a home network.
"""
from __future__ import annotations

from datetime import date


def current_season(today: date | None = None) -> str:
    """'2026-27' style season string. Seasons start in October."""
    d = today or date.today()
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def fetch_schedule_stats(season: str | None = None, timeout: int = 60) -> dict:
    from nba_api.stats.library.http import NBAStatsHTTP

    season = season or current_season()
    resp = NBAStatsHTTP().send_api_request(
        endpoint="scheduleleaguev2",
        parameters={"LeagueID": "00", "Season": season},
        timeout=timeout,
    )
    raw = resp.get_dict()
    sched = raw.get("leagueSchedule")
    if not sched or "gameDates" not in sched:
        raise ValueError(f"unexpected response from stats.nba.com: keys {list(raw)[:5]}")
    sched.setdefault("seasonYear", season)
    return raw
