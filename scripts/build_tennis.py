"""Daily tennis build: fetch recent results from ESPN, rate players, predict upcoming matches.

    python -m scripts.build_tennis            # fetch, then build
    python -m scripts.build_tennis --no-fetch # build from the saved results only

Writes site/tennis/{atp,wta}.json and updates data/tennis/{tour}_matches.csv.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo.data import now_iso  # noqa: E402
from tennis import elo, espn, predict  # noqa: E402

DATA = ROOT / "data" / "tennis"
OUT = ROOT / "site" / "tennis"
TEST_YEARS = 4       # walk-forward backtest over the last four years
RECENT_DAYS = 21     # graded predictions shown on the page
TOP = 150            # rated players listed
ACTIVE_DAYS = 365    # listed players must have played within this many days
BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


def summary(graded: list[dict]) -> dict:
    n = len(graded)
    return {"n":n, "correct":sum(g["p"] > 0.5 for g in graded),
            "brier":round(sum((1 - g["p"]) ** 2 for g in graded) / n, 4) if n else None,
            "by_conf":[{"lo":lo, "hi":min(hi, 1.0), "n":len(xs), "won":sum(x["p"] > 0.5 for x in xs),
                        "avg_p":round(sum(x["fav_p"] for x in xs) / len(xs), 4) if xs else None,
                        "hit":round(sum(x["p"] > 0.5 for x in xs) / len(xs), 4) if xs else None}
                       for lo, hi in BUCKETS
                       for xs in [[g for g in graded if lo <= g["fav_p"] < hi]]]}


def build_tour(tour: str, fetch: bool, today: date) -> dict:
    path = DATA / f"{tour}_matches.csv"
    rows = espn.load(path)
    todo: list[dict] = []
    if fetch:
        start, end = (today.replace(day=1) - timedelta(days=1)).replace(day=1), today + timedelta(days=7)
        try:
            done, todo = espn.parse(espn.fetch(tour, start.strftime("%Y%m%d"), end.strftime("%Y%m%d")), tour)
            rows = espn.merge(rows, done)
            espn.save(path, rows)
            print(f"{tour}: {len(done)} recent results, {len(todo)} upcoming")
        except Exception as e:  # noqa: BLE001
            print(f"{tour}: ESPN unavailable ({e}); building from saved results")
    rows = predict.prepare(rows, tour)
    model, out = elo.replay(rows)
    year = today.year
    cal = elo.calibration_for(out, year)
    names = {}
    for r in rows:
        names[r["winner_id"]] = (r["winner"], r["winner_country"])
        names[r["loser_id"]] = (r["loser"], r["loser_country"])

    def who(pid: str, surface: str) -> dict:
        pl = model.players[pid]
        return {"id":pid, "name":names.get(pid, ("", ""))[0], "country":names.get(pid, ("", ""))[1],
                "elo":round(pl.rating(surface, model.w)), "n":pl.n}

    # Upcoming: one entry per match, player 1 as ESPN lists them.
    upcoming = []
    for t in predict.prepare([dict(x) for x in todo], tour):
        q = predict.win_chance(model, t["p1_id"], t["p2_id"], t["surface"], t["best_of"], cal, tour)
        upcoming.append({"match_id":t["match_id"], "date":t["date"], "start":t["start"], "state":t["state"],
                         "event":t["event"], "round":t["round"], "surface":t["surface"], "best_of":t["best_of"],
                         "p1":{**who(t["p1_id"], t["surface"]), "name":t["p1"], "country":t["p1_country"]},
                         "p2":{**who(t["p2_id"], t["surface"]), "name":t["p2"], "country":t["p2_country"]},
                         "p":round(q, 4), **predict.outlook(q, tour, t["surface"], t["best_of"])})
    upcoming.sort(key=lambda u: (u["date"], u["event"], u["start"] or "", u["match_id"]))

    # Graded: completed matches, each with the calibrated chance the model gave the winner beforehand.
    cals = {y: elo.calibration_for(out, y) for y in range(year - TEST_YEARS, year + 1)}
    graded = []
    for m, p in out:
        y = int(m["date"][:4])
        if y not in cals or m["status"] != "final":
            continue
        q = elo.calibrate(p, cals[y])
        graded.append({"date":m["date"], "event":m["event"], "round":m["round"], "surface":m["surface"],
                       "winner":m["winner"], "winner_id":m["winner_id"], "loser":m["loser"], "loser_id":m["loser_id"],
                       "score":" ".join(f"{a}-{b}" for a, b in zip(m["w_games"].split(), m["l_games"].split())),
                       "p":round(q, 4), "fav_p":round(max(q, 1 - q), 4)})
    since = (today - timedelta(days=RECENT_DAYS)).isoformat()
    by_year = defaultdict(list)
    for g in graded:
        by_year[g["date"][:4]].append(g)
    backtest = {y: {k:v for k, v in summary(gs).items() if k != "by_conf"} for y, gs in sorted(by_year.items())}

    cutoff = (today - timedelta(days=ACTIVE_DAYS)).isoformat()
    ratings = sorted(((pid, pl) for pid, pl in model.players.items() if pl.last >= cutoff and pl.n >= 20),
                     key=lambda x: -x[1].overall)[:TOP]
    return {
        "built_at":now_iso(), "tour":tour, "calibration":list(cal),
        "upcoming":upcoming,
        "recent":sorted((g for g in graded if g["date"] >= since), key=lambda g: g["date"], reverse=True),
        "record":summary([g for g in graded if int(g["date"][:4]) > year - TEST_YEARS]),
        "backtest":backtest,
        "ratings":[{"id":pid, "name":names[pid][0], "country":names[pid][1], "elo":round(pl.overall),
                    "hard":round(pl.rating("hard", model.w)), "clay":round(pl.rating("clay", model.w)),
                    "grass":round(pl.rating("grass", model.w)), "n":pl.n, "last":pl.last} for pid, pl in ratings],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()
    today = date.today()
    for tour in espn.TOURS:
        res = build_tour(tour, not args.no_fetch, today)
        write_json(OUT / f"{tour}.json", res)
        r = res["record"]
        print(f"{tour}: {len(res['upcoming'])} upcoming; last {TEST_YEARS} years {r['correct']}/{r['n']} "
              f"({r['correct'] / max(r['n'], 1):.1%}) picked right")


if __name__ == "__main__":
    main()
