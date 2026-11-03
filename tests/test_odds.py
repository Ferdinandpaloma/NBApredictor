import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo import booklines, odds  # noqa: E402


def book(title, line, over, under, player="Nikola Jokić", key="player_points"):
    return {"title": title, "markets": [{"key": key, "outcomes": [
        {"name": "Over", "description": player, "point": line, "price": over},
        {"name": "Under", "description": player, "point": line, "price": under}]}]}


class OddsTests(unittest.TestCase):
    def test_parse_and_consensus(self):
        event = {"bookmakers": [book("DraftKings", 28.5, -115, -105), book("FanDuel", 28.5, -105, -125),
                                book("BetMGM", 29.5, +100, -130),
                                book("DraftKings", 12.5, -110, -110, key="player_rebounds"),
                                {"title": "X", "markets": [{"key": "h2h", "outcomes": []}]}]}
        rows = odds.parse(event)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["key"], "nikola jokic")
        c = odds.consensus(rows)
        pts = c[("nikola jokic", "pts")]
        self.assertEqual(pts["line"], 28.5)      # two books post 28.5, one 29.5
        self.assertEqual(pts["books"], 2)
        self.assertEqual(pts["best_over"], [-105, "FanDuel"])
        self.assertEqual(pts["best_under"], [-105, "DraftKings"])
        self.assertEqual(pts["over"], -110)      # median of -115 and -105, by payout
        self.assertEqual(c[("nikola jokic", "reb")]["line"], 12.5)

    def test_median_odds_across_even(self):
        self.assertEqual(odds._median_odds([-110, +110]), 100)
        self.assertEqual(odds._median_odds([+150]), 150)


class BookLineTests(unittest.TestCase):
    def rows(self):
        base = {"fetched_at": "t", "date": "2026-11-02", "game_id": "g1", "team": "DEN", "books": 5,
                "best_over": -105, "best_over_book": "A", "best_under": -105, "best_under_book": "B",
                "result": "", "actual": ""}
        return [
            {**base, "player_id": "1", "player": "A", "stat": "pts", "line": 28.5, "over": -110, "under": -110,
             "p_over": 0.58, "p_under": 0.42},   # model likes the over by 8 points
            {**base, "player_id": "2", "player": "B", "stat": "pra", "line": 30.0, "over": -110, "under": -110,
             "p_over": 0.40, "p_under": 0.52},   # whole line: 0.52 / 0.92 = 56.5% among decided
            {**base, "player_id": "3", "player": "C", "stat": "pts", "line": 10.5, "over": -110, "under": -110,
             "p_over": 0.51, "p_under": 0.49},   # no edge
            {**base, "player_id": "4", "player": "D", "stat": "pts", "line": 10.5, "over": -110, "under": -110,
             "p_over": 0.70, "p_under": 0.30, "game_id": "g2"},  # didn't play
        ]

    def test_grade_bets_and_summary(self):
        rows = self.rows()
        logs = [{"game_id": "g1", "player_id": "1", "pts": 31, "reb": 0, "ast": 0},
                {"game_id": "g1", "player_id": "2", "pts": 20, "reb": 6, "ast": 4},
                {"game_id": "g1", "player_id": "3", "pts": 12, "reb": 0, "ast": 0},
                {"game_id": "g2", "player_id": "9", "pts": 5, "reb": 0, "ast": 0}]
        booklines.grade(rows, logs)
        self.assertEqual([r["result"] for r in rows], ["over", "push", "over", "void"])
        bs = booklines.bets(rows, 0.03)
        self.assertEqual([(b["player"], b["side"]) for b in bs], [("A", "over"), ("B", "under")])
        self.assertAlmostEqual(bs[0]["units"], 100 / 110)
        self.assertEqual(bs[1]["units"], 0.0)   # push: stake back
        s = booklines.summarize(rows)
        self.assertEqual(s["graded"], 3)
        e3 = s["by_edge"][0]
        self.assertEqual((e3["n"], e3["won"]), (1, 1))  # the push isn't a decided bet
        self.assertEqual(s["by_edge"][2]["n"], 0)       # nothing with a 10-point edge after vig removal

    def test_upsert_keeps_latest_fetch(self):
        rows = self.rows()
        later = dict(rows[0], line=29.5, fetched_at="t2")
        out = booklines.upsert(rows, [later])
        self.assertEqual(len(out), 4)
        self.assertEqual([r["line"] for r in out if r["player_id"] == "1"], [29.5])

    def test_round_trip(self):
        import tempfile
        rows = self.rows()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.csv"
            booklines.save(p, rows)
            back = booklines.load(p)
        self.assertEqual(len(back), 4)
        self.assertEqual(back[0]["over"], -110)
        self.assertIsInstance(back[0]["p_over"], float)


if __name__ == "__main__":
    unittest.main()
