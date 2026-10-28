# NBA Elo Predictor

A statically generated NBA prediction site. A daily GitHub Action replays every game through an Elo model, predicts the next week of games, writes JSON, and deploys a static page to GitHub Pages. No server, no database.

## How it works

```
data/history.csv  ─┐
                   ├─► Elo replay ─► site/predictions.json ─► GitHub Pages
cdn.nba.com feed  ─┘                 site/ratings.json
(current season)                     site/meta.json (backtest stats)
```

- **`nbaelo/elo.py`**: the model. Teams start at 1505; winners take points from losers, scaled by margin of victory. Home court is worth 100 Elo (~3.5 points). Ratings regress 25% toward the mean each offseason.
- **`nbaelo/data.py`**: reads NBA's public schedule feed (`cdn.nba.com/static/json/staticData/scheduleLeagueV2.json`), which includes scores for finished games. It's a static file, so it works from GitHub Actions.
- **`scripts/build.py`**: replays all games, predicts upcoming ones, writes the JSON.
- **`scripts/backfill_history.py`**: one-time pull of past seasons via `nba_api`.
- **`site/index.html`**: the page. It just fetches the JSON.

## Setup

1. **Backfill history (locally, once).** stats.nba.com often blocks cloud IPs, so run this on your own machine:
   ```bash
   pip install nba_api pandas
   python -m scripts.backfill_history 2018 2025
   git add data/history.csv
   ```
   You can skip this; the model will just start cold at the beginning of the current season.

2. **Build locally.**
   ```bash
   python -m scripts.build
   cd site && python -m http.server   # open http://localhost:8000
   ```

3. **Deploy.** Push to GitHub, then go to **Settings → Pages → Source: GitHub Actions**. The workflow runs daily at about 6am Pacific, or on demand from the Actions tab.

## Player props

`site/props.html` projects every rotation player's next game: points, rebounds, assists, 3PM, steals, blocks, turnovers, shooting, minutes, and the combo markets (PRA, P+R, P+A, R+A, S+B). Enter a sportsbook line (and optionally the odds) to get P(over)/P(under), fair odds and expected value. Every player since 2018-19 has a page with season averages and a full game log.

- **`nbaelo/players.py`**: box scores. History in `data/player_logs.csv`; new games come from the CDN box score feed, which works from GitHub Actions.
- **`nbaelo/props.py`**: the model. Features use only earlier games: recent form (exponentially weighted, last 10, season), per-minute rates × projected minutes, opponent defense vs the league for that stat, pace, rest/back-to-backs, Elo spread (blowout risk), and teammates who sat. One gradient-boosted model per stat predicts the mean. A negative binomial around it, with dispersion fitted on out-of-sample games, gives the probabilities.
- **Rotation / injuries**: players are listed if they averaged 10+ minutes in the team's last 10 games. Anyone who missed the last 3 is flagged "likely out". There's no injury feed, so always check news before betting.

```bash
pip install -r requirements.txt
python -m scripts.backfill_players 2018 2026   # once, locally (~2 min)
python -m scripts.build_props                    # ~2 min
python -m scripts.build_props --backtest         # also writes site/props_backtest.json (~10 min)
```

The backtest walks forward (train on earlier seasons, predict the next) and compares the model's average miss against season average, last-10 and recent form. It also checks that P(over) is calibrated. Results are on the page's "Model accuracy" tab. Single-game stats are noisy, so treat the probabilities as an edge finder, not a sure thing.

## Tests

```bash
python -m unittest discover -s tests -v
```

The team Elo build and its tests need only the standard library. The props tests are skipped unless `requirements.txt` is installed.

## Using it from an app

Point any client at the published JSON, for example `https://<you>.github.io/<repo>/predictions.json`:

```json
{ "game_id": "0022600123", "date": "2026-10-28", "home": "GSW", "away": "OKC",
  "home_elo": 1561.2, "away_elo": 1652.8,
  "home_win_prob": 0.4116, "away_win_prob": 0.5884, "home_spread": 0.0 }
```

## Ideas for next steps

- **Tune** `K`, `HOME_ADV` and `SEASON_CARRY` against the backtest log loss.
- **Rest/travel:** subtract Elo for back-to-backs.
- **Injuries:** adjust ratings when stars sit (the biggest gain, and the hardest data to get).
- **Second model:** logistic regression or gradient boosting on rolling net rating + Elo, compared in `meta.json`.
- **Grade past picks:** save each day's predictions and score them once games finish.
# NBApredictor
