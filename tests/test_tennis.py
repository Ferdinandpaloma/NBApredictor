import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from tennis import elo, espn, predict, scoring, surfaces
except ImportError:  # numpy not installed
    scoring = None


def comp(cid, name, games, winner=None, tb=None):
    return {"id":cid, "winner":winner, "athlete":{"displayName":name, "flag":{"alt":"Spain"}},
            "linescores":[{"value":g, **({"tiebreak":t} if t else {})} for g, t in zip(games, tb or [None] * len(games))]}


def event(*comps):
    return {"events":[{"id":"9", "date":"2026-05-25T09:00Z", "name":"Roland Garros", "groupings":[
        {"grouping":{"slug":"mens-singles"}, "competitions":list(comps)},
        {"grouping":{"slug":"mens-doubles"}, "competitions":[]}]}]}


def match(cid, state, name, a, b, status_name="STATUS_FINAL", rnd="Round 1"):
    return {"id":cid, "date":"2026-05-26T10:00Z", "round":{"displayName":rnd}, "format":{"regulation":{"periods":5}},
            "status":{"type":{"state":state, "name":status_name}}, "competitors":[a, b]}


@unittest.skipIf(scoring is None, "needs numpy")
class ScoringTests(unittest.TestCase):
    def test_even_players_split_everything(self):
        self.assertAlmostEqual(scoring.hold(0.5), 0.5)
        self.assertAlmostEqual(scoring.tiebreak(0.64, 0.64), 0.5)
        m = scoring.match(0.64, 0.64)
        self.assertAlmostEqual(m["p"], 0.5)
        self.assertAlmostEqual(sum(m["totals"]), 1.0)
        self.assertAlmostEqual(sum(m["sets"].values()), 1.0)
        self.assertAlmostEqual(m["sets"]["2-0"], m["sets"]["0-2"])
        self.assertAlmostEqual(sum(k * v for k, v in m["margins"].items()), 0.0)

    def test_fit_and_mix_keep_the_win_chance(self):
        pa, pb = scoring.fit(0.75, 0.64)
        self.assertAlmostEqual(scoring.match_win(pa, pb), 0.75, places=3)
        mixed = scoring.match_mix(0.75, 0.64, 0.05)
        self.assertAlmostEqual(mixed["p"], 0.75, places=3)
        plain = scoring.match(pa, pb)
        # A spread of gaps makes straight sets likelier and matches shorter.
        self.assertGreater(mixed["sets"]["2-0"], plain["sets"]["2-0"])
        self.assertLess(sum(i * v for i, v in enumerate(mixed["totals"])), sum(i * v for i, v in enumerate(plain["totals"])))

    def test_best_of_five_favours_the_better_player(self):
        pa, pb = scoring.fit(0.7, 0.64)
        self.assertGreater(scoring.match_win(pa, pb, 5), 0.7)

    def test_over_under_and_push(self):
        self.assertEqual(scoring.p_over({20:0.25, 22:0.5, 24:0.25}, 22), (0.25, 0.25))
        self.assertEqual(scoring.p_over([0, 0.5, 0.5], 1.5), (0.5, 0.5))


@unittest.skipIf(scoring is None, "needs numpy")
class DataTests(unittest.TestCase):
    def test_parse_finished_upcoming_and_tbd(self):
        raw = event(
            match("1", "post", "", comp("10", "Carlos Alcaraz", [7, 6], True, [7, None]), comp("11", "Jannik Sinner", [6, 3], False, [4, None])),
            match("2", "post", "", comp("12", "A", [1], True), comp("13", "B", [0], False), status_name="STATUS_RETIRED"),
            match("3", "post", "", comp("14", "C", [], True), comp("15", "D", [], False), status_name="STATUS_CANCELED"),
            match("4", "pre", "", comp("10", "Carlos Alcaraz", []), comp("16", "Casper Ruud", [])),
            match("5", "pre", "", comp("-1", "TBD", []), comp("16", "Casper Ruud", [])))
        done, todo = espn.parse(raw, "atp")
        self.assertEqual([d["match_id"] for d in done], ["1", "2"])
        d = done[0]
        self.assertEqual((d["winner"], d["loser"], d["w_games"], d["l_games"], d["w_tb"]), ("Carlos Alcaraz", "Jannik Sinner", "7 6", "6 3", "7 "))
        self.assertEqual((d["date"], d["status"]), ("2026-05-26", "final"))
        self.assertEqual(done[1]["status"], "retired")
        self.assertEqual([(t["p1"], t["p2"]) for t in todo], [("Carlos Alcaraz", "Casper Ruud")])

    def test_surfaces_and_formats(self):
        self.assertEqual(surfaces.surface("Roland Garros", "2025-05-30"), "clay")
        self.assertEqual(surfaces.surface("Terra Wortmann Open", "2025-06-20"), "grass")
        self.assertEqual(surfaces.surface("ATP Mercedes Cup", "2012-07-10"), "clay")
        self.assertEqual(surfaces.surface("Boss Open", "2025-06-10"), "grass")
        self.assertEqual(surfaces.surface("Rolex Paris Masters", "2026-11-01"), "hard")
        rows = predict.prepare([{"event":"US Open", "date":"2025-09-01", "round":"Round 1"},
                                {"event":"US Open", "date":"2025-08-20", "round":"Qualifying 1st Round"},
                                {"event":"Laver Cup", "date":"2025-09-20", "round":"Day 1"}], "atp")
        self.assertEqual([r["best_of"] for r in rows], [5, 3])
        self.assertEqual(predict.prepare([{"event":"US Open", "date":"2025-09-01", "round":"Round 1"}], "wta")[0]["best_of"], 3)

    def test_elo_moves_toward_the_winner_and_skips_walkovers(self):
        rows = [{"match_id":str(i), "date":f"2025-01-{i + 1:02d}", "status":"final", "surface":"clay",
                 "winner_id":"a", "loser_id":"b"} for i in range(5)]
        rows.append({"match_id":"9", "date":"2025-01-09", "status":"walkover", "surface":"clay", "winner_id":"b", "loser_id":"a"})
        model, out = elo.replay(rows)
        self.assertEqual(len(out), 5)
        self.assertGreater(model.predict("a", "b", "clay"), model.predict("a", "b", "grass"))  # clay rating moved more
        self.assertGreater(model.predict("a", "b", "grass"), 0.5)


if __name__ == "__main__":
    unittest.main()
