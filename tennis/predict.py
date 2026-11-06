"""Predictions for upcoming matches: win chance, set scores, total games, game margin."""
from __future__ import annotations

from . import elo, scoring, surfaces

# (tour, surface, best of) -> (serve-point base, sd of the day-to-day gap), fitted on
# 2016-22 totals and deciding-set rates (see README "Tennis").
TOTALS = {
    ("atp", "hard", 3):(0.62, 0.04), ("atp", "clay", 3):(0.62, 0.04), ("atp", "grass", 3):(0.62, 0.03),
    ("atp", "hard", 5):(0.62, 0.04), ("atp", "clay", 5):(0.66, 0.06), ("atp", "grass", 5):(0.68, 0.06),
    ("wta", "hard", 3):(0.58, 0.06), ("wta", "clay", 3):(0.58, 0.06), ("wta", "grass", 3):(0.60, 0.05),
}
DEFAULT_TOTALS = {"atp":(0.62, 0.04), "wta":(0.58, 0.06)}


def prepare(rows: list[dict], tour: str) -> list[dict]:
    """Drop exhibitions; add surface and format. Men's Slam main draws are best of 5."""
    out = []
    for r in rows:
        if surfaces.is_exhibition(r["event"]):
            continue
        r["surface"] = surfaces.surface(r["event"], r["date"])
        r["best_of"] = 5 if (tour == "atp" and surfaces.is_slam(r["event"])
                             and not r["round"].lower().startswith("qualif")) else 3
        out.append(r)
    return out


def totals_params(tour: str, surface: str, best_of: int) -> tuple[float, float]:
    return TOTALS.get((tour, surface, best_of), DEFAULT_TOTALS[tour])


def win_chance(model: elo.TennisElo, a: str, b: str, surface: str, best_of: int, cal, tour: str) -> float:
    """Calibrated chance a beats b. Ratings are learned mostly from best-of-3, so for
    best of 5 the edge is stretched through the scoring model (the better player
    is more likely to prevail over a longer match)."""
    q = elo.calibrate(model.predict(a, b, surface), cal)
    if best_of == 5:
        base, _ = totals_params(tour, surface, 3)
        q = scoring.match_win(*scoring.fit(q, base, 3), 5)
    return q


def outlook(q: float, tour: str, surface: str, best_of: int) -> dict:
    """Set scores and distributions of total games and of A's game margin, rounded for the page."""
    base, sigma = totals_params(tour, surface, best_of)
    m = scoring.match_mix(q, base, sigma, best_of)
    tot = m["totals"]
    lo = next(i for i, v in enumerate(tot) if v > 1e-4)
    hi = max(i for i, v in enumerate(tot) if v > 1e-4)
    margins = sorted((k, v) for k, v in m["margins"].items() if v > 1e-4)
    return {"sets":{k:round(v, 4) for k, v in sorted(m["sets"].items())},
            "totals":{"from":lo, "p":[round(v, 5) for v in tot[lo:hi + 1]]},
            "margins":{"from":margins[0][0], "p":[round(m["margins"].get(k, 0.0), 5)
                                                  for k in range(margins[0][0], margins[-1][0] + 1)]}}
