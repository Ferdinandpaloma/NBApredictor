import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nbaelo.elo import Game  # noqa: E402
from nbaelo.players import merge_logs, parse_boxscore, parse_minutes  # noqa: E402

try:
    import numpy as np
    from nbaelo import props
except ImportError:  # pandas/numpy/scipy/sklearn not installed
    props = None


def player(pid, name, mins, pts, played="1"):
    return {"personId": pid, "name": name, "played": played,
            "statistics": {"minutes": mins, "points": pts, "reboundsTotal": 5, "assists": 3}}


def fake_boxscore():
    return {"game": {
        "homeTeam": {"teamTricode": "LAL", "players": [
            player(1, "Starter", "PT34M30.00S", 28), player(2, "DNP", "", 0, played="0")]},
        "awayTeam": {"teamTricode": "BOS", "players": [player(3, "Bench", "PT12M00.00S", 6)]},
    }}


def log_rows(n_games=30, teams=("AAA", "BBB")):
    """A synthetic two-team league. Player 1 scores 10 + game number."""
    rows = []
    for k in range(n_games):
        date = f"2025-{11 + k // 28:02d}-{k % 28 + 1:02d}"
        gid = f"00225{k:05d}"
        home, away = teams if k % 2 == 0 else teams[::-1]
        for team, opp in ((home, away), (away, home)):
            for j in range(3):
                pid = f"{team}{j}"
                pts = 10 + k if pid == "AAA0" else 8 + j
                rows.append({
                    "game_id": gid, "date": date, "season": "2025-26", "player_id": pid,
                    "player": pid, "team": team, "opp": opp, "home": int(team == home),
                    "min": 30.0 - j * 8, "pts": pts, "reb": 4, "oreb": 1, "dreb": 3, "ast": 2,
                    "stl": 1, "blk": 0, "tov": 1, "fgm": 4, "fga": 9, "fg3m": 1, "fg3a": 3,
                    "ftm": 1, "fta": 2, "pf": 2, "plus_minus": 0,
                })
    return rows


class PlayerDataTests(unittest.TestCase):
    def test_parse_minutes(self):
        self.assertAlmostEqual(parse_minutes("PT34M12.00S"), 34.2)
        self.assertAlmostEqual(parse_minutes("PT00M30.00S"), 0.5)
        self.assertAlmostEqual(parse_minutes("21:30"), 21.5)
        self.assertEqual(parse_minutes(27), 27.0)
        self.assertEqual(parse_minutes(""), 0.0)

    def test_parse_boxscore_skips_dnp(self):
        g = Game("0022600001", "2026-10-21", "2026-27", "LAL", "BOS")
        rows = parse_boxscore(fake_boxscore(), g)
        self.assertEqual([r["player"] for r in rows], ["Starter", "Bench"])
        starter, bench = rows
        self.assertEqual((starter["team"], starter["opp"], starter["home"]), ("LAL", "BOS", 1))
        self.assertEqual((bench["team"], bench["opp"], bench["home"]), ("BOS", "LAL", 0))
        self.assertEqual(starter["pts"], 28)
        self.assertAlmostEqual(starter["min"], 34.5)

    def test_merge_logs_newest_wins(self):
        a = {"game_id": "1", "date": "2025-01-01", "team": "X", "player_id": "p", "pts": 1}
        b = dict(a, pts=9)
        self.assertEqual(merge_logs([a], [b]), [b])


