"""Real sportsbook lines, the model's chances at them, and how they turned out.

Each fetch is saved to data/book_lines.csv: one row per (date, player, market),
replaced if fetched again the same day (the later fetch is closer to tip-off,
so nearer the closing line). After the games, rows are graded from the box
scores. The summary bets the side the model prefers *only when it disagrees
with the book's no-vig price by at least EDGE*, at the book's median price, so
units are a real measure of value against real lines.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .picks import _stat

FIELDS = ["fetched_at", "date", "game_id", "player_id", "player", "team", "stat", "line", "over", "under",
          "books", "best_over", "best_over_book", "best_under", "best_under_book", "p_over", "p_under",
          "result", "actual"]
EDGES = [0.03, 0.06, 0.10]  # model chance minus the book's no-vig chance


def implied(o: float) -> float:
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def payout(o: float) -> float:
    """Profit per 1 staked."""
    return o / 100 if o > 0 else 100 / -o


def no_vig_over(over: float, under: float) -> float:
    a, b = implied(over), implied(under)
    return a / (a + b)


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("line", "p_over", "p_under"):
            r[k] = float(r[k])
        for k in ("over", "under", "books", "best_over", "best_under"):
            r[k] = int(r[k])
        r["actual"] = float(r["actual"]) if r["actual"] not in ("", None) else ""
    return rows


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["date"], r["game_id"], r["player"], r["stat"])))


def upsert(rows: list[dict], new: list[dict]) -> list[dict]:
    key = lambda r: (r["date"], str(r["player_id"]), r["stat"])  # noqa: E731
    fresh = {key(r) for r in new}
    return [r for r in rows if key(r) not in fresh] + new


def grade(rows: list[dict], logs: list[dict]) -> None:
    """Fill result (over / under / push / void) and actual, in place."""
    box = {(r["game_id"], str(r["player_id"])): r for r in logs}
    final = {r["game_id"] for r in logs}
    for r in rows:
        if r["result"]:
            continue
        b = box.get((r["game_id"], str(r["player_id"])))
        if b is None:
            if r["game_id"] in final:
                r["result"] = "void"
            continue
        a = _stat(b, r["stat"])
        r["actual"] = a
        r["result"] = "push" if a == r["line"] else "over" if a > r["line"] else "under"


def bets(rows: list[dict], edge: float) -> list[dict]:
    """The side the model prefers on each graded line where its chance beats the book's
    no-vig chance by `edge` or more, with the profit at the book's median price."""
    out = []
    for r in rows:
        if r["result"] not in ("over", "under", "push"):
            continue
        fair = no_vig_over(r["over"], r["under"])
        # A push refunds the stake, so compare chances among decided outcomes, as the book's price does.
        decided = r["p_over"] + r["p_under"]
        for side, p, f, price in (("over", r["p_over"] / decided, fair, r["over"]),
                                  ("under", r["p_under"] / decided, 1 - fair, r["under"])):
            if p - f >= edge:
                won = r["result"] == side
                units = 0.0 if r["result"] == "push" else payout(price) if won else -1.0
                out.append({**r, "side": side, "edge": round(p - f, 4), "units": units,
                            "won": won, "push": r["result"] == "push"})
    return out


def summarize(rows: list[dict]) -> dict:
    graded = [r for r in rows if r["result"] in ("over", "under", "push")]

    def block(bs):
        decided = [b for b in bs if not b["push"]]
        n, won = len(decided), sum(b["won"] for b in decided)
        units = sum(b["units"] for b in bs)
        return {"n": n, "won": won, "hit": round(won / n, 4) if n else None,
                "units": round(units, 2), "roi": round(units / n, 4) if n else None}

    # How often the line went over, and how the model's chance compared (calibration vs real lines).
    over_rate = sum(r["result"] == "over" for r in graded) / len(graded) if graded else None
    return {
        "lines": len(rows), "graded": len(graded),
        "over_rate": round(over_rate, 4) if over_rate is not None else None,
        "avg_p_over": round(sum(r["p_over"] for r in graded) / len(graded), 4) if graded else None,
        "by_edge": [{"edge": e, **block(bets(rows, e))} for e in EDGES],
        "since": min((r["date"] for r in rows), default=None),
    }
