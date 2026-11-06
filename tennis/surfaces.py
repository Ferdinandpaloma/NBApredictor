"""Surface and level for a tournament, from its name (ESPN doesn't give either).

Names change with sponsors ("Barcelona Open Banc Sabadell", "ATP Barcelona
Open BancSabadell"), so matching is by keyword. Anything unmatched is hard
court, which is right for most of the calendar. A few venues changed surface
over the years, so some rules depend on the month.
"""
from __future__ import annotations

import re

SLAMS = ("australian open", "french open", "roland garros", "wimbledon", "us open")
EXHIBITIONS = ("laver cup", "next gen", "hopman cup", "mubadala", "six kings", "tie break tens", "ultimate tennis showdown")

CLAY = (
    "french open", "roland garros", "monte-carlo", "monte carlo", "madrid", "internazionali", "italia", "rome",
    "barcelona", "estoril", "portugal", "nice", "serbia", "belgrade", "bmw open", "munich", "clay court",
    "claycourt", "hassan", "marrakech", "casablanca", "bucharest", "romania", "nastase", "tiriac", "power horse",
    "world team", "geneva", "lyon", "hamburg", "german open", "german tennis championships", "bet-at-home",
    "gstaad", "swiss open", "kitzbuhel", "kitzbühel", "austrian open", "generali open", "umag", "croatia open",
    "bastad", "båstad", "swedish open", "nordea", "copa claro", "argentina open", "buenos aires", "brasil open",
    "rio open", "copa telmex", "vtr open", "movistar open", "chile open", "santiago", "ecuador", "quito",
    "cordoba", "córdoba", "sao paulo", "são paulo", "istanbul", "charleston", "family circle", "credit one",
    "volvo car open", "rabat", "lalla meryem", "strasbourg", "internationaux de strasbourg",
    "palermo", "bad gastein", "budapest", "bogota", "bogotá", "copa colsanitas",
    "lausanne", "jurmala", "porsche tennis grand prix",
    "j&t banka", "parma", "emilia-romagna", "cagliari", "sardegna", "belgrade open",
    "houston", "u.s. men's clay", "us men's clay", "auvergne",
)
GRASS = (
    "wimbledon", "queen", "aegon championships", "aegon international", "aegon open", "aegon classic",
    "eastbourne", "halle", "gerry weber", "terra wortmann", "hertogenbosch", "unicef open", "topshelf",
    "libema", "libéma", "rosmalen", "hall of fame", "newport", "mallorca", "boss open", "nottingham", "antalya",
    "cinch", "hsbc championships", "birmingham", "berlin", "bad homburg", "viking", "rothesay", "ecotrans",
    "bett1open", "bett1 open", "grass",
)
# Name fragments that don't decide on their own: (keyword, month -> surface).
BY_MONTH = {
    "stuttgart": lambda m: "grass" if m == 6 else "clay",   # Mercedes Cup: clay in July until 2014, grass in June since 2015
    "mercedes cup": lambda m: "grass" if m == 6 else "clay",
    "prague": lambda m: "clay" if m <= 6 else "hard",         # WTA Prague: clay in spring, hard in summer since 2021
}


def _has(name: str, words) -> bool:
    return any(w and re.search(r"(?<![a-z])" + re.escape(w), name) for w in words)


def surface(event: str, date: str) -> str:
    name, month, year = event.lower(), int(date[5:7]), int(date[:4])
    if "acapulco" in name or "abierto mexicano" in name:
        return "clay" if year < 2014 else "hard"
    for k, rule in BY_MONTH.items():
        if k in name:
            return rule(month)
    if _has(name, GRASS) and 5 <= month <= 7:
        return "grass"
    if _has(name, CLAY):
        return "clay"
    return "hard"


def is_slam(event: str) -> bool:
    name = event.lower().strip()
    return any(name == s or name.startswith(s + " ") for s in SLAMS)


def is_exhibition(event: str) -> bool:
    return _has(event.lower(), EXHIBITIONS)
