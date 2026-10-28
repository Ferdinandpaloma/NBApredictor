"""The model's daily picks: chosen each morning, locked, then graded from box scores.

Rules (kept simple and fixed, so the record means something):
- Only the day's slate (the earliest upcoming game date) gets picks.
- Line: we don't have sportsbook lines, so we set the one a book anchored on
  recent form would: the half point where the player's recent form alone
  makes over and under closest to 50/50. "Recent form" is the strongest
  simple baseline from the backtest (an average weighted toward the last ~5
  games); the plain last-10 average is too easy to beat, especially early in
  a season, and would flatter the model. (Simply rounding up would also hand
  the under a free edge on small, lumpy stats like rebounds or 3s.)
- This measures accuracy against that line, not profit against a sportsbook,
  whose lines are sharper. Units at -110 are kept in the data for reference.
- The market must be one a book would actually post: recent form has to put
  that line near a coin flip (FORM_BAND). That rules out things like "under
  0.5 threes" for a center who never shoots them.
- A pick needs the model to give one side at least MIN_P, a projected
  MIN_MINUTES+, and no "likely out" flag. One pick per player (their
  strongest market), at most PER_DAY a day, strongest first.
- Once a game has picks they never change, so nothing can be cherry-picked.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

from .props import COMBOS, dist_param, p_over

MARKETS = ["pts", "reb", "ast", "pra", "pr", "pa", "ra", "fg3m"]
MIN_P = 0.58
FORM_BAND = (0.38, 0.62)  # recent form's P(over) at the line must fall in here
PER_DAY = 10
MIN_MINUTES = 20.0
ODDS = -110
WIN = 100 / 110  # units won per unit staked at -110
BUCKETS = [(0.58, 0.62), (0.62, 0.66), (0.66, 1.01)]

FIELDS = ["made_at", "date", "game_id", "player_id", "player", "team", "opp", "home",
          "stat", "line", "side", "p", "form_p", "proj", "form", "result", "actual"]


def form_line(stat: str, l10, param):
    """Half-point line where recent form alone is closest to a coin flip.

    Works on scalars or numpy arrays of the same shape."""
    l10 = np.atleast_1d(np.asarray(l10, float))
    param = np.broadcast_to(np.asarray(param, float), l10.shape)
    base = np.floor(l10) + 0.5
    cands = np.maximum(np.stack([base - 1, base, base + 1]), 0.5)          # (3, n)
    gap = np.abs(np.stack([p_over(stat, l10, param, c) for c in cands]) - 0.5)
    best = np.take_along_axis(cands, gap.argmin(axis=0)[None], axis=0)[0]
    return best if best.size > 1 else best[0]


def best_market(player: dict) -> dict | None:
    """The player's strongest over/under among MARKETS, or None if none qualifies."""
    if player.get("likely_out") or (player["proj"]["min"][0] or 0) < MIN_MINUTES:
        return None
    best = None
    for t in MARKETS:
        mu, param = player["proj"][t]
        l10 = player.get("e5", player["l10"]).get(t)  # recent-form baseline
        if mu is None or param is None or l10 is None:
            continue
        line = float(form_line(t, l10, param))
        pf = float(p_over(t, l10, param, line))  # what recent form alone says
        if not FORM_BAND[0] <= pf <= FORM_BAND[1]:
            continue
        po = float(p_over(t, mu, param, line))  # half-point line: no push, under = 1 - over
        side, p = ("over", po) if po >= 0.5 else ("under", 1 - po)
        if p >= MIN_P and (best is None or p > best["p"]):
            best = {"stat": t, "line": line, "side": side, "p": round(p, 4),
                    "form_p": round(pf if side == "over" else 1 - pf, 4), "proj": mu, "form": l10}
    return best


def make_picks(players: list[dict], existing: list[dict], made_at: str) -> list[dict]:
    """New picks for the earliest upcoming date. Games that already have picks are locked."""
    if not players:
        return []
    day = min(p["date"] for p in players)
    locked = {x["game_id"] for x in existing}
    room = PER_DAY - sum(1 for x in existing if x["date"] == day)
    cands = []
    for pl in players:
        if pl["date"] != day or pl["game_id"] in locked:
            continue
        m = best_market(pl)
        if m:
            cands.append({"made_at": made_at, "date": day, "game_id": pl["game_id"],
                          "player_id": pl["id"], "player": pl["name"], "team": pl["team"],
                          "opp": pl["opp"], "home": pl["home"], **m, "result": "", "actual": ""})
    cands.sort(key=lambda c: -c["p"])
    return cands[:max(room, 0)]


def _stat(row: dict, stat: str) -> float:
    return sum(row[s] for s in COMBOS[stat]) if stat in COMBOS else row[stat]


