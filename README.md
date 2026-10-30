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
- **`web/`**: the site (`props.html`; `index.html` just redirects to it) and its JS, built with Vite into `dist/`. **`site/`** holds the JSON the Python builds write; Vite copies it into `dist/` as-is.

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
   npm install
   npm run dev        # open the URL it prints, e.g. http://localhost:5173/props.html
   ```

3. **Deploy.** Push to GitHub, then go to **Settings → Pages → Source: GitHub Actions**. The workflow runs daily at about 6am Pacific, or on demand from the Actions tab.

## Player props

`web/props.html` projects every rotation player's next game: points, rebounds, assists, 3PM, steals, blocks, turnovers, shooting, minutes, and the combo markets (PRA, P+R, P+A, R+A, S+B). Enter a sportsbook line (and optionally the odds) to get P(over)/P(under), fair odds and expected value. Every player since 2018-19 has a page with season averages and a full game log.

- **`nbaelo/players.py`**: box scores. History in `data/player_logs.csv`; new games come from the CDN box score feed, which works from GitHub Actions.
- **`nbaelo/props.py`**: the model. Features use only earlier games: recent form (exponentially weighted, last 10, season), per-minute rates × projected minutes, opponent defense vs the league for that stat, pace, rest/back-to-backs, Elo spread (blowout risk), and who's missing on both teams: scoring and minutes of regulars (20+ min) who aren't playing, from the box score for past games and the morning injury report for upcoming ones. One gradient-boosted model per stat predicts the mean. A negative binomial around it, with dispersion fitted on out-of-sample games, gives the probabilities.
- **Rotation / injuries**: players are listed if they averaged 10+ minutes in the team's last 10 games. Anyone who missed the last 3 is flagged "likely out". Players the injury report rules Out are flagged too; late scratches still aren't known, so check news before betting.

```bash
pip install -r requirements.txt
python -m scripts.backfill_players 2018 2026   # once, locally (~2 min)
python -m scripts.build_props                    # ~2 min
python -m scripts.build_props --backtest         # also writes site/props_backtest.json (~10 min)
```

The backtest walks forward (train on earlier seasons, predict the next) and compares the model's average miss against season average, last-10 and recent form. It also checks that P(over) is calibrated. Results are on the page's "Model accuracy" tab. Single-game stats are noisy, so treat the probabilities as an edge finder, not a sure thing.

## Daily updates

cdn.nba.com blocks GitHub's runners (403), and stats.nba.com blocks cloud IPs, so the data is refreshed from a Mac instead. `scripts/daily.sh` pulls the current season from stats.nba.com, runs both builds, commits and pushes; Vercel redeploys on the push. A launchd job runs it at 9:00 every morning (or on wake if the Mac was asleep). macOS won't let background jobs read ~/Documents, so the job runs from its own clone in `~/Library/Application Support/nba-predictor` (with its own `.venv`); `git pull` your working copy to see the updates:

```bash
# install (already done on the main machine)
git clone https://github.com/Ferdinandpaloma/NBApredictor.git ~/Library/Application\ Support/nba-predictor
cd ~/Library/Application\ Support/nba-predictor && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp scripts/com.nbapredictor.daily.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nbapredictor.daily.plist

