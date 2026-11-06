"""Surface-aware Elo for tennis players (one rating pool per tour).

Every player has an overall rating and one per surface. A match is predicted
from a blend of the two (SURFACE_WEIGHT on the surface rating), and both
update after it. K shrinks as a player's match count grows, so newcomers
move fast and veterans slowly (FiveThirtyEight's tennis formula).

Walkovers aren't matches and are skipped. Raw Elo probabilities go through
a logistic calibration fitted on earlier years only, as for the NBA model.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from nbaelo.elo import IDENTITY, Calibration, calibrate, fit_calibration

START = 1500.0
SURFACE_WEIGHT = 0.3  # tuned on 2023-26: 0.3 beats 0.0 and 0.5 on Brier for both tours
K_NUM, K_OFFSET, K_SHAPE = 250.0, 5.0, 0.4
SURFACES = ("hard", "clay", "grass")


def k_factor(n: int) -> float:
    return K_NUM / (n + K_OFFSET) ** K_SHAPE


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


@dataclass
class Player:
    overall: float = START
    n: int = 0
    surf: dict = field(default_factory=lambda: defaultdict(lambda: START))
    n_surf: dict = field(default_factory=lambda: defaultdict(int))
    last: str = ""

    def rating(self, surface: str, w: float = SURFACE_WEIGHT) -> float:
        return (1 - w) * self.overall + w * self.surf[surface]


class TennisElo:
    def __init__(self, surface_weight: float = SURFACE_WEIGHT, skip_retired: bool = False):
        self.players: dict[str, Player] = defaultdict(Player)
        self.w = surface_weight
        self.skip_retired = skip_retired

    def predict(self, a: str, b: str, surface: str) -> float:
        """Raw chance that a beats b on this surface."""
        return expected(self.players[a].rating(surface, self.w), self.players[b].rating(surface, self.w))

    def update(self, m: dict) -> float | None:
        """Apply a finished match (winner/loser ids, surface). Returns the raw pre-match
        chance the winner had, or None if the match doesn't count."""
        if m["status"] == "walkover":
            return None
        w, l, s = self.players[m["winner_id"]], self.players[m["loser_id"]], m["surface"]
        p = expected(w.rating(s, self.w), l.rating(s, self.w))
        if self.skip_retired and m["status"] == "retired":
            return p
        po = expected(w.overall, l.overall)
        ps = expected(w.surf[s], l.surf[s])
        w.overall += k_factor(w.n) * (1 - po)
        l.overall -= k_factor(l.n) * (1 - po)
        w.surf[s] += k_factor(w.n_surf[s]) * (1 - ps)
        l.surf[s] -= k_factor(l.n_surf[s]) * (1 - ps)
        for x in (w, l):
            x.n += 1
            x.n_surf[s] += 1
            x.last = m["date"]
        return p


def replay(matches: list[dict], **kw) -> tuple[TennisElo, list[tuple[dict, float]]]:
    """Run every match in date order. Returns the final model and (match, raw p for the
    winner) for each match that counted."""
    model = TennisElo(**kw)
    out = []
    for m in sorted(matches, key=lambda r: (r["date"], r["match_id"])):
        p = model.update(m)
        if p is not None:
            out.append((m, p))
    return model, out


def _pairs(rows: list[tuple[dict, float]]) -> list[tuple[float, int]]:
    """Calibration pairs with the favourite-agnostic orientation: alternate which player
    is "A" by match id so the outcome isn't always 1."""
    return [(p, 1) if int(m["match_id"]) % 2 else (1 - p, 0) for m, p in rows]


def calibration_for(rows: list[tuple[dict, float]], year: int, warmup: int = 2) -> Calibration:
    """Calibration fitted on matches from after the warm-up years up to (not including) `year`."""
    first = min(int(m["date"][:4]) for m, _ in rows) + warmup
    return fit_calibration(_pairs([(m, p) for m, p in rows if first <= int(m["date"][:4]) < year]))


def backtest(rows: list[tuple[dict, float]], years: list[int], min_matches: int = 0,
             counts: dict | None = None) -> dict:
    """Walk-forward accuracy, Brier and log loss per test year, calibrated and raw.
    Tested on completed matches only (a retirement says little about who was better)."""
    out = {}
    for y in years:
        cal = calibration_for(rows, y)
        test = [(m, p) for m, p in rows if int(m["date"][:4]) == y and m["status"] == "final"]
        if not test:
            continue
        acc = brier = ll = rb = 0.0
        for m, p in test:
            q = calibrate(p, cal)
            acc += q > 0.5
            brier += (1 - q) ** 2
            rb += (1 - p) ** 2
            ll -= math.log(max(q, 1e-9))
        n = len(test)
        out[y] = {"n":n, "accuracy":acc / n, "brier":brier / n, "brier_raw":rb / n, "log_loss":ll / n, "cal":cal}
    return out


__all__ = ["TennisElo", "replay", "backtest", "calibration_for", "calibrate", "IDENTITY", "SURFACES"]
