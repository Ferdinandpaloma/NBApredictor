import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from nbaelo import picks
except ImportError:  # numpy/scipy not installed
    picks = None


def player(pid, game="G1", date="2026-10-28", mu=30.0, l10=20.0, minutes=34.0, out=False, alpha=0.05):
    """A projected player whose points projection sits `mu - l10` above recent form."""
    proj = {t: [3.0, 0.3] for t in picks.MARKETS}
    l10s = {t: 3.0 for t in picks.MARKETS}  # other markets: projection == form, never picked
    proj["pts"], l10s["pts"] = [mu, alpha], l10
    proj["min"] = [minutes, 5.0]
    return {"id": pid, "name": pid, "team": "AAA", "opp": "BBB", "home": 1, "game_id": game,
            "date": date, "likely_out": out, "proj": proj, "l10": l10s}


def row(game, pid, pts, reb=5, ast=3):
    return {"game_id": game, "player_id": pid, "pts": pts, "reb": reb, "ast": ast, "fg3m": 1}


@unittest.skipIf(picks is None, "needs numpy and scipy")
class PickTests(unittest.TestCase):
    def test_strong_projection_becomes_an_over_pick(self):
        m = picks.best_market(player("p1", mu=30, l10=20))
        self.assertEqual((m["stat"], m["side"]), ("pts", "over"))
        self.assertIn(m["line"], (19.5, 20.5))
        self.assertGreaterEqual(m["p"], picks.MIN_P)

    def test_form_line_is_close_to_a_coin_flip(self):
        import numpy as np
        for stat, l10, alpha in (("pts", 20.0, 0.05), ("reb", 3.0, 0.3), ("fg3m", 1.2, 0.4), ("pra", 33.7, 0.04)):
            line = float(picks.form_line(stat, l10, alpha))
            p = float(picks.p_over(stat, l10, alpha, line))
            others = [abs(float(picks.p_over(stat, l10, alpha, line + d)) - 0.5) for d in (-1, 1) if line + d > 0]
            self.assertLessEqual(abs(p - 0.5), min(others), (stat, line, p))
        arr = picks.form_line("pts", np.array([20.0, 9.3]), np.array([0.05, 0.08]))
        self.assertEqual(arr.shape, (2,))

    def test_no_pick_on_markets_a_book_would_not_post(self):
        pl = player("big", mu=20, l10=20)
        pl["proj"]["fg3m"], pl["l10"]["fg3m"] = [0.02, 0.5], 0.0  # never shoots threes
        self.assertIsNone(picks.best_market(pl))

    def test_weak_edge_out_or_low_minutes_get_no_pick(self):
        self.assertIsNone(picks.best_market(player("p", mu=20.6, l10=20)))
        self.assertIsNone(picks.best_market(player("p", out=True)))
        self.assertIsNone(picks.best_market(player("p", minutes=12)))

    def test_only_todays_slate_and_strongest_first(self):
        ps = [player("a", mu=26), player("b", mu=34), player("c", date="2026-10-29", game="G2", mu=40)]
        made = picks.make_picks(ps, [], "t")
        self.assertEqual([x["player_id"] for x in made], ["b", "a"])

    def test_games_with_picks_are_locked(self):
        first = picks.make_picks([player("a", mu=30)], [], "t1")
        again = picks.make_picks([player("a", mu=30), player("b", mu=35)], first, "t2")
        self.assertEqual(again, [])  # same game: no new or changed picks

    def test_daily_cap(self):
        ps = [player(f"p{i}", game=f"G{i}", mu=30 + i) for i in range(picks.PER_DAY + 5)]
        self.assertEqual(len(picks.make_picks(ps, [], "t")), picks.PER_DAY)

    def test_grading_won_lost_push_void_pending(self):
        made = picks.make_picks([player("a", game="G1", mu=30), player("b", game="G2", mu=30),
                                 player("c", game="G3", mu=30), player("d", game="G4", mu=30)], [], "t")
        made.append({**made[0], "player_id": "e", "game_id": "G1", "result": "", "actual": ""})
        picks.grade(made, [row("G1", "a", 25), row("G2", "b", 12), row("G3", "x", 9)])
        got = {x["player_id"]: x["result"] for x in made}
        self.assertEqual(got, {"a": "won", "b": "lost", "c": "void", "d": "", "e": "void"})

    def test_combo_markets_grade_on_the_sum(self):
        x = {"game_id": "G", "player_id": "a", "stat": "pra", "line": 30.5, "side": "under", "result": "", "actual": ""}
        picks.grade([x], [row("G", "a", 20, 6, 4)])
        self.assertEqual((x["actual"], x["result"]), (30, "won"))

    def test_summary_units_at_minus_110(self):
        xs = [{"date": "d1", "stat": "pts", "p": 0.6, "result": r} for r in ("won", "won", "lost", "push", "")]
        s = picks.summarize(xs)
        self.assertEqual((s["won"], s["lost"], s["push"], s["pending"]), (2, 1, 1, 1))
        self.assertAlmostEqual(s["units"], round(2 * 100 / 110 - 1, 2))
        self.assertAlmostEqual(s["break_even"], 0.5238, places=4)
        self.assertEqual(s["daily"][0]["cum"], s["units"])

    def test_save_and_load_round_trip(self):
        import tempfile
        made = picks.make_picks([player("a", mu=30)], [], "t")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "picks.csv"
            picks.save(path, made)
            back = picks.load(path)
        self.assertEqual(back[0]["line"], made[0]["line"])
        self.assertEqual(back[0]["result"], "")


if __name__ == "__main__":
    unittest.main()
