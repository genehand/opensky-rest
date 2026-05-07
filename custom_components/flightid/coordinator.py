"""DataUpdateCoordinator for the flightID integration."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from opensky_api import OpenSkyApi, TokenManager

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import airports
from .const import (
    AIRLINE_LOOKUP,
    ATTR_AIRCRAFT,
    ATTR_AIRCRAFT_IMAGE_URL,
    ATTR_AIRLINE,
    ATTR_ALTITUDE,
    ATTR_ALTITUDE_FT,
    ATTR_ARRIVAL_AIRPORT,
    ATTR_ARRIVAL_CITY,
    ATTR_ARRIVAL_COUNTRY,
    ATTR_BARO_ALTITUDE,
    ATTR_CALLSIGN,
    ATTR_CATEGORY,
    ATTR_CATEGORY_NAME,
    ATTR_COUNT,
    ATTR_DEPARTURE_AIRPORT,
    ATTR_DEPARTURE_CITY,
    ATTR_DEPARTURE_COUNTRY,
    ATTR_GEO_ALTITUDE,
    ATTR_ICAO24,
    ATTR_LAST_CONTACT,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_ON_GROUND,
    ATTR_ORIGIN_COUNTRY,
    ATTR_POSITION_SOURCE,
    ATTR_POSITION_SOURCE_NAME,
    ATTR_SENSORS,
    ATTR_SPEED_KTS,
    ATTR_SPI,
    ATTR_SQUAWK,
    ATTR_TIME_POSITION,
    ATTR_TRUE_TRACK,
    ATTR_VELOCITY,
    ATTR_VERTICAL_RATE,
    CATEGORY_MAP,
    CONF_ALTITUDE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    DEFAULT_ALTITUDE,
    DOMAIN,
    EVENT_FLIGHTID_ENTRY,
    EVENT_FLIGHTID_EXIT,
    LOGGER,
    POSITION_SOURCE_MAP,
)

FLIGHT_CACHE_TTL: timedelta = timedelta(hours=1)
AIRCRAFT_METADATA_CACHE_TTL: timedelta = timedelta(hours=24)

PLANESPOTTERS_API: str = "https://api.planespotters.net/pub/photos/hex"
ROUTE_API: str = "https://vrs-standing-data.adsb.lol/routes"

UPDATE_INTERVAL_AUTH: timedelta = timedelta(seconds=30)
UPDATE_INTERVAL_ANON: timedelta = timedelta(minutes=5)


def _extract_airline(callsign: str | None) -> str | None:
    """Extract the airline name from a callsign using the lookup table.

    Callsigns typically start with 3 letters identifying the airline,
    followed by the flight number (e.g. 'UAL123').
    """
    if not callsign:
        return None
    # Strip whitespace/padding and get first 3 characters
    prefix = callsign.strip()[:3].upper()
    return AIRLINE_LOOKUP.get(prefix)


def _airport_city(icao_code: str | None) -> str | None:
    """Look up the city name for an ICAO airport code."""
    if not icao_code:
        return None
    info = airports.AIRPORT_LOOKUP.get(icao_code.upper())
    if info is None:
        LOGGER.debug("Airport code %s not found in lookup table", icao_code)
    return info[1] if info else None


def _airport_country(icao_code: str | None) -> str | None:
    """Look up the country name for an ICAO airport code."""
    if not icao_code:
        return None
    info = airports.AIRPORT_LOOKUP.get(icao_code.upper())
    return info[2] if info else None


def _convert_aircraft_state(
    state: Any,
    flight_cache: dict[str, dict] | None = None,
    aircraft_metadata_cache: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Convert an OpenSky StateVector to a structured dict with enriched data."""
    aircraft: dict[str, Any] = {
        ATTR_ICAO24: state.icao24,
        ATTR_CALLSIGN: state.callsign.strip() if state.callsign else None,
        ATTR_AIRLINE: _extract_airline(state.callsign),
        ATTR_ORIGIN_COUNTRY: state.origin_country,
        ATTR_TIME_POSITION: state.time_position,
        ATTR_LAST_CONTACT: state.last_contact,
        ATTR_LONGITUDE: state.longitude,
        ATTR_LATITUDE: state.latitude,
        ATTR_BARO_ALTITUDE: state.baro_altitude,
        ATTR_GEO_ALTITUDE: state.geo_altitude,
        ATTR_ON_GROUND: state.on_ground,
        ATTR_VELOCITY: state.velocity,
        ATTR_TRUE_TRACK: state.true_track,
        ATTR_VERTICAL_RATE: state.vertical_rate,
        ATTR_SENSORS: state.sensors,
        ATTR_SQUAWK: state.squawk,
        ATTR_SPI: state.spi,
        ATTR_POSITION_SOURCE: state.position_source,
        ATTR_CATEGORY: state.category,
        ATTR_CATEGORY_NAME: CATEGORY_MAP.get(
            state.category, "Unknown"
        ),
        ATTR_POSITION_SOURCE_NAME: POSITION_SOURCE_MAP.get(
            state.position_source, "Unknown"
        ),
    }

    # Look up image URL from aircraft metadata cache
    if aircraft_metadata_cache:
        cached = aircraft_metadata_cache.get(state.icao24)
        if cached:
            aircraft[ATTR_AIRCRAFT_IMAGE_URL] = cached.get(ATTR_AIRCRAFT_IMAGE_URL)

    # Compute derived values
    if state.baro_altitude is not None:
        aircraft[ATTR_ALTITUDE] = state.baro_altitude
        aircraft[ATTR_ALTITUDE_FT] = round(state.baro_altitude * 3.28084, 1)
    elif state.geo_altitude is not None:
        aircraft[ATTR_ALTITUDE] = state.geo_altitude
        aircraft[ATTR_ALTITUDE_FT] = round(state.geo_altitude * 3.28084, 1)

    if state.velocity is not None:
        aircraft[ATTR_SPEED_KTS] = round(state.velocity * 1.94384, 1)

    # Look up departure/arrival from flight cache
    if flight_cache and state.callsign:
        cs = state.callsign.strip()
        cached = flight_cache.get(cs)
        if cached:
            aircraft[ATTR_DEPARTURE_AIRPORT] = cached.get(ATTR_DEPARTURE_AIRPORT)
            aircraft[ATTR_DEPARTURE_CITY] = cached.get(ATTR_DEPARTURE_CITY)
            aircraft[ATTR_DEPARTURE_COUNTRY] = cached.get(ATTR_DEPARTURE_COUNTRY)
            aircraft[ATTR_ARRIVAL_AIRPORT] = cached.get(ATTR_ARRIVAL_AIRPORT)
            aircraft[ATTR_ARRIVAL_CITY] = cached.get(ATTR_ARRIVAL_CITY)
            aircraft[ATTR_ARRIVAL_COUNTRY] = cached.get(ATTR_ARRIVAL_COUNTRY)
        else:
            LOGGER.debug(
                "No route cache for %s (callsign=%s) — "
                "will be populated by background enrichment",
                state.icao24,
                cs,
            )

    return aircraft


