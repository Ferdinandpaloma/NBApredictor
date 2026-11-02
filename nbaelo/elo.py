"""Elo ratings for NBA teams (FiveThirtyEight-style).

Each team starts at 1500. After every game the winner takes rating points
from the loser; upsets and blowouts move ratings more. Between seasons,
ratings regress partway back toward the mean.

Raw Elo is overconfident (its 75-80% picks won ~70%) and gives home court
too much weight since 2020, so published probabilities go through a
calibration fitted on earlier seasons only: logit(p') = a * logit(p) + b.
Ratings themselves still update from the raw probabilities.
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


Calibration = tuple[float, float]  # (a, b): logit(p') = a * logit(p) + b
IDENTITY: Calibration = (1.0, 0.0)


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def calibrate(p: float, cal: Calibration = IDENTITY) -> float:
    return 1.0 / (1.0 + math.exp(-(cal[0] * _logit(p) + cal[1])))


def spread_for(p: float) -> float:
    """Home spread (negative = home favored) implied by a home win probability."""
    return -(400.0 / math.log(10)) * _logit(p) / ELO_PER_POINT


def fit_calibration(pairs: list[tuple[float, int]]) -> Calibration:
    """Logistic regression of the result on the raw prediction's logit (Newton's method).
    `pairs` are (raw home win prob, home won 0/1)."""
    if len(pairs) < 100:
        return IDENTITY
    a, b = 1.0, 0.0
    xs = [(_logit(p), y) for p, y in pairs]
    for _ in range(25):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in xs:
            q = 1.0 / (1.0 + math.exp(-(a * x + b)))
            w = q * (1 - q)
            ga, gb = ga + (y - q) * x, gb + (y - q)
            haa, hab, hbb = haa + w * x * x, hab + w * x, hbb + w
        det = haa * hbb - hab * hab
        da, db = (hbb * ga - hab * gb) / det, (haa * gb - hab * ga) / det
        a, b = a + da, b + db
        if abs(da) + abs(db) < 1e-9:
            break
    return (round(a, 4), round(b, 4))


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

    def predict(self, g: Game, cal: Calibration = IDENTITY) -> dict:
        h, a = self.rating(g.home), self.rating(g.away)
        p = calibrate(win_prob(h, a, g.neutral), cal)
        return {
            "home_elo": round(h, 1),
            "away_elo": round(a, 1),
            "home_win_prob": round(p, 4),
            "away_win_prob": round(1 - p, 4),
            "home_spread": round(spread_for(p), 1),  # negative = home favored
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


def replay(games: list[Game]) -> list[tuple[Game, float]]:
    """Every finished game in order, with the raw home win prob from the ratings before it."""
    model, out = EloModel(), []
    for g in sorted(games, key=lambda x: (x.date, x.game_id)):
        if g.is_final:
            out.append((g, model.update(g)))
    return out


def calibration_for(rows: list[tuple[Game, float]], season: str) -> Calibration:
    """Fitted on complete seasons before `season`. The first season is left out:
    everyone starts at 1500, so its predictions say little."""
    first = rows[0][0].season if rows else None
    return fit_calibration([(p, int(g.home_pts > g.away_pts)) for g, p in rows
                            if first < g.season < season])


def walk_forward(rows: list[tuple[Game, float]]) -> list[float]:
    """Calibrated home win prob for each row, each season using only earlier seasons."""
    cals = {s: calibration_for(rows, s) for s in {g.season for g, _ in rows}}
    return [calibrate(p, cals[g.season]) for g, p in rows]


def past_picks(games: list[Game], seasons: set[str]) -> list[dict]:
    """The model's pick for every finished game in `seasons`, made from the ratings it had
    going into that game (only earlier results) and the calibration of earlier seasons,
    with how it turned out."""
    rows = replay(games)
    out = []
    for (g, _), p in zip(rows, walk_forward(rows)):
        if g.season not in seasons:
            continue
        home_pick = p >= 0.5
        winner = g.home if g.home_pts > g.away_pts else g.away
        out.append({
            "game_id": g.game_id, "date": g.date, "season": g.season, "home": g.home, "away": g.away,
            "home_pts": g.home_pts, "away_pts": g.away_pts, "home_spread": round(spread_for(p), 1),
            "pick": g.home if home_pick else g.away,
            "p": round(p if home_pick else 1 - p, 4),
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
    """Score every pre-game prediction, calibrated walk-forward (each season's
    calibration from earlier seasons only), plus the raw Elo numbers.

    The first season is skipped by default because everyone starts at 1500,
    so early predictions are meaningless.
    """
    rows = replay(games)
    if not rows:
        return {"games": 0}
    first = rows[0][0].season
    keep = [(g, raw, p) for (g, raw), p in zip(rows, walk_forward(rows))
            if not (skip_first_season and g.season == first)]
    if not keep:
        return {"games": 0}

    def score(probs):
        n = len(keep)
        won = [g.home_pts > g.away_pts for g, _, _ in keep]
        return {
            "accuracy": round(sum((p >= 0.5) == w for p, w in zip(probs, won)) / n, 4),
            "brier": round(sum((p - w) ** 2 for p, w in zip(probs, won)) / n, 4),
            "log_loss": round(-sum(math.log(min(max(p if w else 1 - p, 1e-9), 1.0))
                                   for p, w in zip(probs, won)) / n, 4),
        }
    cal, raw = score([p for _, _, p in keep]), score([r for _, r, _ in keep])
    return {"games": len(keep), **cal, **{f"raw_{k}": v for k, v in raw.items()}}
