"""Who guards whom: matchup features from NBA tracking data (data/matchups.csv).

For each (player, game), using only earlier games:
- Defender ratings: per possession, how much players score / assist / hit
  threes against a defender relative to what they normally do against
  everyone. Shrunk toward average (a defender needs a few hundred possessions
  to mean much) and faded over time (half-life HALF_LIFE days).
- Expected assignments: how the player's past possessions split among the
  opponent's defenders who are playing in this game, wherever those
  defenders were playing when they guarded him.
- mdef_<stat>: the assignment-weighted defender rating (1.0 = average,
  0.9 = he does 10% worse than usual against these defenders).
- h2h_pts: the player's own scoring against those same defenders relative to
  his usual rate, shrunk hard (most "he owns this guy" stories are noise).
Players with too little history against the opponent's current defenders
get NaN, which the gradient-boosted model handles as its own case.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

STATS = ["pts", "ast", "fg3m"]
HALF_LIFE = 365.0                                # days
SHRINK = {"pts": 60.0, "ast": 12.0, "fg3m": 8.0}  # pseudo-counts, in expected stat units
H2H_SHRINK = 25.0                                # expected points
MIN_POSS = 8.0                                   # assignment history needed to estimate


def load(path) -> pd.DataFrame:
    m = pd.read_csv(path, dtype={"game_id": str, "off_id": str, "def_id": str})
    return m[m["off_id"].notna() & (m["poss"] > 0)]


class _Decayed:
    """Sums that fade with time: value * 0.5 ** (days / HALF_LIFE)."""
    __slots__ = ("v", "day")

    def __init__(self, n: int):
        self.v, self.day = [0.0] * n, None

    def at(self, day: int) -> list[float]:
        if self.day is not None and day != self.day:
            f = 0.5 ** ((day - self.day) / HALF_LIFE)
            self.v = [x * f for x in self.v]
        self.day = day
        return self.v


def features(df: pd.DataFrame, mu: pd.DataFrame) -> pd.DataFrame:
    """Matchup features for every row of the player frame `df` (index-aligned).

    `df` needs game_id, date, team, opp, player_id, future and out; `mu` is
    `load()`'s matchup rows. Who "plays" in a game is everyone in its box
    score, or for upcoming games every projected player not flagged out.
    """
    day = (df["date"] - pd.Timestamp("2000-01-01")).dt.days.to_numpy()
    plays = ~(df["future"] & df["out"]).to_numpy()
    pid, team, opp = df["player_id"].astype(str).to_numpy(), df["team"].to_numpy(), df["opp"].to_numpy()
    by_game = df.groupby("game_id", sort=False).indices
    m_by_game = {g: grp for g, grp in mu.groupby("game_id", sort=False)}
    order = sorted(by_game, key=lambda g: (day[by_game[g][0]], g))

    k = len(STATS)
    off = defaultdict(lambda: _Decayed(k + 1))       # player: [poss, pts, ast, fg3m]
    dfn = defaultdict(lambda: _Decayed(2 * k))       # defender: [actual..., expected...]
    pair = defaultdict(lambda: _Decayed(3))          # (off, def): [poss, actual pts, expected pts]
    guarded_by = defaultdict(set)                    # off -> defenders who have guarded him

    out = {f"mdef_{s}": np.full(len(df), np.nan) for s in STATS}
    out["h2h_pts"] = np.full(len(df), np.nan)
    out["mdef_poss"] = np.zeros(len(df))

    def rating(d: str, today: int) -> list[float]:
        v = dfn[d].at(today)
        return [(v[i] + SHRINK[s]) / (v[k + i] + SHRINK[s]) for i, s in enumerate(STATS)]

    for g in order:
        idx = by_game[g]
        today = int(day[idx[0]])
        playing = defaultdict(set)
        for i in idx:
            if plays[i]:
                playing[team[i]].add(pid[i])
        # Features first, from earlier games only.
        for i in idx:
            p, defenders = pid[i], playing.get(opp[i], set())
            cand = guarded_by[p] & defenders
            if not cand:
                continue
            w = {d: pair[(p, d)].at(today)[0] for d in cand}
            tot = sum(w.values())
            out["mdef_poss"][i] = tot
            if tot < MIN_POSS:
                continue
            r = np.zeros(k)
            act = exp = 0.0
            for d, wd in w.items():
                r += wd * np.array(rating(d, today))
                v = pair[(p, d)].at(today)
                act, exp = act + v[1], exp + v[2]
            for j, s in enumerate(STATS):
                out[f"mdef_{s}"][i] = r[j] / tot
            out["h2h_pts"][i] = (act + H2H_SHRINK) / (exp + H2H_SHRINK)
        # Then learn from this game's matchups.
        rows = m_by_game.get(g)
        if rows is None:
            continue
        for o, d, poss, *vals in rows[["off_id", "def_id", "poss"] + STATS].itertuples(index=False):
            ov = off[o].at(today)
            rate = [(ov[1 + j] + 0.1) / (ov[0] + 1.0) for j in range(k)] if ov[0] else None
            if rate is not None and ov[0] >= 50:  # need a baseline for the shooter first
                dv = dfn[d].at(today)
                for j in range(k):
                    dv[j] += vals[j]
                    dv[k + j] += rate[j] * poss
                pv = pair[(o, d)].at(today)
                pv[1] += vals[0]
                pv[2] += rate[0] * poss
            pair[(o, d)].at(today)[0] += poss
            guarded_by[o].add(d)
        for o, grp in rows.groupby("off_id", sort=False):
            ov = off[o].at(today)
            ov[0] += grp["poss"].sum()
            for j, s in enumerate(STATS):
                ov[1 + j] += grp[s].sum()
    return pd.DataFrame(out, index=df.index)
