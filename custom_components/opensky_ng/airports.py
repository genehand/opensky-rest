"""Airport ICAO code → (name, city, country) lookup table.

Fetched from the VRS standing data airports CSV:
  https://vrs-standing-data.adsb.lol/airports.csv.gz

The CSV contains ~34,000 airports with columns:
  Code (ICAO), Name, ICAO, IATA, Location (city), CountryISO2,
  Latitude, Longitude, AltitudeFeet

If the fetch fails, an empty dict is returned — the integration
still works, just without city/country enrichment for departure/arrival airports.
"""

from __future__ import annotations

import gzip
import logging
from io import BytesIO
from typing import Final

import requests

from .const import LOGGER

AIRPORTS_URL: Final = "https://vrs-standing-data.adsb.lol/airports.csv.gz"


def _fetch_airport_lookup() -> dict[str, tuple[str, str, str]]:
    """Download and parse the airports CSV into a lookup dict.

    Returns ``{icao: (name, city, country)}`` for each airport with a
    valid ICAO code.
    """
    lookup: dict[str, tuple[str, str, str]] = {}
    try:
        resp = requests.get(AIRPORTS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.content

        # The source is gzip-compressed; requests may or may not auto-decompress
        # depending on the ``Content-Encoding`` header.  Try gzip first, then
        # fall back to treating it as plain text.
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError):
            # Already decompressed or plain text — nothing to do
            pass

        # utf-8-sig strips the BOM if present
        text = data.decode("utf-8-sig")

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
            if not icao:
                continue

            name = parts[1].strip()
            location = parts[4].strip()  # Location (city)
            country = parts[5].strip()  # CountryISO2

            lookup[icao] = (name, location, country)

    except requests.RequestException as exc:
        LOGGER.debug("Failed to fetch airport data from %s: %s", AIRPORTS_URL, exc)
    except Exception as exc:
        LOGGER.debug("Error parsing airport data from %s: %s", AIRPORTS_URL, exc)

    return lookup


AIRPORT_LOOKUP: Final[dict[str, tuple[str, str, str]]] = _fetch_airport_lookup()
