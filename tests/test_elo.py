import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo.data import parse_schedule  # noqa: E402
from nbaelo.elo import HOME_ADV, MEAN, EloModel, Game, backtest, win_prob  # noqa: E402


def team(code, score=0):
    return {"teamId": 1, "teamTricode": code, "score": score, "wins": 0, "losses": 0}


def fake_schedule():
    """A tiny feed in the same shape as cdn.nba.com's scheduleLeagueV2.json."""
    return {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": [
        {"gameDate": "10/04/2026 00:00:00", "games": [  # preseason: ignored
            {"gameId": "0012600001", "gameStatus": 3, "gameDateEst": "2026-10-04T00:00:00Z",
             "homeTeam": team("LAL", 99), "awayTeam": team("BOS", 90)}]},
        {"gameDate": "10/21/2026 00:00:00", "games": [
            {"gameId": "0022600001", "gameStatus": 3, "gameDateEst": "2026-10-21T00:00:00Z",
             "homeTeam": team("OKC", 120), "awayTeam": team("HOU", 100)},
            {"gameId": "0022600002", "gameStatus": 3, "gameDateEst": "2026-10-21T00:00:00Z",
             "homeTeam": team("LAL", 104), "awayTeam": team("GSW", 110)}]},
        {"gameDate": "10/28/2026 00:00:00", "games": [
            {"gameId": "0022600003", "gameStatus": 1, "gameDateEst": "2026-10-28T00:00:00Z",
             "homeTeam": team("GSW"), "awayTeam": team("OKC")},
            {"gameId": "0042600001", "gameStatus": 1, "gameDateEst": "2026-10-28T00:00:00Z",
             "homeTeam": team(""), "awayTeam": team("")}]},  # TBD playoff slot: ignored
    ]}}


class EloTests(unittest.TestCase):
    def test_equal_teams_home_edge(self):
        self.assertAlmostEqual(win_prob(1500, 1500, neutral=True), 0.5)
        self.assertAlmostEqual(win_prob(1500, 1500), 1 / (1 + 10 ** (-HOME_ADV / 400)))

    def test_update_is_zero_sum_and_rewards_winner(self):
        m = EloModel()
        m.update(Game("1", "2026-10-21", "2026-27", "AAA", "BBB", 110, 100))
        self.assertGreater(m.ratings["AAA"], MEAN)
        self.assertAlmostEqual(m.ratings["AAA"] + m.ratings["BBB"], 2 * MEAN)

    def test_upset_moves_more_than_expected_win(self):
        a, b = EloModel(), EloModel()
        a.update(Game("1", "d", "s", "H", "A", 110, 100))   # home wins (expected)
        b.update(Game("1", "d", "s", "H", "A", 100, 110))   # away wins (upset)
        self.assertGreater(abs(b.ratings["A"] - MEAN), abs(a.ratings["H"] - MEAN))

    def test_season_regression(self):
        m = EloModel(ratings={"X": 1705.0}, season="2025-26")
        m._new_season("2026-27")
        self.assertAlmostEqual(m.ratings["X"], MEAN + 0.75 * 200)

    def test_backtest_learns_a_dominant_team(self):
        games = []
        for s, season in enumerate(["2024-25", "2025-26"]):
            for i in range(60):
                home, away = ("GOOD", "BAD") if i % 2 else ("BAD", "GOOD")
                hp, ap = (115, 100) if home == "GOOD" else (100, 115)
                games.append(Game(f"{s}{i:03}", f"202{4 + s}-11-{i % 28 + 1:02}", season, home, away, hp, ap))
        result = backtest(games)
        self.assertEqual(result["games"], 60)
        self.assertGreater(result["accuracy"], 0.95)


class ScheduleTests(unittest.TestCase):
    def test_parse_filters_and_splits(self):
        finished, upcoming = parse_schedule(fake_schedule())
        self.assertEqual([g.game_id for g in finished], ["0022600001", "0022600002"])
        self.assertEqual([g.game_id for g in upcoming], ["0022600003"])
        self.assertEqual(finished[0].date, "2026-10-21")
        self.assertEqual((finished[1].home_pts, finished[1].away_pts), (104, 110))

    def test_stats_api_fallback(self):
        """CDN refuses -> build falls back to stats.nba.com via nba_api."""
        try:
            from nba_api.stats.library.http import NBAStatsHTTP, NBAStatsResponse
        except ImportError:
            self.skipTest("nba_api not installed")
        from unittest import mock
        from nbaelo import data

        raw = fake_schedule()
        raw["leagueSchedule"].update({"leagueId": "00", "weeks": []})
        fake = lambda self, **kw: NBAStatsResponse(response=json.dumps(raw), status_code=200, url="x")  # noqa: E731
        with mock.patch.object(NBAStatsHTTP, "send_api_request", fake):
            result = data.fetch_schedule(urls=["http://127.0.0.1:9/refused.json"], timeout=2)
        finished, upcoming = parse_schedule(result)
        self.assertEqual(len(finished), 2)
        self.assertEqual(upcoming[0].home, "GSW")

    def test_current_season(self):
        from datetime import date
        from nbaelo.statsapi import current_season
        self.assertEqual(current_season(date(2026, 10, 27)), "2026-27")
        self.assertEqual(current_season(date(2027, 4, 1)), "2026-27")

    def test_build_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = Path(tmp) / "schedule.json"
            sched.write_text(json.dumps(fake_schedule()))
            out = Path(tmp) / "site"
            subprocess.run(
                [sys.executable, "-m", "scripts.build", "--schedule", str(sched), "--out", str(out)],
                cwd=ROOT, check=True, capture_output=True,
            )
            preds = json.loads((out / "predictions.json").read_text())
            self.assertEqual(len(preds), 1)
            p = preds[0]
            self.assertEqual((p["home"], p["away"]), ("GSW", "OKC"))
            self.assertAlmostEqual(p["home_win_prob"] + p["away_win_prob"], 1.0, places=3)
            ratings = json.loads((out / "ratings.json").read_text())
            self.assertGreaterEqual(len(ratings), 4)  # more once history.csv exists
            meta = json.loads((out / "meta.json").read_text())
            self.assertEqual(meta["season"], "2026-27")


if __name__ == "__main__":
    unittest.main()
