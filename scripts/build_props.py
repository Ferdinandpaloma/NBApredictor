"""Build player prop projections and player stat pages.

    python -m scripts.build_props                    # fetch schedule + new box scores
    python -m scripts.build_props --schedule FILE    # use a saved schedule JSON
    python -m scripts.build_props --no-fetch         # don't download box scores
    python -m scripts.build_props --backtest         # also run the walk-forward backtest (slow)

Writes:
    data/player_logs.csv        every player box score (updated in place)
    site/props.json             next-game projections for each team's rotation
    site/props_backtest.json    backtest metrics (only with --backtest)
    site/players/index.json     player search index
    site/players/<id>.json      full game log + season averages per player
    data/book_lines.csv         sportsbook lines (with --odds and an API key), graded later
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo import booklines, injuries, odds  # noqa: E402
from nbaelo import picks as model_picks  # noqa: E402
from nbaelo import wire  # noqa: E402
from nbaelo import props  # noqa: E402
from nbaelo.data import fetch_schedule, load_history, merge, now_iso, parse_schedule  # noqa: E402
from nbaelo.elo import EloModel  # noqa: E402
from nbaelo.players import STATS, load_logs, save_logs, update_logs  # noqa: E402

HISTORY = ROOT / "data" / "history.csv"
LOGS = ROOT / "data" / "player_logs.csv"
PICKS = ROOT / "data" / "picks.csv"
BOOK_LINES = ROOT / "data" / "book_lines.csv"
SITE = ROOT / "site"
BACKTEST_SEASONS = ["2022-23", "2023-24", "2024-25", "2025-26"]
LOG_COLS = ["date", "opp", "home"] + [s for s in STATS] + list(props.COMBOS)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")) + "\n")


def elo_spreads(games, upcoming, season: str) -> dict[str, float]:
    """Pre-game Elo home spread for every finished and upcoming game."""
    model, spreads = EloModel(), {}
    for g in games:
        model._new_season(g.season)
        spreads[g.game_id] = model.predict(g)["home_spread"]
        model.update(g)
    model._new_season(season)
    for g in upcoming:
        spreads[g.game_id] = model.predict(g)["home_spread"]
    return spreads


def next_games(upcoming) -> list[dict]:
    """Each team's next scheduled game, from that team's point of view."""
    out, seen = [], set()
    for g in sorted(upcoming, key=lambda x: (x.date, x.game_id)):
        for team, opp, home in ((g.home, g.away, 1), (g.away, g.home, 0)):
            if team not in seen:
                seen.add(team)
                out.append({"game_id": g.game_id, "date": g.date, "season": g.season,
                            "team": team, "opp": opp, "home": home})
    return out


def r(x, nd=1):
    return None if x != x else round(float(x), nd)  # NaN -> None


def player_pages(df, out: Path) -> None:
    """One JSON per player: full game log plus per-season averages."""
    real = df[~df["future"]].copy()
    real["date"] = real["date"].dt.strftime("%Y-%m-%d")
    avg_cols = [c for c in LOG_COLS if c not in ("date", "opp", "home")]
    index = []
    for pid, grp in real.groupby("player_id", sort=False):
        last = grp.iloc[-1]
        seasons = []
        for s, sg in grp.groupby("season"):
            pct = lambda m, a: r(sg[m].sum() / sg[a].sum(), 3) if sg[a].sum() else None  # noqa: E731
            seasons.append({
                "season": s, "team": "/".join(dict.fromkeys(sg["team"])), "gp": len(sg),
                **{c: r(sg[c].mean()) for c in avg_cols},
                "fg_pct": pct("fgm", "fga"), "fg3_pct": pct("fg3m", "fg3a"), "ft_pct": pct("ftm", "fta"),
            })
        log = [[row[c] if c in ("date", "opp") else r(row[c]) for c in LOG_COLS]
               for _, row in grp[LOG_COLS].iterrows()]
        write_json(out / f"{pid}.json", {
            "id": pid, "name": last["player"], "team": last["team"],
            "cols": LOG_COLS, "log": log, "seasons": seasons,
        })
        index.append([pid, last["player"], last["team"], last["season"]])
    index.sort(key=lambda x: (x[3], x[1]), reverse=True)
    write_json(out / "index.json", index)


def book_side(stat: str, proj: list, line: float, cal: dict) -> tuple[float, float]:
    """Model's calibrated (P over, P under) at a line; a whole-number line can push."""
    mu, param = proj
    c = cal.get(stat)
    over = float(props.p_over(stat, mu, param, line, c))
    under = 1 - float(props.p_over(stat, mu, param, line - 1 if float(line).is_integer() else line, c))
    return round(over, 4), round(under, 4)


