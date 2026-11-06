"""From point-on-serve chances to set scores and total games, exactly.

Tennis scoring is a Markov chain: the chance of holding serve follows from
the chance of winning a point on serve, a set from holds and tiebreaks, a
match from sets. Given each player's point-on-serve chance (pa for A, pb for
B), `match` returns A's win chance, the set-score distribution, and the full
distributions of total games and of A's game margin (a tiebreak counts as
one game, as books count it).

We don't have serve stats, so `fit` finds the pair that reproduces the
rating model's win probability around the tour's average serve level on
that surface: pa = base + x, pb = base - x. `base` decides how often serve
is held, so it sets how long matches run (more holds, more tiebreaks).

One fixed gap x makes matches too close: on the day, the real gap between
two players varies around what the ratings say, and a mix of gaps gives
more lopsided scores than their average. `match_mix` spreads x over a
normal distribution (sd `sigma`, fitted per tour and surface on past
totals) while keeping the overall win chance at p.
"""
from __future__ import annotations

from functools import lru_cache

from numpy.polynomial.hermite_e import hermegauss

MAX_GAMES = 70  # longest possible best-of-5 count with tiebreaks is 65
_Z, _W = hermegauss(9)
NODES = [(float(z), float(w / _W.sum())) for z, w in zip(_Z, _W)]  # standard normal quadrature


def hold(p: float) -> float:
    """Chance the server wins a game, winning each point with chance p."""
    q = 1 - p
    deuce = p * p / (p * p + q * q)
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * deuce


