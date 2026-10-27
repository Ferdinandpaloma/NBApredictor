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

## Tests

```bash
python -m unittest discover -s tests -v
```

No dependencies needed for the build or tests (standard library only). `nba_api` and `pandas` are only for the backfill.

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
