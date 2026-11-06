"""Backfill ATP and WTA singles results from ESPN into data/tennis/{tour}_matches.csv.

    python -m scripts.backfill_tennis 2010 2026

One request per tour per month (each returns every tournament active that
month). Safe to rerun: matches are merged by id.
"""
from __future__ import annotations

import calendar
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tennis import espn  # noqa: E402

DATA = ROOT / "data" / "tennis"


def main(first: int, last: int) -> None:
    for tour in espn.TOURS:
        path = DATA / f"{tour}_matches.csv"
        rows = espn.load(path)
        for year in range(first, last + 1):
            got = 0
            for m in range(1, 13):
                end = calendar.monthrange(year, m)[1]
                for attempt in range(3):
                    try:
                        done, _ = espn.parse(espn.fetch(tour, f"{year}{m:02d}01", f"{year}{m:02d}{end}"), tour)
                        break
                    except Exception as e:  # noqa: BLE001
                        print(f"{tour} {year}-{m:02d} failed ({e}); retrying")
                        time.sleep(5 * (attempt + 1))
                else:
                    continue
                rows = espn.merge(rows, done)
                got += len(done)
                time.sleep(1)
            espn.save(path, rows)
            print(f"{tour} {year}: {got} matches (total {len(rows)})", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