def tiebreak(pa: float, pb: float, first_to: int = 7) -> float:
    """Chance A wins a tiebreak A serves first. pa: A wins a point on A's serve;
    pb: B wins a point on B's serve. Serve order: A, then B twice, A twice, ..."""
    n = first_to - 1
    win = [[0.0] * (n + 2) for _ in range(n + 2)]  # chance of reaching (a, b)
    win[0][0] = 1.0
    out = 0.0
    for a in range(n + 1):
        for b in range(n + 1):
            pr = win[a][b]
            if not pr:
                continue
            k = a + b
            a_serves = ((k + 1) // 2) % 2 == 0
            pt = pa if a_serves else 1 - pb
            if a == n and b == n:
                # from n-n, points go in pairs with one serve each
                both, lose = pa * (1 - pb), (1 - pa) * pb
                out += pr * both / (both + lose)
                continue
            if a == n:
                out += pr * pt
            else:
                win[a + 1][b] += pr * pt
            if b < n:
                win[a][b + 1] += pr * (1 - pt)
    return out


@lru_cache(maxsize=4096)
def _set(pa: float, pb: float, a_first: bool, tb_to: int) -> tuple:
    """Set outcomes when A serves the first game: ((a_games, b_games, prob), ...)."""
    ha, hb = hold(pa), hold(pb)
    tb_a = tiebreak(pa, pb, tb_to) if a_first else 1 - tiebreak(pb, pa, tb_to)
    # at 6-6 the 13th game's server serves first in the tiebreak: that's whoever served game 1
    reach = {(0, 0): 1.0}
    out = []
    for total in range(12):
        nxt = {}
        for (a, b), pr in reach.items():
            a_serves = (total % 2 == 0) == a_first
            pw = ha if a_serves else 1 - hb
            for na, nb, w in ((a + 1, b, pw), (a, b + 1, 1 - pw)):
                if (na >= 6 or nb >= 6) and abs(na - nb) >= 2:
                    out.append((na, nb, pr * w))
                else:
                    nxt[(na, nb)] = nxt.get((na, nb), 0.0) + pr * w
        reach = nxt
    tie = reach.get((6, 6), 0.0)
    if tie:
        out += [(7, 6, tie * tb_a), (6, 7, tie * (1 - tb_a))]
    return tuple(out)


def match(pa: float, pb: float, best_of: int = 3, final_tb: int = 10) -> dict:
    """A's win chance, set scores (keys like "2-1"), and distributions over total games
    and A's game margin. A serves first half the time. The deciding set ends in a
    first-to-`final_tb` tiebreak at 6-6 (the rule at every Slam since 2022)."""
    need = best_of // 2 + 1
    # state: (sets A, sets B, A serves next game) -> {(total games, margin): prob}
    states = {(0, 0, True):{(0, 0):0.5}, (0, 0, False):{(0, 0):0.5}}
    sets: dict[str, float] = {}
    totals = [0.0] * MAX_GAMES
    margins: dict[int, float] = {}
    for _ in range(best_of):
        nxt: dict = {}
        for (sa, sb, a_first), dist in states.items():
            decider = sa == sb == need - 1
            for ga, gb, p in _set(round(pa, 6), round(pb, 6), a_first, final_tb if decider else 7):
                n = ga + gb
                na, nb = sa + (ga > gb), sb + (gb > ga)
                a_next = a_first == (n % 2 == 0)
                for (t, m), pr in dist.items():
                    key, val = (t + n, m + ga - gb), pr * p
                    if na == need or nb == need:
                        sets[f"{na}-{nb}"] = sets.get(f"{na}-{nb}", 0.0) + val
                        totals[key[0]] += val
                        margins[key[1]] = margins.get(key[1], 0.0) + val
                    else:
                        d = nxt.setdefault((na, nb, a_next), {})
                        d[key] = d.get(key, 0.0) + val
        states = nxt
    win = sum(v for k, v in sets.items() if int(k[0]) == need)
    return {"p":win, "sets":sets, "totals":totals, "margins":margins}


def match_win(pa: float, pb: float, best_of: int = 3, final_tb: int = 10) -> float:
    """Just A's win chance (cheaper than match(): no game counts)."""
    need = best_of // 2 + 1
    probs = {(0, 0, True):0.5, (0, 0, False):0.5}
    win = 0.0
    for _ in range(best_of):
        nxt: dict = {}
        for (sa, sb, a_first), pr in probs.items():
            decider = sa == sb == need - 1
            for ga, gb, p in _set(round(pa, 6), round(pb, 6), a_first, final_tb if decider else 7):
                na, nb = sa + (ga > gb), sb + (gb > ga)
                if na == need:
                    win += pr * p
                elif nb < need:
                    k = (na, nb, a_first == ((ga + gb) % 2 == 0))
                    nxt[k] = nxt.get(k, 0.0) + pr * p
        probs = nxt
    return win


@lru_cache(maxsize=64)
def _win_table(base: float, best_of: int, final_tb: int) -> tuple:
    """A's match win chance at pa = base + x, pb = base - x on a grid of x (increasing in x)."""
    lim = min(base, 1 - base) - 1e-3
    xs = [-lim + 2 * lim * i / 400 for i in range(401)]
    return tuple(xs), tuple(match_win(base + x, base - x, best_of, final_tb) for x in xs)


def fit(p_win: float, base: float, best_of: int = 3, final_tb: int = 10) -> tuple[float, float]:
    """Serve-point chances (pa, pb) = (base + x, base - x) giving A a match win chance of p_win
    (interpolated on a precomputed grid, so it's cheap to call for every match)."""
    xs, ps = _win_table(round(base, 4), best_of, final_tb)
    if p_win <= ps[0]:
        x = xs[0]
    elif p_win >= ps[-1]:
        x = xs[-1]
    else:
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if ps[mid] < p_win else (lo, mid)
        t = (p_win - ps[lo]) / (ps[hi] - ps[lo])
        x = xs[lo] + t * (xs[hi] - xs[lo])
    return base + x, base - x


def _interp(x: float, xs: tuple, ps: tuple) -> float:
    if x <= xs[0]:
        return ps[0]
    if x >= xs[-1]:
        return ps[-1]
    step = xs[1] - xs[0]
    i = min(int((x - xs[0]) / step), len(xs) - 2)
    t = (x - xs[i]) / step
    return ps[i] + t * (ps[i + 1] - ps[i])


def mix_points(p_win: float, base: float, sigma: float, best_of: int = 3, final_tb: int = 10) -> list[tuple]:
    """(weight, pa, pb) quadrature points for gaps x ~ Normal(x0, sigma), with x0 set so the
    mix still gives A a win chance of p_win."""
    xs, ps = _win_table(round(base, 4), best_of, final_tb)
    lim = xs[-1]
    win = lambda x0: sum(w * _interp(x0 + sigma * z, xs, ps) for z, w in NODES)  # noqa: E731
    lo, hi = -lim, lim
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if win(mid) < p_win else (lo, mid)
    x0 = (lo + hi) / 2
    return [(w, base + x, base - x) for z, w in NODES if abs(x := max(min(x0 + sigma * z, lim), -lim)) <= lim]


def match_mix(p_win: float, base: float, sigma: float, best_of: int = 3, final_tb: int = 10) -> dict:
    """match() averaged over the day-to-day spread in the gap; "p" stays p_win."""
    out = {"p":0.0, "sets":{}, "totals":[0.0] * MAX_GAMES, "margins":{}}
    for w, pa, pb in mix_points(p_win, base, sigma, best_of, final_tb):
        m = match(round(pa, 4), round(pb, 4), best_of, final_tb)
        out["p"] += w * m["p"]
        for k, v in m["sets"].items():
            out["sets"][k] = out["sets"].get(k, 0.0) + w * v
        for i, v in enumerate(m["totals"]):
            out["totals"][i] += w * v
        for k, v in m["margins"].items():
            out["margins"][k] = out["margins"].get(k, 0.0) + w * v
    return out


def p_over(dist, line: float) -> tuple[float, float]:
    """(P over, P under) for a line on a distribution given as a list (index = value)
    or a dict {value: prob}. A whole-number line can push."""
    items = enumerate(dist) if isinstance(dist, list) else dist.items()
    over = under = 0.0
    for v, p in items:
        if v > line:
            over += p
        elif v < line:
            under += p
    return over, under