def grade(picks: list[dict], logs: list[dict]) -> None:
    """Fill in result/actual for picks whose game is in the box scores (in place).

    A player with no box score row in a game that's in the data didn't play: void.
    """
    rows = {(r["game_id"], r["player_id"]): r for r in logs}
    final = {r["game_id"] for r in logs}
    for x in picks:
        if x["result"]:
            continue
        row = rows.get((x["game_id"], x["player_id"]))
        if row is None:
            if x["game_id"] in final:
                x["result"] = "void"
            continue
        actual = _stat(row, x["stat"])
        x["actual"] = actual
        if actual == x["line"]:
            x["result"] = "push"
        else:
            x["result"] = "won" if (actual > x["line"]) == (x["side"] == "over") else "lost"


def summarize(picks: list[dict]) -> dict:
    """Record, hit rate, units at -110, and accuracy by confidence, market and day."""
    decided = [x for x in picks if x["result"] in ("won", "lost")]

    def block(xs):
        won = sum(x["result"] == "won" for x in xs)
        n = len(xs)
        units = won * WIN - (n - won)
        return {"n": n, "won": won, "lost": n - won,
                "hit": round(won / n, 4) if n else None,
                "avg_p": round(sum(float(x["p"]) for x in xs) / n, 4) if n else None,
                "units": round(units, 2), "roi": round(units / n, 4) if n else None}

    by_day = defaultdict(list)
    for x in decided:
        by_day[x["date"]].append(x)
    daily, cum = [], 0.0
    for d in sorted(by_day):
        b = block(by_day[d])
        cum += b["units"]
        daily.append({"date": d, "won": b["won"], "lost": b["lost"], "units": b["units"], "cum": round(cum, 2)})

    return {
        **block(decided),
        "push": sum(x["result"] == "push" for x in picks),
        "void": sum(x["result"] == "void" for x in picks),
        "pending": sum(not x["result"] for x in picks),
        "break_even": round(1 / (1 + WIN), 4),
        "by_conf": [{"lo": lo, "hi": min(hi, 1.0), **block([x for x in decided if lo <= float(x["p"]) < hi])}
                    for lo, hi in BUCKETS],
        "by_market": {t: block(xs) for t in MARKETS if (xs := [x for x in decided if x["stat"] == t])},
        "daily": daily,
    }


def simulate(hold, mu, disp: dict) -> dict:
    """Apply the same rules to out-of-sample predictions for past games.

    `hold` is the feature frame for games the model wasn't trained on and `mu`
    its predicted means. Only players who actually played are in it, so there
    are no voids, and the dispersion was fitted on these same games: treat it
    as a guide, not a live record.
    """
    best_p = np.zeros(len(hold))
    best = [None] * len(hold)
    ok = (mu["min"].to_numpy() >= MIN_MINUTES)
    for t in MARKETS:
        l10 = hold[f"{t}_e5"].to_numpy(float)
        m = mu[t].to_numpy(float)
        valid = ~np.isnan(l10) & ok
        safe = np.where(valid, l10, 1.0)
        line = form_line(t, safe, dist_param(disp[t], safe))
        pf = p_over(t, safe, dist_param(disp[t], safe), line)
        valid &= (pf >= FORM_BAND[0]) & (pf <= FORM_BAND[1])
        po = np.where(valid, p_over(t, m, dist_param(disp[t], m), np.nan_to_num(line)), 0.5)
        p = np.maximum(po, 1 - po)
        actual = hold[t].to_numpy(float)
        for i in np.nonzero(valid & (p >= MIN_P) & (p > best_p))[0]:
            best_p[i] = p[i]
            side = "over" if po[i] >= 0.5 else "under"
            best[i] = {"stat": t, "line": float(line[i]), "side": side, "p": float(p[i]),
                       "result": "won" if (actual[i] > line[i]) == (side == "over") else "lost"}
    dates = hold["date"].dt.strftime("%Y-%m-%d").to_numpy()
    per_day = defaultdict(list)
    for i, b in enumerate(best):
        if b:
            per_day[dates[i]].append({**b, "date": dates[i]})
    picks = [x for d in per_day for x in sorted(per_day[d], key=lambda x: -x["p"])[:PER_DAY]]
    return {"seasons": sorted(hold["season"].unique().tolist()), **summarize(picks)}


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        out = list(csv.DictReader(f))
    for x in out:
        x["line"], x["p"] = float(x["line"]), float(x["p"])
        x["form_p"] = float(x["form_p"]) if x.get("form_p") else ""
        x["home"] = int(x["home"])
        x["actual"] = float(x["actual"]) if x["actual"] not in ("", None) else ""
    return out


def save(path: Path, picks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(picks, key=lambda x: (x["date"], x["game_id"], -float(x["p"]))))