def _fetch_route_data(callsign: str) -> dict[str, Any] | None:
    """Fetch route data (departure/arrival airports) from VRS standing data.

    Calls ``https://vrs-standing-data.adsb.lol/routes/{prefix}/{callsign}.json``
    where ``prefix`` is the first 2 characters of the callsign.
    Returns a dict with departure/arrival airport codes, city names, and
    country codes on success, or None on error / not found.
    """
    prefix = callsign.strip()[:2].upper()
    url = f"{ROUTE_API}/{prefix}/{callsign.strip()}.json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        airports = data.get("_airports")
        if not airports or not isinstance(airports, list) or len(airports) < 2:
            return None
        dep = airports[0].get("icao")
        arr = airports[-1].get("icao")
        return {
            ATTR_DEPARTURE_AIRPORT: dep,
            ATTR_DEPARTURE_CITY: _airport_city(dep),
            ATTR_DEPARTURE_COUNTRY: _airport_country(dep),
            ATTR_ARRIVAL_AIRPORT: arr,
            ATTR_ARRIVAL_CITY: _airport_city(arr),
            ATTR_ARRIVAL_COUNTRY: _airport_country(arr),
        }
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        LOGGER.debug("Route lookup failed for %s: %s", callsign, exc)
        return None


class FlightIdDataUpdateCoordinator(
    DataUpdateCoordinator[dict[str, Any]]
):
    """Coordinator for fetching flight tracking data.

    Wraps the synchronous ``opensky_api.OpenSkyApi`` in an executor to
    keep the event loop responsive.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self._api: OpenSkyApi | None = None
        self._previously_tracked: set[str] | None = None
        self._bounding_box: tuple[float, float, float, float] | None = None
        self._is_authenticated: bool = False
        self._flight_cache: dict[str, dict[str, Any]] = {}
        self._aircraft_metadata_cache: dict[str, dict[str, Any]] = {}
        self.fetching_enabled: bool = True

        # Determine update interval based on authentication
        self._client_id = config_entry.options.get(CONF_CLIENT_ID)
        self._client_secret = config_entry.options.get(CONF_CLIENT_SECRET)

        if self._client_id and self._client_secret:
            token_manager = TokenManager(
                client_id=self._client_id,
                client_secret=self._client_secret,
            )
            self._api = OpenSkyApi(token_manager=token_manager)
            self._is_authenticated = True
            update_interval = UPDATE_INTERVAL_AUTH
        else:
            self._api = OpenSkyApi()
            update_interval = UPDATE_INTERVAL_ANON

        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

        # Build the bounding box
        self._update_bounding_box(config_entry)

    def _should_fetch_flight(self, callsign: str, now: int) -> bool:
        """Check whether route data for this callsign should be refreshed."""
        cached = self._flight_cache.get(callsign)
        if cached is None:
            return True
        last = cached.get("last_updated", 0)
        return (now - last) > FLIGHT_CACHE_TTL.total_seconds()

    def _should_fetch_metadata(self, icao24: str, now: int) -> bool:
        """Check whether aircraft metadata for this ICAO24 should be refreshed."""
        cached = self._aircraft_metadata_cache.get(icao24)
        if cached is None:
            return True
        last = cached.get("last_updated", 0)
        return (now - last) > AIRCRAFT_METADATA_CACHE_TTL.total_seconds()

    @staticmethod
    def _fetch_aircraft_image(icao24: str) -> str | None:
        """Fetch the first aircraft photo URL from Planespotters.net.

        Calls ``https://api.planespotters.net/pub/photos/hex/{icao24}`` and
        returns the ``thumbnail_large.src`` of the first photo, or None
        if no photos are found or on error.
        """
        try:
            resp = requests.get(
                f"{PLANESPOTTERS_API}/{icao24}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            photos = data.get("photos")
            if not photos or not isinstance(photos, list) or len(photos) == 0:
                return None
            first = photos[0]
            thumbnail = first.get("thumbnail_large", {})
            return thumbnail.get("src")
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            LOGGER.debug("Image lookup failed for %s: %s", icao24, exc)
            return None

    async def _async_enrich_aircraft_metadata(
        self, aircraft_list: list[dict[str, Any]]
    ) -> None:
        """Background task: fetch aircraft photo URLs for tracked aircraft.

        Queries ``_fetch_aircraft_image`` for each unique ICAO24 whose
        cache is stale and populates ``self._aircraft_metadata_cache``.
        """
        now = int(datetime.now(timezone.utc).timestamp())
        icao24s_to_fetch: set[str] = set()

        for ac in aircraft_list:
            icao24 = ac.get(ATTR_ICAO24)
            if icao24 and self._should_fetch_metadata(icao24, now):
                icao24s_to_fetch.add(icao24)

        if not icao24s_to_fetch:
            return

        # Use a stable list so zip() ordering is consistent across two iterations
        icao24_list = sorted(icao24s_to_fetch)

        LOGGER.debug(
            "Fetching aircraft images for %d aircraft: %s",
            len(icao24_list),
            ", ".join(icao24_list),
        )

        tasks = [
            self.hass.async_add_executor_job(
                self._fetch_aircraft_image, icao24
            )
            for icao24 in icao24_list
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for icao24, result in zip(icao24_list, results):
            if isinstance(result, Exception):
                LOGGER.debug("Image lookup failed for %s: %s", icao24, result)
                continue

            image_url = None if result is None else result

            if image_url:
                LOGGER.debug(
                    "Aircraft %s: image=%s",
                    icao24,
                    image_url,
                )
            else:
                LOGGER.debug(
                    "No image found for %s", icao24
                )

            # Merge into existing cache entry to preserve any registration field
            if icao24 not in self._aircraft_metadata_cache:
                self._aircraft_metadata_cache[icao24] = {}
            self._aircraft_metadata_cache[icao24][ATTR_AIRCRAFT_IMAGE_URL] = image_url
            self._aircraft_metadata_cache[icao24]["last_updated"] = now

            # Update aircraft dict in-place so data propagates immediately
            for ac in aircraft_list:
                if ac.get(ATTR_ICAO24) == icao24:
                    ac[ATTR_AIRCRAFT_IMAGE_URL] = image_url
                    break

        # Notify entities so they re-read the updated attributes
        self.async_update_listeners()

    async def _async_enrich_routes(
        self, aircraft_list: list[dict[str, Any]]
    ) -> None:
        """Background task: fetch route data for tracked aircraft.

        Queries the VRS standing data API for each unique callsign whose
        cache is stale and populates ``self._flight_cache``.
        """
        now = int(datetime.now(timezone.utc).timestamp())
        callsigns_to_fetch: set[str] = set()

        for ac in aircraft_list:
            cs = ac.get(ATTR_CALLSIGN)
            if cs and self._should_fetch_flight(cs, now):
                callsigns_to_fetch.add(cs)

        if not callsigns_to_fetch:
            return

        LOGGER.debug(
            "Fetching route data for %d aircraft: %s",
            len(callsigns_to_fetch),
            ", ".join(sorted(callsigns_to_fetch)),
        )

        tasks = [
            self.hass.async_add_executor_job(
                _fetch_route_data, cs
            )
            for cs in callsigns_to_fetch
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for callsign, result in zip(callsigns_to_fetch, results):
            if isinstance(result, Exception):
                LOGGER.debug("Route lookup failed for %s: %s", callsign, result)
                continue
            if not result:
                LOGGER.debug("No route data returned for %s", callsign)
                # Still cache with Nones so we don't retry every cycle
                self._flight_cache[callsign] = {
                    ATTR_DEPARTURE_AIRPORT: None,
                    ATTR_DEPARTURE_CITY: None,
                    ATTR_DEPARTURE_COUNTRY: None,
                    ATTR_ARRIVAL_AIRPORT: None,
                    ATTR_ARRIVAL_CITY: None,
                    ATTR_ARRIVAL_COUNTRY: None,
                    "last_updated": now,
                }
                # Clear any stale city data in the aircraft dict in-place
                for ac in aircraft_list:
                    if ac.get(ATTR_CALLSIGN) == callsign:
                        ac[ATTR_DEPARTURE_AIRPORT] = None
                        ac[ATTR_DEPARTURE_CITY] = None
                        ac[ATTR_DEPARTURE_COUNTRY] = None
                        ac[ATTR_ARRIVAL_AIRPORT] = None
                        ac[ATTR_ARRIVAL_CITY] = None
                        ac[ATTR_ARRIVAL_COUNTRY] = None
                        break
                continue

            LOGGER.debug(
                "Route enrichment for %s: dep=%s (%s, %s) arr=%s (%s, %s)",
                callsign,
                result[ATTR_DEPARTURE_AIRPORT],
                result[ATTR_DEPARTURE_CITY],
                result[ATTR_DEPARTURE_COUNTRY],
                result[ATTR_ARRIVAL_AIRPORT],
                result[ATTR_ARRIVAL_CITY],
                result[ATTR_ARRIVAL_COUNTRY],
            )

            self._flight_cache[callsign] = {
                ATTR_DEPARTURE_AIRPORT: result[ATTR_DEPARTURE_AIRPORT],
                ATTR_DEPARTURE_CITY: result[ATTR_DEPARTURE_CITY],
                ATTR_DEPARTURE_COUNTRY: result[ATTR_DEPARTURE_COUNTRY],
                ATTR_ARRIVAL_AIRPORT: result[ATTR_ARRIVAL_AIRPORT],
                ATTR_ARRIVAL_CITY: result[ATTR_ARRIVAL_CITY],
                ATTR_ARRIVAL_COUNTRY: result[ATTR_ARRIVAL_COUNTRY],
                "last_updated": now,
            }

            # Update aircraft dict in-place so data propagates immediately
            for ac in aircraft_list:
                if ac.get(ATTR_CALLSIGN) == callsign:
                    ac[ATTR_DEPARTURE_AIRPORT] = result[ATTR_DEPARTURE_AIRPORT]
                    ac[ATTR_DEPARTURE_CITY] = result[ATTR_DEPARTURE_CITY]
                    ac[ATTR_DEPARTURE_COUNTRY] = result[ATTR_DEPARTURE_COUNTRY]
                    ac[ATTR_ARRIVAL_AIRPORT] = result[ATTR_ARRIVAL_AIRPORT]
                    ac[ATTR_ARRIVAL_CITY] = result[ATTR_ARRIVAL_CITY]
                    ac[ATTR_ARRIVAL_COUNTRY] = result[ATTR_ARRIVAL_COUNTRY]
                    break

        # Notify entities so they re-read the updated attributes
        self.async_update_listeners()

    def _update_bounding_box(self, config_entry: ConfigEntry) -> None:
        """Compute the bounding box from config lat/lon/radius.

        The opensky-api library expects bbox as
        (min_latitude, max_latitude, min_longitude, max_longitude).
        """
        latitude = config_entry.data[CONF_LATITUDE]
        longitude = config_entry.data[CONF_LONGITUDE]
        radius = config_entry.options.get(CONF_RADIUS, 100)

        # Approximate: 1° latitude ≈ 111km, 1° longitude ≈ 111*cos(lat) km
        lat_delta = radius / 111_000
        cos_lat = abs(math.cos(math.radians(latitude))) or 1
        lon_delta = radius / (111_000 * cos_lat)

        self._bounding_box = (
            latitude - lat_delta,  # min_lat
            latitude + lat_delta,  # max_lat
            longitude - lon_delta,  # min_lon
            longitude + lon_delta,  # max_lon
        )

    def _get_altitude_filter(self) -> float:
        """Get the altitude filter from options."""
        return self.config_entry.options.get(CONF_ALTITUDE, DEFAULT_ALTITUDE)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch state vectors from OpenSky and return structured data."""
        if not self.fetching_enabled:
            LOGGER.debug("FlightID fetching is disabled, skipping update")
            return {ATTR_COUNT: 0, ATTR_AIRCRAFT: []}

        try:
            states = await self.hass.async_add_executor_job(
                self._api.get_states,
                0,
                None,
                self._bounding_box,
            )
        except Exception as exc:
            raise UpdateFailed(f"Error fetching OpenSky data: {exc}") from exc

        if states is None or states.states is None:
            # Rate limited or no data available
            LOGGER.debug("OpenSky returned no states (rate limit or empty)")
            return self._empty_result()

        altitude_filter = self._get_altitude_filter()
        currently_tracked: set[str] = set()
        flight_metadata: dict[str, dict[str, Any]] = {}
        all_aircraft: list[dict[str, Any]] = []

        for state in states.states:
            if not state.callsign:
                continue

            callsign = state.callsign.strip()
            if not callsign:
                continue

            # Apply altitude filter (only if altitude is available)
            baro_alt = state.baro_altitude
            if altitude_filter != 0 and baro_alt is not None:
                if baro_alt > altitude_filter:
                    continue

            # Skip aircraft on the ground (optional heuristic)
            # Keep them but they're less interesting
            aircraft_data = _convert_aircraft_state(
                state, self._flight_cache, self._aircraft_metadata_cache
            )
            flight_metadata[callsign] = aircraft_data
            all_aircraft.append(aircraft_data)

            # Only count airborne aircraft for the "currently tracked" set
            if not state.on_ground:
                currently_tracked.add(callsign)

        # Fire entry/exit events
        if self._previously_tracked is not None:
            entries = currently_tracked - self._previously_tracked
            exits = self._previously_tracked - currently_tracked
            self._handle_boundary(entries, EVENT_FLIGHTID_ENTRY, flight_metadata)
            self._handle_boundary(exits, EVENT_FLIGHTID_EXIT, flight_metadata)

        self._previously_tracked = currently_tracked

        # Spawn background enrichments (don't block the main update)
        self.hass.async_create_task(self._async_enrich_routes(all_aircraft))
        self.hass.async_create_task(
            self._async_enrich_aircraft_metadata(all_aircraft)
        )

        return {
            ATTR_COUNT: len(currently_tracked),
            ATTR_AIRCRAFT: all_aircraft,
        }

    def _handle_boundary(
        self,
        flights: set[str],
        event: str,
        metadata: dict[str, dict[str, Any]],
    ) -> None:
        """Fire HA events when flights enter or exit the monitored area."""
        for flight in flights:
            data = metadata.get(flight)
            if data:
                event_data = {
                    ATTR_CALLSIGN: flight,
                    ATTR_AIRLINE: data.get(ATTR_AIRLINE),
                    ATTR_ALTITUDE: data.get(ATTR_ALTITUDE),
                    ATTR_ALTITUDE_FT: data.get(ATTR_ALTITUDE_FT),
                    ATTR_LATITUDE: data.get(ATTR_LATITUDE),
                    ATTR_LONGITUDE: data.get(ATTR_LONGITUDE),
                    ATTR_ICAO24: data.get(ATTR_ICAO24),
                    ATTR_ORIGIN_COUNTRY: data.get(ATTR_ORIGIN_COUNTRY),
                    ATTR_VELOCITY: data.get(ATTR_VELOCITY),
                    ATTR_SPEED_KTS: data.get(ATTR_SPEED_KTS),
                    ATTR_TRUE_TRACK: data.get(ATTR_TRUE_TRACK),
                    ATTR_DEPARTURE_AIRPORT: data.get(ATTR_DEPARTURE_AIRPORT),
                    ATTR_DEPARTURE_CITY: data.get(ATTR_DEPARTURE_CITY),
                    ATTR_DEPARTURE_COUNTRY: data.get(ATTR_DEPARTURE_COUNTRY),
                    ATTR_ARRIVAL_AIRPORT: data.get(ATTR_ARRIVAL_AIRPORT),
                    ATTR_ARRIVAL_CITY: data.get(ATTR_ARRIVAL_CITY),
                    ATTR_ARRIVAL_COUNTRY: data.get(ATTR_ARRIVAL_COUNTRY),
                }
            else:
                event_data = {
                    ATTR_CALLSIGN: flight,
                }
            self.hass.bus.fire(event, event_data)