launchctl kickstart gui/$(id -u)/com.nbapredictor.daily   # run it now
tail -f ~/Library/Logs/nba-predictor.log                   # watch it
launchctl bootout gui/$(id -u)/com.nbapredictor.daily     # turn it off
```

The GitHub Action still runs but its build steps fail softly, so it just republishes the last committed data.

## Model picks

Each morning the build (`nbaelo/picks.py`) publishes up to 10 over/unders for the day's slate where the model disagrees most with a player's recent form, then grades them from the box scores once the games are final. Picks are stored in `data/picks.csv` and lock when published (a game's picks never change). The **Model Picks** tab shows open picks, the live record, hit rate vs the model's own predicted rate (by confidence and by market), and a simulation of the same rules on last season.

The line for each pick is the half point where recent form alone is closest to 50/50 (a stand-in for a book line), and only markets a book would plausibly post count, so trivial picks like "under 0.5 threes" for a center are excluded. Because real sportsbook lines are sharper than recent form, the tracker measures accuracy, not profit; use My Bets with real odds for that.

## News & injuries

The **News** tab shows ESPN's NBA headlines, injury report and transactions, read live in the browser from ESPN's public feeds (`web/src/news.js`) and refreshed every 5 minutes while open. The morning build also saves a copy to `site/news.json` (`nbaelo/wire.py`, `nbaelo/injuries.py`), which the page falls back to if the live feed can't be reached.

The injury report feeds the rest of the site: players are matched by name, Out / DTD tags show on the Slate, Board, Line Desk, parlay slip and Model Picks, and players ruled **Out** are marked likely out in the build, so Model Picks skips them. Regulars ruled Out also feed the projections: teammates' minutes and stats go up, and opponents get the matchup against a weakened lineup. In the backtest (2023-24 to 2025-26) this cut points error from 4.55 to 4.48, PRA from 5.98 to 5.84 and minutes from 4.86 to 4.64.

## Team picks record

The **Team Picks** tab also shows how the Elo picks did: every finished game this season with the model's pick, its confidence and whether it was right, plus hit rate by confidence and last season's record. `scripts/build.py` writes these to `site/team_results.json` by replaying the season (`past_picks` in `nbaelo/elo.py`), so each pick uses only the ratings the model had before that game.

## Team logos

`site/logos/` holds the 30 team logos (96px PNGs, plus dark-mode versions for the four teams that have one), downloaded from ESPN's public logo CDN by `scripts/fetch_logos.sh`. Re-run it only if a team rebrands; if the set of dark-mode logos changes, update `DARK_LOGOS` in `web/src/props.js`. The logos are the teams' trademarks, shown here only to identify them.

## Player photos

Headshots load in the visitor's browser straight from the NBA's image server (`cdn.nba.com/headshots/...`), keyed by the same player ids the data uses, so nothing is stored in the repo and new players appear automatically. If a photo is missing or the server refuses it, it's left out entirely.

## Accounts (Firebase)

Sign in with Google or email/password, save bets from the Line Desk, and the **My Bets** tab grades them against the box scores once games are final (record, units, ROI, and the model's predicted hit rate vs the real one). Code: `web/src/account.js` (Firebase), `web/src/grade.js` (grading). Without a config the site works normally and the sign-in button explains it isn't set up.

**Odds or multiplier:** the Line Desk has a "Your book shows" switch. Pick *Multiplier* if your app shows payouts like 1.91x or 3x instead of odds (the total returned per 1 staked, stake included); the whole page then shows odds that way. Bets are still stored as American odds, so switching never changes a saved bet.

**Parlays:** on the Line Desk, "+ Add to parlay" collects props from different players (2–12 legs) into one bet. The slip shows the model's chance that every leg hits (legs multiplied as if independent, so same-game legs get a warning), the payout from the leg odds or your book's parlay odds, and the value per $100. A parlay loses if any leg loses; a leg that pushes or is void drops out and the payout shrinks to the remaining legs. The **+** buttons on The Board and Model Picks add that side to the parlay at −110 (tap again to remove), and a bar at the bottom of every tab shows the parlay while you build it.

One-time setup in the [Firebase console](https://console.firebase.google.com):

1. **Project settings → Your apps → Web app → SDK setup and configuration → Config.** Copy the values into `.env` (template: `.env.example`) and commit it. These values are public by design; security comes from the rules below.
2. **Authentication → Sign-in method:** enable **Google** and **Email/Password**.
3. **Authentication → Settings → Authorized domains:** add your Vercel domain (e.g. `your-app.vercel.app`). `localhost` is there already.
4. **Firestore Database → Create database** (production mode), then **Rules:** paste `firestore.rules` and publish. Each user can only read and write their own bets.

Vercel builds the site with `npm ci && npm run build` (see `vercel.json`).

## Tests

```bash
python -m unittest discover -s tests -v
```

`npm test` checks the bet grading. The team Elo build and its tests need only the standard library. The props tests are skipped unless `requirements.txt` is installed.

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
