"""A snapshot of ESPN's public NBA headlines and transactions for the News tab.

The page reads the feeds live; this copy, saved by the morning build, is what it
shows if the live feed can't be reached. Fields match web/src/news.js.
"""
from __future__ import annotations

import json
import urllib.request

from .injuries import ESPN_ABBR

API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"


def fetch(path: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.load(r)


def parse_news(raw: dict) -> list[dict]:
    out = []
    for a in raw.get("articles", []):
        url = (a.get("links", {}).get("web") or {}).get("href")
        if not a.get("headline") or not url:
            continue
        cats = a.get("categories", [])
        out.append({
            "id": a.get("id"), "type": a.get("type"), "headline": a["headline"],
            "description": a.get("description", ""), "published": a.get("published"), "url": url,
            "image": next((i["url"] for i in a.get("images", []) if i.get("url")), ""), "byline": a.get("byline", ""),
            "players": [c.get("description") for c in cats if c.get("type") == "athlete"],
            "teams": [c.get("description") for c in cats if c.get("type") == "team"],
        })
    return out


def parse_transactions(raw: dict) -> list[dict]:
    return [{"date": t.get("date"), "team": ESPN_ABBR.get(a := t.get("team", {}).get("abbreviation", ""), a),
             "text": t.get("description", "")} for t in raw.get("transactions", [])]