def attach_book_lines(players: list[dict], logs: list[dict], cal: dict, fetch: bool) -> dict:
    """Fetch today's sportsbook lines (if asked and a key is set), save and grade them, and
    put each player's lines on their projection as p["book"][stat]. Returns the record."""
    rows = booklines.load(BOOK_LINES)
    key = odds.api_key()
    day = min((p["date"] for p in players), default=None)
    if fetch and key and day:
        try:
            slate = odds.fetch_slate(day, key)
            new, at = [], now_iso()
            for p in players:
                if p["date"] != day:
                    continue
                game = slate.get((p["opp"], p["team"]) if p["home"] else (p["team"], p["opp"]), {})
                for (k, stat), c in game.items():
                    if k != injuries.name_key(p["name"]):
                        continue
                    po, pu = book_side(stat, p["proj"][stat], c["line"], cal)
                    new.append({"fetched_at": at, "date": day, "game_id": p["game_id"], "player_id": p["id"],
                                "player": p["name"], "team": p["team"], "stat": stat, "line": c["line"],
                                "over": c["over"], "under": c["under"], "books": c["books"],
                                "best_over": c["best_over"][0], "best_over_book": c["best_over"][1],
                                "best_under": c["best_under"][0], "best_under_book": c["best_under"][1],
                                "p_over": po, "p_under": pu, "result": "", "actual": ""})
            rows = booklines.upsert(rows, new)
            print(f"book lines: {len(new)} matched to projected players")
        except Exception as e:  # noqa: BLE001 - the build shouldn't fail over it
            print(f"book lines unavailable: {e}")
    elif fetch and not key:
        print("book lines: no Odds API key set; skipping")
    booklines.grade(rows, logs)
    if rows:
        booklines.save(BOOK_LINES, rows)
    # Today's saved lines go on the projections, with the current model's chances at them.
    by = {(r["date"], str(r["player_id"]), r["stat"]): r for r in rows}
    for p in players:
        for stat in props.TARGETS:
            r = by.get((p["date"], str(p["id"]), stat))
            if r:
                po, pu = book_side(stat, p["proj"][stat], r["line"], cal)
                p.setdefault("book", {})[stat] = {
                    "line": r["line"], "over": r["over"], "under": r["under"], "books": r["books"],
                    "best_over": [r["best_over"], r["best_over_book"]],
                    "best_under": [r["best_under"], r["best_under_book"]],
                    "p_over": po, "p_under": pu, "at": r["fetched_at"]}
    return booklines.summarize(rows) if rows else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", type=Path, help="local schedule JSON (skips the network)")
    ap.add_argument("--no-fetch", action="store_true", help="don't download new box scores")
    ap.add_argument("--backtest", action="store_true", help="run the walk-forward backtest")
    ap.add_argument("--odds", action="store_true", help="fetch sportsbook lines (needs an Odds API key)")
    ap.add_argument("--out", type=Path, default=SITE)
    args = ap.parse_args()

    raw = json.loads(args.schedule.read_text()) if args.schedule else fetch_schedule()
    season = raw["leagueSchedule"]["seasonYear"]
    finished, upcoming = parse_schedule(raw)

    # Drop rows from current-season games that aren't final (a backfill run
    # mid-game picks up partial box scores), then fetch anything missing.
    final_ids = {g.game_id for g in finished}
    logs = [x for x in load_logs(LOGS) if x["season"] != season or x["game_id"] in final_ids]
    if not args.no_fetch:
        logs = update_logs(logs, finished)
    save_logs(LOGS, logs)

    spreads = elo_spreads(merge(load_history(HISTORY), finished), upcoming, season)
    nxt = next_games(upcoming)
    base = props.to_frame(logs)
    cands = props.candidates(base, nxt)
    # Tonight's injury report goes into the features: who's out changes teammates' and
    # opponents' projections. It's saved, with headlines and transactions, as the News
    # tab's fallback when ESPN can't be reached live.
    news = {"built_at": now_iso()}
    try:
        news["injuries"] = injuries.parse(injuries.fetch())
        print(f"injury report: {injuries.mark_out(cands, news['injuries'])} projected players ruled out")
    except Exception as e:  # noqa: BLE001 - the build shouldn't fail over it
        print(f"injury report unavailable: {e}")
    df = props.build_features(props.to_frame(logs + cands), spreads)
    print(f"{len(logs)} player-games, {len(cands)} players to project")

    if args.backtest:
        bt = props.backtest(df, BACKTEST_SEASONS)
        write_json(args.out / "props_backtest.json",
                   {"built_at": now_iso(), "seasons": BACKTEST_SEASONS, "targets": bt})
        for t in ("pts", "pra"):
            print(f"{t}: {bt[t]}")

    proj, disp, cal, past, past_mu = props.train_and_project(df)
    fut = df[df["future"]]
    players = []
    for i, row in fut.iterrows():
        mu = proj.loc[i]
        players.append({
            "id": row["player_id"], "name": row["player"], "team": row["team"],
            "opp": row["opp"], "home": int(row["home"]), "game_id": row["game_id"],
            "date": row["date"].strftime("%Y-%m-%d"), "likely_out": bool(row["likely_out"]),
            "gp": int(row["gp"]), "spread": r(row["spread"]),
            "without": [r(row["out_pts"]), r(row["opp_out_pts"])],  # scoring missing: own team, opponent
            "proj": {t: [r(mu[t], 2), r(props.dist_param(disp[t], mu[t]), 5)] for t in props.TARGETS},
            "l10": {t: r(row[f"{t}_l10"]) for t in props.TARGETS},
            "e5": {t: r(row[f"{t}_e5"], 2) for t in props.TARGETS},
            "sea": {t: r(row[f"{t}_sea"]) for t in props.TARGETS},
        })
    if "injuries" in news:  # attach statuses; anyone ruled out is skipped by the picks
        print(f"injury report: {injuries.apply(players, news['injuries'])} projected players listed")
    for key, path, parse in (("news", "news?limit=40", wire.parse_news),
                             ("transactions", "transactions", wire.parse_transactions)):
        try:
            news[key] = parse(wire.fetch(path))
        except Exception as e:  # noqa: BLE001
            print(f"{key} unavailable: {e}")
    write_json(args.out / "news.json", news)
    book = attach_book_lines(players, logs, cal, args.odds)
    players.sort(key=lambda p: (p["date"], p["game_id"], p["team"], -(p["proj"]["min"][0] or 0)))
    games = sorted({(g["date"], g["game_id"]) for g in nxt})
    by_id = {g.game_id: g for g in upcoming}
    tips = {g["gameId"]: g.get("gameDateTimeUTC") for d in raw["leagueSchedule"]["gameDates"] for g in d["games"]}
    write_json(args.out / "props.json", {
        "built_at": now_iso(), "season": season, "labels": props.LABELS, "targets": props.TARGETS,
        "cal": cal,  # per-stat [a, b]: logit P'(stat > x) = a * logit P(stat > x) + b
        "games": [{"game_id": gid, "date": d, "home": by_id[gid].home, "away": by_id[gid].away,
                   "home_spread": spreads.get(gid), "tip": tips.get(gid)} for d, gid in games],
        "players": players,
    })
    player_pages(df, args.out / "players")

    # The model's picks: grade earlier ones, lock in today's, and simulate last season.
    made = model_picks.load(PICKS)
    model_picks.grade(made, logs)
    day = min((p["date"] for p in players), default=None)
    popular = booklines.popular(booklines.load(BOOK_LINES), day, model_picks.POPULAR_DAYS) if day else set()
    new = model_picks.make_picks(players, made, now_iso(), cal, popular)
    made += new
    model_picks.save(PICKS, made)
    write_json(args.out / "picks.json", {
        "built_at": now_iso(),
        "rules": {"markets": model_picks.MARKETS, "min_p": model_picks.MIN_P, "per_day": model_picks.PER_DAY,
                  "min_minutes": model_picks.MIN_MINUTES,
                  "popular_minutes": model_picks.POPULAR_MINUTES, "odds": model_picks.ODDS},
        "live": {**model_picks.summarize(made),
                 "picks": sorted(made, key=lambda x: (x["date"], x["p"]), reverse=True)},  # newest first
        "sim": model_picks.simulate(past, past_mu, disp, cal),
        "books": book,
    })
    print(f"picks: {len(new)} new, {len(made)} total")
    print(f"wrote {len(players)} projections across {len(games)} games")


if __name__ == "__main__":
    main()
