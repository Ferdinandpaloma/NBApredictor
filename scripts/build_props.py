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
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo import picks as model_picks  # noqa: E402
from nbaelo import props  # noqa: E402
from nbaelo.data import fetch_schedule, load_history, merge, now_iso, parse_schedule  # noqa: E402
from nbaelo.elo import EloModel  # noqa: E402
from nbaelo.players import STATS, load_logs, save_logs, update_logs  # noqa: E402

HISTORY = ROOT / "data" / "history.csv"
LOGS = ROOT / "data" / "player_logs.csv"
PICKS = ROOT / "data" / "picks.csv"
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", type=Path, help="local schedule JSON (skips the network)")
    ap.add_argument("--no-fetch", action="store_true", help="don't download new box scores")
    ap.add_argument("--backtest", action="store_true", help="run the walk-forward backtest")
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
    df = props.build_features(props.to_frame(logs + cands), spreads)
    print(f"{len(logs)} player-games, {len(cands)} players to project")

    if args.backtest:
        bt = props.backtest(df, BACKTEST_SEASONS)
        write_json(args.out / "props_backtest.json",
                   {"built_at": now_iso(), "seasons": BACKTEST_SEASONS, "targets": bt})
        for t in ("pts", "pra"):
            print(f"{t}: {bt[t]}")

    proj, disp, past, past_mu = props.train_and_project(df)
    fut = df[df["future"]]
    players = []
    for i, row in fut.iterrows():
        mu = proj.loc[i]
        players.append({
            "id": row["player_id"], "name": row["player"], "team": row["team"],
            "opp": row["opp"], "home": int(row["home"]), "game_id": row["game_id"],
            "date": row["date"].strftime("%Y-%m-%d"), "likely_out": bool(row["likely_out"]),
            "gp": int(row["gp"]), "spread": r(row["spread"]),
            "proj": {t: [r(mu[t], 2), r(props.dist_param(disp[t], mu[t]), 5)] for t in props.TARGETS},
            "l10": {t: r(row[f"{t}_l10"]) for t in props.TARGETS},
            "e5": {t: r(row[f"{t}_e5"], 2) for t in props.TARGETS},
            "sea": {t: r(row[f"{t}_sea"]) for t in props.TARGETS},
        })
    players.sort(key=lambda p: (p["date"], p["game_id"], p["team"], -(p["proj"]["min"][0] or 0)))
    games = sorted({(g["date"], g["game_id"]) for g in nxt})
    by_id = {g.game_id: g for g in upcoming}
    tips = {g["gameId"]: g.get("gameDateTimeUTC") for d in raw["leagueSchedule"]["gameDates"] for g in d["games"]}
    write_json(args.out / "props.json", {
        "built_at": now_iso(), "season": season, "labels": props.LABELS, "targets": props.TARGETS,
        "games": [{"game_id": gid, "date": d, "home": by_id[gid].home, "away": by_id[gid].away,
                   "home_spread": spreads.get(gid), "tip": tips.get(gid)} for d, gid in games],
        "players": players,
    })
    player_pages(df, args.out / "players")

    # The model's picks: grade earlier ones, lock in today's, and simulate last season.
    made = model_picks.load(PICKS)
    model_picks.grade(made, logs)
    new = model_picks.make_picks(players, made, now_iso())
    made += new
    model_picks.save(PICKS, made)
    write_json(args.out / "picks.json", {
        "built_at": now_iso(),
        "rules": {"markets": model_picks.MARKETS, "min_p": model_picks.MIN_P, "per_day": model_picks.PER_DAY,
                  "min_minutes": model_picks.MIN_MINUTES, "odds": model_picks.ODDS},
        "live": {**model_picks.summarize(made),
                 "picks": sorted(made, key=lambda x: (x["date"], x["p"]), reverse=True)},  # newest first
        "sim": model_picks.simulate(past, past_mu, disp),
    })
    print(f"picks: {len(new)} new, {len(made)} total")
    print(f"wrote {len(players)} projections across {len(games)} games")


if __name__ == "__main__":
    main()
