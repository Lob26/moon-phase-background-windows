"""Discover the next year's SVS collection id and stage the rollover.

    uv run python scripts/rollover_year.py [YEAR]

Scrapes NASA's Moon Phase and Libration gallery for the year's visualisation
id, verifies that the id actually serves frames and an ephemeris, then patches
SVS_COLLECTIONS and caches the ephemeris table.

Nothing here is trusted blindly: a scraped id is a guess until the frame URL it
implies returns 200, and the result lands in a pull request for a human to look
at rather than on main. See .github/workflows/year-rollover.yml.

Exits 0 whether or not there was work to do -- read the ``changed`` output for
that -- and non-zero only when discovery genuinely failed.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonback.config import SVS_COLLECTIONS, SVS_FRAME_BASE  # noqa: E402

GALLERY = "https://svs.gsfc.nasa.gov/gallery/moonphase/"
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "moonback" / "config.py"

#: Deliberately anchored to the exact link text. "South Up" is a different
#: visualisation with a different id, and matching it would be silently wrong.
LINK = re.compile(
    r'href="[^"]*?/(\d{4,5})/?"[^>]*>\s*Moon Phase and Libration,\s*(\d{4})\s*<', re.I
)
COLLECTIONS_BLOCK = re.compile(
    r"(SVS_COLLECTIONS: dict\[int, int\] = \{)(.*?)(\n\})", re.S
)


def emit(name: str, value: str) -> None:
    """Publish a step output when running under GitHub Actions."""
    print(f"{name}={value}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def discover(client: httpx.Client, year: int) -> int:
    response = client.get(GALLERY)
    response.raise_for_status()

    found = {int(y): int(vid) for vid, y in LINK.findall(response.text)}
    if not found:
        raise SystemExit("scraped no visualisations -- the gallery layout probably changed")
    if year not in found:
        raise SystemExit(f"the gallery has no 'Moon Phase and Libration, {year}' entry yet")
    return found[year]


def collection_url(collection: int) -> str:
    group = f"a{collection // 100 * 100:06d}"
    return f"{SVS_FRAME_BASE}/{group}/a{collection:06d}"


def verify(client: httpx.Client, collection: int, year: int) -> str:
    """Confirm the scraped id serves what we expect, and return the mooninfo URL."""
    base = collection_url(collection)
    frame = f"{base}/frames/3840x2160_16x9_30p/plain/moon.0001.tif"
    mooninfo = f"{base}/mooninfo_{year}.txt"

    for label, url in (("first frame", frame), ("ephemeris", mooninfo)):
        status = client.head(url).status_code
        if status != httpx.codes.OK:
            raise SystemExit(
                f"id {collection} does not serve a {label} for {year}: {url} -> {status}"
            )
    return mooninfo


def patch_config(year: int, collection: int) -> None:
    source = CONFIG_PATH.read_text(encoding="utf-8")
    block = COLLECTIONS_BLOCK.search(source)
    if block is None:
        raise SystemExit(f"could not find SVS_COLLECTIONS in {CONFIG_PATH}")

    entries = dict(SVS_COLLECTIONS) | {year: collection}
    rendered = "".join(f"\n    {y}: {c}," for y, c in sorted(entries.items()))
    CONFIG_PATH.write_text(
        source[: block.start()] + block.group(1) + rendered + block.group(3) + source[block.end():],
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    year = int(argv[0]) if argv else datetime.now(UTC).year

    if year in SVS_COLLECTIONS:
        print(f"{year} is already mapped to {SVS_COLLECTIONS[year]}; nothing to do")
        emit("changed", "false")
        return 0

    with httpx.Client(timeout=45, follow_redirects=True) as client:
        collection = discover(client, year)
        print(f"gallery lists {year} as SVS id {collection}")
        mooninfo_url = verify(client, collection, year)

        table = client.get(mooninfo_url)
        table.raise_for_status()
        (REPO_ROOT / "data" / f"mooninfo_{year}.txt").write_bytes(table.content)

    patch_config(year, collection)

    print(f"staged {year} -> {collection} and cached mooninfo_{year}.txt")
    emit("changed", "true")
    emit("year", str(year))
    emit("collection", str(collection))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
