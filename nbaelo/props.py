"""Player prop projections: a next-game stat distribution for each player.

For every (player, game) we build features from games *before* it: recent
form (exponentially weighted), season and last-10 averages, opponent
defense, pace, rest, Elo spread, and who is missing tonight on both teams.
A gradient-boosted
model per stat predicts the mean. A negative binomial around that mean,
with dispersion fitted on out-of-sample games, turns it into P(over line).
Minutes use a normal distribution instead.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

COMBOS = {
    "pra": ["pts", "reb", "ast"],
    "pr": ["pts", "reb"],
    "pa": ["pts", "ast"],
    "ra": ["reb", "ast"],
    "stocks": ["stl", "blk"],
}
TARGETS = ["pts", "reb", "ast", "pra", "pr", "pa", "ra", "fg3m", "stl", "blk", "stocks",
           "tov", "fgm", "fga", "ftm", "fta", "oreb", "dreb", "min"]
COUNTS = [t for t in TARGETS if t != "min"]
LABELS = {
    "pts": "Points", "reb": "Rebounds", "ast": "Assists", "pra": "Pts+Reb+Ast",
    "pr": "Pts+Reb", "pa": "Pts+Ast", "ra": "Reb+Ast", "fg3m": "3-Pointers Made",
    "stl": "Steals", "blk": "Blocks", "stocks": "Steals+Blocks", "tov": "Turnovers",
    "fgm": "Field Goals Made", "fga": "Field Goal Attempts", "ftm": "Free Throws Made",
    "fta": "Free Throw Attempts", "oreb": "Offensive Rebounds", "dreb": "Defensive Rebounds",
    "min": "Minutes",
}

MIN_GAMES = 5         # need this many prior games before we train on / project a player
ROTATION_MIN = 10.0   # avg minutes over the team's last 10 games to count as rotation
OUT_GAP = 3           # missed the team's last N games -> flagged "likely out"
GENERIC = ["min_e5", "min_e20", "min_l3", "min_sea", "gp", "gp_sea", "rest", "b2b", "home",
           "gap", "miss_pts", "miss_n", "spread", "pace", "opp_pace",
           "out_pts", "out_min", "out_n", "opp_out_pts", "opp_out_min", "opp_out_n",
           "pts_e20", "reb_e20", "ast_e20", "fga_e20"]


# ---------------------------------------------------------------- frame

def to_frame(rows: list[dict]) -> pd.DataFrame:
    """Box-score rows (plus optional future rows with no stats) -> sorted frame."""
    df = pd.DataFrame(rows)
    df["future"] = df["future"].fillna(False).astype(bool) if "future" in df else False
    for k, parts in COMBOS.items():
        df[k] = df[parts].sum(axis=1, min_count=len(parts))
    df["date"] = pd.to_datetime(df["date"])
    df["home"] = df["home"].astype(int)
    # Future rows only: expected not to play (injury report, or a long absence).
    df["out"] = df["out"].fillna(False).astype(bool) if "out" in df else False
    df = df.sort_values(["date", "game_id", "team", "player_id"]).reset_index(drop=True)
    return df


def candidates(df: pd.DataFrame, next_games: list[dict]) -> list[dict]:
    """Future rows for each team's next game: its recent rotation players.

    `next_games` items: game_id, date, season, team, opp, home.
    """
    real = df[~df["future"]]
    last_row = real.groupby("player_id").tail(1).set_index("player_id")
    out = []
    for g in next_games:
        t = real[real["team"] == g["team"]]
        recent = t["game_id"].drop_duplicates().tail(10).tolist()
        if not recent:
            continue
        r = t[t["game_id"].isin(recent)]
        for pid, grp in r.groupby("player_id"):
            if last_row.at[pid, "team"] != g["team"] or grp["min"].mean() < ROTATION_MIN:
                continue
            last_game = grp["game_id"].iloc[-1]
            gap = len(recent) - 1 - recent.index(last_game)
            out.append({**g, "player_id": pid, "player": grp["player"].iloc[-1],
                        "future": True, "likely_out": gap >= OUT_GAP, "out": gap >= OUT_GAP})
    return out


# ---------------------------------------------------------------- features

def _shifted(g, col: str, fn) -> pd.Series:
    return g[col].transform(lambda x: fn(x).shift())


def _context(df: pd.DataFrame, pts_post: np.ndarray, min_post: np.ndarray) -> dict:
    """Sequential pass over team-games: how long each player has been out, how
    much scoring the team was missing in its previous game, and who it is
    missing in this one.

    "Missing in this one" means regulars (20+ minutes a game lately, still on
    the team, played in its last 10 games) who aren't playing: absent from the
    box score for past games, flagged `out` for upcoming ones. The `out_*`
    values are per team-game, so the opponent's can be looked up too."""
    pid = df["player_id"].to_numpy()
    fut = df["future"].to_numpy()
    out_flag = df["out"].to_numpy()
    n = len(df)
    gap = np.full(n, np.nan)
    miss_pts = np.zeros(n)
    miss_n = np.zeros(n)
    now = {k: np.zeros(n) for k in ("out_pts", "out_min", "out_n")}
    team_rows = []

    count = defaultdict(int)
    hist: dict[str, list[set]] = defaultdict(list)
    last_team, last_idx, last_pts, last_min = {}, {}, {}, {}
    order = df.groupby(["game_id", "team"], sort=False).indices
    keys = sorted(order, key=lambda k: (order[k].min(), k))  # frame is date-sorted
    for gid, team in keys:
        idx = order[(gid, team)]
        k, h = count[team], hist[team]
        if h:
            rotation = set().union(*h[-11:-1]) if len(h) > 1 else set()
            absent = [p for p in rotation - h[-1]
                      if last_team.get(p) == team and last_min.get(p, 0) >= 20]
            miss_pts[idx] = sum(last_pts[p] for p in absent)
            miss_n[idx] = len(absent)
            playing = {pid[i] for i in idx if not (fut[i] and out_flag[i])}
            gone = [p for p in set().union(*h[-10:]) - playing
                    if last_team.get(p) == team and last_min.get(p, 0) >= 20]
            vals = (sum(last_pts[p] for p in gone), sum(last_min[p] for p in gone), len(gone))
            for key, v in zip(now, vals):
                now[key][idx] = v
            team_rows.append((gid, team, *vals))
        for i in idx:
            p = pid[i]
            if last_team.get(p) == team:
                gap[i] = k - last_idx[p] - 1
        real = [i for i in idx if not fut[i]]
        if real:
            for i in real:
                p = pid[i]
                last_team[p], last_idx[p] = team, k
                last_pts[p], last_min[p] = pts_post[i], min_post[i]
            h.append({pid[i] for i in real})
            count[team] += 1
    teams = pd.DataFrame(team_rows, columns=["game_id", "opp", "opp_out_pts", "opp_out_min", "opp_out_n"])
    return {"gap": gap, "miss_pts": miss_pts, "miss_n": miss_n, **now}, teams


