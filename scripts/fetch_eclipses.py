"""Regenerate data/lunar_eclipses.txt from NASA's decade tables.

    uv run python scripts/fetch_eclipses.py

Run this once every decade or so -- eclipse predictions are stable centuries
ahead, so unlike the ephemeris this is not an annual chore.
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx

DECADES = (2021, 2031)
SOURCE = "https://eclipse.gsfc.nasa.gov/LEdecade/LEdecade{decade}.html"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "lunar_eclipses.txt"

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}  # fmt: skip

#: date, time, type, saros, umbral magnitude, duration (visibility is optional).
REQUIRED_COLUMNS = 6

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
DATE = re.compile(r"^(\d{4}) ([A-Z][a-z]{2}) (\d{2})$")
DURATION = re.compile(r"(\d{2})h(\d{2})m")


def minutes(text: str) -> list[int]:
    return [int(h) * 60 + int(m) for h, m in DURATION.findall(text)]


def scrape(client: httpx.Client, decade: int) -> list[str]:
    response = client.get(SOURCE.format(decade=decade))
    response.raise_for_status()

    rows: list[str] = []
    for raw in ROW.findall(response.text):
        cells = [
            " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split())
            for cell in CELL.findall(raw)
        ]
        if len(cells) < REQUIRED_COLUMNS:
            continue
        matched = DATE.match(cells[0])
        if not matched:
            continue

        year, month, day = matched.groups()
        kind = cells[2].lower()
        if kind not in {"total", "partial", "penumbral"}:
            raise SystemExit(f"unexpected eclipse type {cells[2]!r} in {decade}s table")

        spans = minutes(cells[5])
        umbral = spans[0] if spans else 0
        totality = spans[1] if len(spans) > 1 else 0

        # NASA rounds to the second and occasionally prints ":60" rather than
        # carrying into the next minute (2038 Dec 11 17:44:60). Adding the
        # seconds as a delta normalises that instead of emitting an invalid time.
        hour, minute, second = (int(part) for part in cells[1].split(":"))
        greatest = datetime(int(year), MONTHS[month], int(day), hour, minute) + timedelta(
            seconds=second
        )
        rows.append(f"{greatest.isoformat():<22}{kind:<12}{umbral:<8}{totality}")
    return rows


def main() -> int:
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        rows = [row for decade in DECADES for row in scrape(client, decade)]

    if not rows:
        raise SystemExit("scraped no eclipses -- the table layout probably changed")

    sources = "\n".join(f"#   {SOURCE.format(decade=d)}" for d in DECADES)
    header = f"""\
# Lunar eclipses, {rows[0][:4]}-{rows[-1][:4]}.
#
# Source: NASA/GSFC, Five Millennium Canon of Lunar Eclipses (Fred Espenak).
{sources}
# Regenerate with: uv run python scripts/fetch_eclipses.py
#
# Times are greatest eclipse in TD. TD - UT is about 70 s this century, three
# orders of magnitude below the one-hour resolution this tool works at.
#
# Durations are minutes. "umbral" is the partial phase (first to last umbral
# contact) and is 0 for penumbral eclipses, whose duration the decade tables
# do not publish. "totality" is 0 unless the eclipse is total.
#
# greatest_td         type        umbral  totality
"""
    OUTPUT.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} eclipses to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