@unittest.skipIf(props is None, "needs pandas, numpy, scipy and scikit-learn")
class PropsTests(unittest.TestCase):
    def test_p_over_matches_poisson_when_alpha_tiny(self):
        # Poisson(2): P(X > 2.5) = 1 - e^-2 (1 + 2 + 2)
        expected = 1 - math.exp(-2) * 5
        self.assertAlmostEqual(float(props.p_over("pts", 2.0, 1e-7, 2.5)), expected, places=4)

    def test_p_over_whole_line_excludes_push(self):
        over_3 = float(props.p_over("pts", 2.0, 1e-7, 3))
        over_35 = float(props.p_over("pts", 2.0, 1e-7, 3.5))
        self.assertAlmostEqual(over_3, over_35)

    def test_dispersion_grows_with_noise(self):
        rng = np.random.default_rng(0)
        mu = rng.uniform(5, 30, 5000)
        calm = mu + rng.normal(0, 2, mu.size)
        wild = mu + rng.normal(0, 8, mu.size)
        a = np.mean(props.fit_dispersion("pts", mu, calm)["param"])
        b = np.mean(props.fit_dispersion("pts", mu, wild)["param"])
        self.assertLess(a, b)

    def test_features_use_only_earlier_games(self):
        rows = log_rows()
        df = props.build_features(props.to_frame(rows), {})
        # Change the last game's stats: no feature on that row may move.
        changed = [dict(r, pts=999, min=48.0) if r["game_id"] == rows[-1]["game_id"] else r for r in rows]
        df2 = props.build_features(props.to_frame(changed), {})
        last = df["game_id"] == rows[-1]["game_id"]
        cols = sorted({c for t in props.TARGETS for c in props.feature_cols(t)})
        a, b = df.loc[last, cols], df2.loc[last, cols]
        self.assertTrue(a.equals(b), "features leak the game's own result")

    def test_ewm_tracks_recent_form(self):
        df = props.build_features(props.to_frame(log_rows()), {})
        p = df[df["player_id"] == "AAA0"].iloc[-1]
        # Scores rise by one each game, so recent form beats the season average.
        self.assertGreater(p["pts_e5"], p["pts_sea"])
        self.assertAlmostEqual(p["pts_l10"], sum(10 + k for k in range(19, 29)) / 10)  # games 19-28

    def test_candidates_and_future_rows(self):
        rows = log_rows()
        base = props.to_frame(rows)
        nxt = [{"game_id": "0022599999", "date": "2025-12-31", "season": "2025-26",
                "team": "AAA", "opp": "BBB", "home": 1}]
        cands = props.candidates(base, nxt)
        # AAA2 averages 14 minutes (>= 10), so all three are rotation players.
        self.assertEqual(sorted(c["player_id"] for c in cands), ["AAA0", "AAA1", "AAA2"])
        self.assertTrue(all(not c["likely_out"] for c in cands))
        df = props.build_features(props.to_frame(rows + cands), {"0022599999": -4.0})
        fut = df[df["future"]]
        self.assertEqual(len(fut), 3)
        self.assertTrue((fut["spread"] == -4.0).all())
        self.assertFalse(fut["pts_e5"].isna().any())

    def test_candidates_flag_long_absence(self):
        rows = [r for r in log_rows() if not (r["player_id"] == "AAA0" and r["game_id"] >= "0022500026")]
        cands = props.candidates(props.to_frame(rows), [
            {"game_id": "x", "date": "2025-12-31", "season": "2025-26", "team": "AAA", "opp": "BBB", "home": 1}])
        out = {c["player_id"]: c["likely_out"] for c in cands}
        self.assertTrue(out["AAA0"])
        self.assertFalse(out["AAA1"])

    def test_missing_tonight_both_sides(self):
        rows = log_rows()
        nxt = [{"game_id": "x", "date": "2025-12-31", "season": "2025-26", "team": t, "opp": o, "home": h}
               for t, o, h in (("AAA", "BBB", 1), ("BBB", "AAA", 0))]
        cands = props.candidates(props.to_frame(rows), nxt)
        df = props.build_features(props.to_frame(rows + cands), {})
        fut = df[df["future"]].set_index("player_id")
        self.assertTrue((fut["out_pts"] == 0).all() and (fut["opp_out_pts"] == 0).all())
        # AAA0 (30 minutes a game) is ruled out tonight.
        from nbaelo import injuries
        for c in cands:
            c["player"] = {"AAA0": "Star Guard", "BBB0": "Other Guard"}.get(c["player_id"], c["player_id"])
        n = injuries.mark_out(cands, [{"key": "star guard", "status": "Out"},
                                      {"key": "other guard", "status": "Day-To-Day"}])
        self.assertEqual(n, 1)
        df = props.build_features(props.to_frame(rows + cands), {})
        fut = df[df["future"]].set_index("player_id")
        self.assertGreater(fut.at["AAA1", "out_pts"], 20)    # teammates know he's missing
        self.assertEqual(fut.at["AAA1", "out_n"], 1)
        self.assertGreater(fut.at["BBB0", "opp_out_pts"], 20)  # and so do opponents
        self.assertEqual(fut.at["BBB0", "out_pts"], 0)
        # In past games, "missing" comes from the box score: drop AAA0 from the last one.
        past = [r for r in rows if not (r["player_id"] == "AAA0" and r["game_id"] == rows[-1]["game_id"])]
        df = props.build_features(props.to_frame(past), {})
        last = df[df["game_id"] == rows[-1]["game_id"]].set_index("player_id")
        self.assertEqual(last.at["AAA1", "out_n"], 1)
        self.assertEqual(last.at["BBB0", "opp_out_n"], 1)


if __name__ == "__main__":
    unittest.main()


class InjuryTests(unittest.TestCase):
    def test_name_key_and_apply(self):
        from nbaelo import injuries
        self.assertEqual(injuries.name_key("Nikola Jokić"), injuries.name_key("Nikola Jokic"))
        self.assertEqual(injuries.name_key("Jaren Jackson Jr."), "jaren jackson")
        raw = {"injuries": [{"injuries": [
            {"status": "Out", "shortComment": "Foot.", "date": "2026-10-19T19:38Z",
             "athlete": {"displayName": "Nikola Jokic", "team": {"abbreviation": "GS"}},
             "details": {"side": "Left", "type": "Foot", "returnDate": "2026-11-20"}},
            {"status": "Day-To-Day", "athlete": {"displayName": "A Guard", "team": {"abbreviation": "BOS"}}}]}]}
        rep = injuries.parse(raw)
        self.assertEqual(rep[0]["team"], "GSW")
        self.assertEqual(rep[0]["injury"], "Left Foot")
        players = [{"name": "Nikola Jokić", "likely_out": False}, {"name": "A Guard", "likely_out": False}, {"name": "Other"}]
        self.assertEqual(injuries.apply(players, rep), 2)
        self.assertTrue(players[0]["likely_out"])
        self.assertFalse(players[1]["likely_out"])  # day-to-day isn't ruled out
        self.assertEqual(players[1]["injury"]["status"], "Day-To-Day")
        self.assertNotIn("injury", players[2])


class WireTests(unittest.TestCase):
    def test_parse(self):
        from nbaelo import wire
        news = wire.parse_news({"articles": [
            {"id": "1", "type": "Story", "headline": "H", "links": {"web": {"href": "https://x"}},
             "images": [{"url": "https://img"}], "categories": [{"type": "team", "description": "Utah Jazz"}]},
            {"headline": "no link"}]})
        self.assertEqual(len(news), 1)
        self.assertEqual((news[0]["image"], news[0]["teams"]), ("https://img", ["Utah Jazz"]))
        tx = wire.parse_transactions({"transactions": [{"date": "d", "team": {"abbreviation": "UTAH"}, "description": "Signed X."}]})
        self.assertEqual(tx, [{"date": "d", "team": "UTA", "text": "Signed X."}])