def _team_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per team-game: rolling pace and how much of each stat the team allows,
    relative to the league. Uses only earlier games."""
    df = df.assign(_poss=df["fga"] - df["oreb"] + df["tov"] + 0.44 * df["fta"])
    sums = df.groupby(["game_id", "team"], sort=False).agg(
        date=("date", "first"), opp=("opp", "first"), future=("future", "first"),
        **{c: (c, lambda x: x.sum(min_count=1)) for c in COUNTS + ["_poss"]},
    ).reset_index()
    sums.loc[sums["future"], COUNTS + ["_poss"]] = np.nan
    # What the opponent scored against this team = what this team allowed.
    allowed = sums[["game_id", "team"] + COUNTS].rename(columns={"team": "opp"})
    tg = sums[["game_id", "team", "opp", "date", "_poss"]].merge(
        allowed, on=["game_id", "opp"], how="left")
    tg = tg.sort_values(["date", "game_id", "team"]).reset_index(drop=True)
    g = tg.groupby("team", sort=False)
    out = {"pace": _shifted(g, "_poss", lambda x: x.rolling(15, min_periods=3).mean())}
    for t in COUNTS:
        team_avg = _shifted(g, t, lambda x: x.rolling(15, min_periods=3).mean())
        # League average per day, shifted a whole day so same-day games can't leak.
        daily = tg.groupby("date")[t].mean().ewm(halflife=40, ignore_na=True).mean().shift()
        out[f"def_{t}"] = team_avg / tg["date"].map(daily)
    return pd.concat([tg[["game_id", "team"]], pd.DataFrame(out)], axis=1)


def build_features(df: pd.DataFrame, spreads: dict[str, float]) -> pd.DataFrame:
    """Add every model feature to the frame. Safe for future rows."""
    g = df.groupby("player_id", sort=False)
    gs = df.groupby(["player_id", "season"], sort=False)
    f = {}
    for t in TARGETS:
        f[f"{t}_e5"] = _shifted(g, t, lambda x: x.ewm(halflife=5, ignore_na=True).mean())
        f[f"{t}_e20"] = _shifted(g, t, lambda x: x.ewm(halflife=20, ignore_na=True).mean())
        f[f"{t}_l10"] = _shifted(g, t, lambda x: x.rolling(10, min_periods=1).mean())
        f[f"{t}_sea"] = _shifted(gs, t, lambda x: x.expanding().mean())
    for t in COUNTS:  # per-minute rate over a long window x recent minutes
        f[f"{t}_proj"] = f[f"{t}_e20"] / f["min_e20"].clip(lower=1) * f["min_e5"]
    f["min_l3"] = _shifted(g, "min", lambda x: x.rolling(3, min_periods=1).mean())
    f["gp"] = g.cumcount()
    f["gp_sea"] = gs.cumcount()
    f["rest"] = g["date"].diff().dt.days.clip(upper=10).fillna(10)
    f["b2b"] = (f["rest"] == 1).astype(int)
    post = {c: g[c].transform(lambda x: x.ewm(halflife=20, ignore_na=True).mean()).to_numpy()
            for c in ("pts", "min")}
    ctx, out_by_team = _context(df, post["pts"], post["min"])
    f.update(ctx)
    home_spread = df["game_id"].map(spreads)
    f["spread"] = np.where(df["home"] == 1, home_spread, -home_spread)
    df = pd.concat([df, pd.DataFrame(f, index=df.index)], axis=1)

    tf = _team_features(df)
    df = df.merge(tf[["game_id", "team", "pace"]], on=["game_id", "team"], how="left")
    opp = tf.rename(columns={"team": "opp", "pace": "opp_pace",
                             **{f"def_{t}": f"opp_{t}" for t in COUNTS}})
    df = df.merge(opp, on=["game_id", "opp"], how="left")
    return df.merge(out_by_team, on=["game_id", "opp"], how="left")


def feature_cols(t: str) -> list[str]:
    own = [f"{t}_e5", f"{t}_e20", f"{t}_l10", f"{t}_sea"]
    if t != "min":
        own += [f"{t}_proj", f"opp_{t}"]
    return list(dict.fromkeys(GENERIC + own))


# ---------------------------------------------------------------- model

def _regressor(t: str):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(
        loss="squared_error" if t == "min" else "poisson",
        max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
        min_samples_leaf=200, l2_regularization=1.0, random_state=0,
    )


def trainable(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["future"] & (df["gp"] >= MIN_GAMES)]


def fit(train: pd.DataFrame, targets: list[str] = TARGETS) -> dict:
    models = {}
    for t in targets:
        m = _regressor(t)
        m.fit(train[feature_cols(t)], train[t])
        models[t] = m
    return models


def predict(models: dict, df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {t: np.clip(m.predict(df[feature_cols(t)]), 0, None) for t, m in models.items()},
        index=df.index,
    )


def fit_dispersion(t: str, mu: np.ndarray, y: np.ndarray, bins: int = 12) -> dict:
    """Spread of outcomes around the prediction, by prediction size.

    Counts: negative binomial alpha (variance = mu + alpha * mu^2).
    Minutes: normal standard deviation.
    """
    edges = np.unique(np.quantile(mu, np.linspace(0, 1, bins + 1)))
    which = np.clip(np.searchsorted(edges, mu, side="right") - 1, 0, len(edges) - 2)
    grid, param = [], []
    for b in range(len(edges) - 1):
        sel = which == b
        if sel.sum() < 50:
            continue
        m, resid = mu[sel].mean(), y[sel] - mu[sel]
        var = float(np.mean(resid ** 2))
        grid.append(round(float(m), 3))
        if t == "min":
            param.append(round(math.sqrt(var), 4))
        else:
            param.append(round(max((var - m) / max(m, 1e-6) ** 2, 1e-3), 5))
    return {"mu": grid, "param": param}


def dist_param(disp: dict, mu: np.ndarray) -> np.ndarray:
    return np.interp(mu, disp["mu"], disp["param"])


def p_over(t: str, mu, param, line):
    """P(stat > line). For a whole-number line a push (== line) is neither."""
    from scipy import stats
    mu, param, line = np.asarray(mu, float), np.asarray(param, float), np.asarray(line, float)
    if t == "min":
        return stats.norm.sf(line, loc=mu, scale=param)
    n = 1.0 / param
    p = n / (n + np.maximum(mu, 1e-6))
    return stats.nbinom.sf(np.floor(line), n, p)


# ---------------------------------------------------------------- evaluation

def _metrics(t: str, test: pd.DataFrame, mu: np.ndarray, disp: dict) -> dict:
    y = test[t].to_numpy(float)
    base = {
        "season_avg": test[f"{t}_sea"].fillna(test[f"{t}_e20"]).to_numpy(float),
        "last10": test[f"{t}_l10"].to_numpy(float),
        "ewm5": test[f"{t}_e5"].to_numpy(float),
    }
    out = {"n": int(len(y)), "mae": round(float(np.mean(np.abs(y - mu))), 3),
           "rmse": round(float(np.sqrt(np.mean((y - mu) ** 2))), 3)}
    for k, b in base.items():
        out[f"mae_{k}"] = round(float(np.mean(np.abs(y - b))), 3)
    # Over/under at a stand-in book line: last-10 average, rounded to a half.
    line = np.floor(base["last10"]) + 0.5
    p = p_over(t, mu, dist_param(disp, mu), line)
    hit = (y > line).astype(float)
    out["brier"] = round(float(np.mean((p - hit) ** 2)), 4)
    out["brier_coin"] = round(float(np.mean((hit.mean() - hit) ** 2)), 4)
    out["calibration"] = [
        {"p": round(float(p[s].mean()), 3), "hit": round(float(hit[s].mean()), 3), "n": int(s.sum())}
        for lo in np.arange(0, 1, 0.1)
        if (s := (p >= lo) & (p < lo + 0.1)).sum() >= 100
    ]
    return out


def backtest(df: pd.DataFrame, test_seasons: list[str], targets: list[str] = TARGETS,
             log=print) -> dict:
    """Walk forward: for each season S, train on seasons before S and score S.

    Each season's dispersion comes from the *previous* season's out-of-sample
    errors, so P(over) is never tuned on the games it's scored on. That means
    one extra warm-up season before the first one reported.
    """
    rows = trainable(df).dropna(subset=["min_e20"])
    seasons = sorted(rows["season"].unique())
    first = seasons.index(test_seasons[0])
    warm = seasons[first - 1]
    results: dict[str, list] = defaultdict(list)
    prev = {}
    for s in [warm] + test_seasons:
        train, test = rows[rows["season"] < s], rows[rows["season"] == s]
        log(f"  backtest {s}: train {len(train)}, test {len(test)}")
        models = fit(train, targets)
        mu = predict(models, test)
        for t in targets:
            m = mu[t].to_numpy()
            if t in prev:
                results[t].append(_metrics(t, test, m, prev[t]))
            prev[t] = fit_dispersion(t, m, test[t].to_numpy(float))
    return {t: _pool(v) for t, v in results.items()}


def _pool(folds: list[dict]) -> dict:
    """Combine per-season metrics, weighted by games."""
    n = sum(f["n"] for f in folds)
    out = {"n": n}
    for k in folds[0]:
        if k in ("n", "calibration"):
            continue
        if k == "rmse":
            out[k] = round(math.sqrt(sum(f[k] ** 2 * f["n"] for f in folds) / n), 3)
        else:
            out[k] = round(sum(f[k] * f["n"] for f in folds) / n, 4)
    cal = defaultdict(lambda: [0.0, 0.0, 0])
    for f in folds:
        for c in f["calibration"]:
            b = cal[int(c["p"] * 10)]
            b[0] += c["p"] * c["n"]
            b[1] += c["hit"] * c["n"]
            b[2] += c["n"]
    out["calibration"] = [{"p": round(a / k, 3), "hit": round(h / k, 3), "n": k}
                          for _, (a, h, k) in sorted(cal.items())]
    return out


def train_and_project(df: pd.DataFrame, log=print) -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame]:
    """Fit on all finished games and project the future rows.

    Dispersion comes from a model trained on seasons before the last complete
    one and scored on everything since (out of sample). Returns
    (projections, dispersion, last complete season's rows, their out-of-sample means).
    """
    rows = trainable(df).dropna(subset=["min_e20"])
    future = df[df["future"]]
    current = future["season"].max() if len(future) else rows["season"].max()
    seasons = sorted(s for s in rows["season"].unique() if s < current)
    holdout_from = seasons[-1]
    train, hold = rows[rows["season"] < holdout_from], rows[rows["season"] >= holdout_from]
    log(f"dispersion fit: train {len(train)}, holdout {len(hold)}")
    hold_mu = predict(fit(train), hold)
    disp = {t: fit_dispersion(t, hold_mu[t].to_numpy(), hold[t].to_numpy(float)) for t in TARGETS}

    log(f"final fit on {len(rows)} player-games")
    models = fit(rows)
    proj = predict(models, future) if len(future) else pd.DataFrame(columns=TARGETS)
    last = hold["season"] == holdout_from
    return proj, disp, hold[last], hold_mu[last]
