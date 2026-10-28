"""Elo ratings for NBA teams (FiveThirtyEight-style).

Each team starts at 1500. After every game the winner takes rating points
from the loser; upsets and blowouts move ratings more. Between seasons,
ratings regress partway back toward the mean.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MEAN = 1505.0
K = 20.0              # how fast ratings react to results
HOME_ADV = 100.0      # Elo points for home court (~3.5 pts on the spread)
SEASON_CARRY = 0.75   # keep 75% of last season's deviation from the mean
ELO_PER_POINT = 28.0  # rough Elo-to-point-spread conversion


@dataclass
class Game:
    game_id: str
    date: str          # YYYY-MM-DD
    season: str        # e.g. "2025-26"
    home: str          # team tricode, e.g. "LAL"
    away: str
    home_pts: int | None = None
    away_pts: int | None = None
    neutral: bool = False

    @property
    def is_final(self) -> bool:
        return self.home_pts is not None and self.away_pts is not None


def win_prob(home_elo: float, away_elo: float, neutral: bool = False) -> float:
    """Probability the home team wins."""
    diff = home_elo - away_elo + (0.0 if neutral else HOME_ADV)
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


def mov_multiplier(margin: int, winner_elo_diff: float) -> float:
    """Bigger wins count more, but less so when a heavy favorite wins big."""
    return ((abs(margin) + 3) ** 0.8) / (7.5 + 0.006 * winner_elo_diff)


@dataclass
class EloModel:
    ratings: dict[str, float] = field(default_factory=dict)
    season: str | None = None
    k: float = K

    def rating(self, team: str) -> float:
        return self.ratings.setdefault(team, MEAN)

    def _new_season(self, season: str) -> None:
        if self.season is not None and season != self.season:
            for t, r in self.ratings.items():
                self.ratings[t] = MEAN + SEASON_CARRY * (r - MEAN)
        self.season = season

    def predict(self, g: Game) -> dict:
        h, a = self.rating(g.home), self.rating(g.away)
        p = win_prob(h, a, g.neutral)
        spread = (h - a + (0 if g.neutral else HOME_ADV)) / ELO_PER_POINT
        return {
            "home_elo": round(h, 1),
            "away_elo": round(a, 1),
            "home_win_prob": round(p, 4),
            "away_win_prob": round(1 - p, 4),
            "home_spread": round(-spread, 1),  # negative = home favored
        }

    def update(self, g: Game) -> float:
        """Apply a finished game. Returns the pre-game home win prob."""
        if not g.is_final:
            raise ValueError(f"game {g.game_id} is not final")
        self._new_season(g.season)
        h, a = self.rating(g.home), self.rating(g.away)
        p = win_prob(h, a, g.neutral)
        margin = g.home_pts - g.away_pts
        result = 1.0 if margin > 0 else 0.0
        adv = 0.0 if g.neutral else HOME_ADV
        winner_diff = (h + adv - a) if margin > 0 else (a - h - adv)
        delta = self.k * mov_multiplier(margin, winner_diff) * (result - p)
        self.ratings[g.home] = h + delta
        self.ratings[g.away] = a - delta
        return p


def past_picks(games: list[Game], seasons: set[str]) -> list[dict]:
    """The model's pick for every finished game in `seasons`, made from the ratings it had
    going into that game (only earlier results), with how it turned out."""
    model = EloModel()
    out = []
    for g in sorted(games, key=lambda x: (x.date, x.game_id)):
        if not g.is_final:
            continue
        model._new_season(g.season)
        pre = model.predict(g)
        model.update(g)
        if g.season not in seasons:
            continue
        home_pick = pre["home_win_prob"] >= 0.5
        winner = g.home if g.home_pts > g.away_pts else g.away
        out.append({
            "game_id": g.game_id, "date": g.date, "season": g.season, "home": g.home, "away": g.away,
            "home_pts": g.home_pts, "away_pts": g.away_pts, "home_spread": pre["home_spread"],
            "pick": g.home if home_pick else g.away,
            "p": round(pre["home_win_prob"] if home_pick else pre["away_win_prob"], 4),
            "winner": winner, "correct": (g.home if home_pick else g.away) == winner,
        })
    return out


BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]


def pick_record(picks: list[dict]) -> dict:
    """Hit rate overall and by how confident the pick was."""
    def block(xs):
        n, c = len(xs), sum(x["correct"] for x in xs)
        return {"n": n, "correct": c, "hit": round(c / n, 4) if n else None,
                "avg_p": round(sum(x["p"] for x in xs) / n, 4) if n else None}
    return {**block(picks),
            "by_conf": [{"lo": lo, "hi": min(hi, 1.0), **block([x for x in picks if lo <= x["p"] < hi])} for lo, hi in BUCKETS]}


def backtest(games: list[Game], skip_first_season: bool = True) -> dict:
    """Replay games in order, scoring each pre-game prediction.

    The first season is skipped by default because everyone starts at 1500,
    so early predictions are meaningless.
    """
    model = EloModel()
    first = games[0].season if games else None
    n = correct = 0
    brier = logloss = 0.0
    for g in sorted(games, key=lambda x: (x.date, x.game_id)):
        if not g.is_final:
            continue
        p = model.update(g)
        if skip_first_season and g.season == first:
            continue
        won = g.home_pts > g.away_pts
        n += 1
        correct += (p >= 0.5) == won
        brier += (p - won) ** 2
        q = min(max(p if won else 1 - p, 1e-9), 1.0)
        logloss -= math.log(q)
    if n == 0:
        return {"games": 0}
    return {
        "games": n,
        "accuracy": round(correct / n, 4),
        "brier": round(brier / n, 4),
        "log_loss": round(logloss / n, 4),
    }
