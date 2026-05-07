"""Airport ICAO code → (name, city, country) lookup table.

Fetched from the VRS standing data airports CSV:
  https://vrs-standing-data.adsb.lol/airports.csv.gz

The CSV contains ~34,000 airports with columns:
  Code(0), Name(1), ICAO(2), IATA(3), Location(4),
  CountryISO2(5), Latitude(6), Longitude(7), AltitudeFeet(8)

Caching strategy:
  - First boot: fetch from network, parse, save to disk with ETag.
  - Subsequent boots: send ``If-None-Match`` with cached ETag.
  - Fallback for no ETag on server: file mtime + 7-day TTL safety net.
  - If the fetch fails, an empty dict is returned — the integration
    still works, just without city/country enrichment for
    departure/arrival airports.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
from io import BytesIO
from typing import Final

import requests

from .const import LOGGER

AIRPORTS_URL: Final = "https://vrs-standing-data.adsb.lol/airports.csv.gz"

# Cache file path — set by __init__.py before coordinator import.
# Defaults to None (no file cache, network-only).
CACHE_PATH: str | None = None

# How long to treat a cached file as valid when no ETag is available.
CACHE_TTL: Final = 7 * 24 * 3600  # 7 days in seconds


# ── Cache helpers ──────────────────────────────────────────────────────


def _get_cache_info() -> dict | None:
    """Load cached data and ETag from disk, if the file is fresh.

    Returns ``{"data": lookup_dict, "etag": "…", "fetched_at": ts}``
    or ``None`` if the cache file is missing, invalid, or stale.
    """
    if CACHE_PATH is None:
        LOGGER.debug("Airport cache disabled (CACHE_PATH not set)")
        return None
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        LOGGER.debug("Airport cache file invalid or unreadable — will fetch")
        return None

    # Safety-net TTL when no ETag is present
    fetched_at = info.get("fetched_at", 0)
    age = time.time() - fetched_at
    if age > CACHE_TTL:
        LOGGER.debug(
            "Airport cache stale (%.1f days, limit %.0f days) — will fetch",
            age / 86400,
            CACHE_TTL / 86400,
        )
        return None

    LOGGER.debug(
        "Airport cache hit (ETag=%s, age=%.1fh, %d airports)",
        info.get("etag"),
        age / 3600,
        len(info.get("data", {})),
    )
    return info


def _save_cache(
    data: dict[str, tuple[str, str, str]],
    etag: str | None,
) -> None:
    """Persist *data* and *etag* to disk as JSON."""
    if CACHE_PATH is None:
        return
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "data": _serialize_data(data),
                    "etag": etag,
                    "fetched_at": int(time.time()),
                },
                fh,
            )
    except OSError as exc:
        LOGGER.debug(
            "Failed to write airport cache to %s: %s", CACHE_PATH, exc
        )


def _serialize_data(
    data: dict[str, tuple[str, str, str]],
) -> dict[str, list[str]]:
    """Convert a dict of tuples into a JSON-serialisable dict of lists."""
    return {k: list(v) for k, v in data.items()}


def _deserialize_data(
    data: dict[str, list[str]],
) -> dict[str, tuple[str, str, str]]:
    """Reconstruct the original ``dict[str, tuple[str, str, str]]``."""
    return {k: tuple(v) for k, v in data.items()}


# ── Parsing ────────────────────────────────────────────────────────────


def _parse_response(text: str) -> dict[str, tuple[str, str, str]]:
    """Parse the (decompressed) CSV text into a lookup dict.

    Returns ``{icao: (name, city, country)}`` for each airport with a
    valid ICAO code.
    """
    lookup: dict[str, tuple[str, str, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Manual CSV parse — columns:
        #   Code(0), Name(1), ICAO(2), IATA(3), Location(4),
        #   CountryISO2(5), Latitude(6), Longitude(7), AltitudeFeet(8)
        parts = line.split(",")
        if len(parts) < 9:
            continue

        icao = parts[2].strip()  # ICAO column
        if not icao or icao == "ICAO":
            continue

        name = parts[1].strip()
        location = parts[4].strip()  # Location (city)
        country = parts[5].strip()  # CountryISO2

        lookup[icao] = (name, location, country)

    return lookup


def _decompress(raw: bytes) -> str:
    """Decompress gzip data, or return as-is if already plain text."""
    try:
        return gzip.decompress(raw).decode("utf-8-sig")
    except (OSError, EOFError):
        # Already decompressed or plain text — nothing to do
        return raw.decode("utf-8-sig")


# ── Main fetch ─────────────────────────────────────────────────────────


def _fetch_airport_lookup() -> dict[str, tuple[str, str, str]]:
    """Download and parse the airports CSV into a lookup dict.

    Uses ETag-based conditional requests when a cache is available:
    - 200 with matching ETag → skip re-parse, return cached data
    - 200 with different ETag → new data, parse and cache
    - error → fall back to cached data or empty dict
    """
    # Try to load cached info first
    cache_info = _get_cache_info()
    cached_data = _deserialize_data(cache_info.get("data")) if cache_info else None
    cached_etag = cache_info.get("etag") if cache_info else None

    if cached_etag:
        LOGGER.debug(
            "Airport lookup: cache available (ETag=%s, %d airports), "
            "sending conditional request",
            cached_etag,
            len(cached_data),
        )
    else:
        LOGGER.debug("Airport lookup: no cache — will fetch unconditionally")

    headers: dict[str, str] = {}
    if cached_etag:
        headers["If-None-Match"] = cached_etag

    try:
        resp = requests.get(AIRPORTS_URL, headers=headers, timeout=30, stream=True)

        resp.raise_for_status()

        # Extract ETag from response (strip any surrounding quotes)
        etag = resp.headers.get("ETag", "").strip('"')

        # If server ignores If-None-Match but returns the same ETag,
        # skip the expensive parse + save and just use cached data.
        if cached_etag and etag and etag == cached_etag:
            resp.close()
            LOGGER.debug(
                "Airport data unchanged (ETag=%s), using cached copy "
                "(%d airports)",
                cached_etag,
                len(cached_data),
            )
            return cached_data

        text = _decompress(resp.content)
        lookup = _parse_response(text)

        if etag:
            _save_cache(lookup, etag)
            LOGGER.info(
                "Airport data fetched and cached (ETag=%s, %d airports)",
                etag,
                len(lookup),
            )
        else:
            # Server didn't send ETag — save with marker so we retry later
            _save_cache(lookup, None)
            LOGGER.info(
                "Airport data fetched and cached (no ETag, %d airports)",
                len(lookup),
            )

        return lookup

    except requests.RequestException as exc:
        LOGGER.warning(
            "Failed to fetch airport data from %s: %s", AIRPORTS_URL, exc
        )
        # Fall back to cached data if available
        if cached_data is not None:
            LOGGER.info(
                "Network error — using stale cached airport data "
                "(%d airports)",
                len(cached_data),
            )
            return cached_data
        LOGGER.warning("No cached data available — returning empty lookup")

    return {}


# Module-level lazy initialisation.
# ``__getattr__`` is called by Python when an attribute is not found
# via the normal lookup path, so ``AIRPORT_LOOKUP`` is resolved on
# first access (e.g. when the coordinator imports it) rather than at
# import time.  This gives ``__init__.py`` a chance to set
# ``CACHE_PATH`` before any network call is made.
_AIRPORT_LOOKUP_CACHE: dict[str, tuple[str, str, str]] | None = None


def __getattr__(name: str) -> object:
    """Lazily populate module-level exports on first access."""
    global _AIRPORT_LOOKUP_CACHE
    if name == "AIRPORT_LOOKUP":
        if _AIRPORT_LOOKUP_CACHE is None:
            _AIRPORT_LOOKUP_CACHE = _fetch_airport_lookup()
        return _AIRPORT_LOOKUP_CACHE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
