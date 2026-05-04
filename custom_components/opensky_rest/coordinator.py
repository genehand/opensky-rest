"""DataUpdateCoordinator for the OpenSky REST integration."""

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

from .airports import AIRPORT_LOOKUP
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
    ATTR_REGISTRATION,
    ATTR_SENSORS,
    ATTR_SPEED_KTS,
    ATTR_SPI,
    ATTR_SQUAWK,
    ATTR_STATS,
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
    EVENT_OPENSKY_ENTRY,
    EVENT_OPENSKY_EXIT,
    LOGGER,
    POSITION_SOURCE_MAP,
)

FLIGHT_CACHE_TTL: timedelta = timedelta(hours=1)
AIRCRAFT_METADATA_CACHE_TTL: timedelta = timedelta(hours=24)

AIRCRAFT_METADATA_API: str = "https://api.airplanes.live/v2/icao"
PLANESPOTTERS_API: str = "https://api.planespotters.net/pub/photos/reg"

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
    info = AIRPORT_LOOKUP.get(icao_code.upper())
    if info is None:
        LOGGER.debug("Airport code %s not found in lookup table", icao_code)
    return info[1] if info else None


def _airport_country(icao_code: str | None) -> str | None:
    """Look up the country name for an ICAO airport code."""
    if not icao_code:
        return None
    info = AIRPORT_LOOKUP.get(icao_code.upper())
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

    # Look up registration from aircraft metadata cache
    registration = None
    if aircraft_metadata_cache:
        cached = aircraft_metadata_cache.get(state.icao24)
        if cached:
            registration = cached.get(ATTR_REGISTRATION)
    aircraft[ATTR_REGISTRATION] = registration

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
    if flight_cache:
        cached = flight_cache.get(state.icao24)
        if cached:
            aircraft[ATTR_DEPARTURE_AIRPORT] = cached.get(ATTR_DEPARTURE_AIRPORT)
            aircraft[ATTR_DEPARTURE_CITY] = cached.get(ATTR_DEPARTURE_CITY)
            aircraft[ATTR_DEPARTURE_COUNTRY] = cached.get(ATTR_DEPARTURE_COUNTRY)
            aircraft[ATTR_ARRIVAL_AIRPORT] = cached.get(ATTR_ARRIVAL_AIRPORT)
            aircraft[ATTR_ARRIVAL_CITY] = cached.get(ATTR_ARRIVAL_CITY)
            aircraft[ATTR_ARRIVAL_COUNTRY] = cached.get(ATTR_ARRIVAL_COUNTRY)
        elif state.callsign:
            LOGGER.debug(
                "No flight cache for %s (callsign=%s, icao24=%s) — "
                "will be populated by background enrichment",
                state.icao24,
                state.callsign.strip(),
                state.icao24,
            )

    return aircraft


class OpenSkyRestDataUpdateCoordinator(
    DataUpdateCoordinator[dict[str, Any]]
):
    """Coordinator for fetching OpenSky state data.

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

    def _should_fetch_flight(self, icao24: str, now: int) -> bool:
        """Check whether flight data for this ICAO24 should be refreshed."""
        cached = self._flight_cache.get(icao24)
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
    def _fetch_aircraft_metadata(icao24: str) -> dict[str, Any] | None:
        """Fetch aircraft metadata (registration, type, etc.) from airplanes.live.

        Calls ``https://api.airplanes.live/v2/icao/{icao24}`` which returns
        JSON with registration (``r``), aircraft type (``t``), operator
        (``ownOp``), etc.  Returns a dict with ``registration`` key on
        success, or None on error / not found.
        """
        try:
            resp = requests.get(
                f"{AIRCRAFT_METADATA_API}/{icao24}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            ac_list = data.get("ac")
            if not ac_list or not isinstance(ac_list, list) or len(ac_list) == 0:
                return None
            ac = ac_list[0]
            registration = ac.get("r")
            if not registration:
                return None
            return {
                ATTR_REGISTRATION: registration,
            }
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            LOGGER.debug("Metadata lookup failed for %s: %s", icao24, exc)
            return None

    @staticmethod
    def _fetch_aircraft_image(registration: str) -> str | None:
        """Fetch the first aircraft photo URL from Planespotters.net.

        Calls ``https://api.planespotters.net/pub/photos/reg/{reg}`` and
        returns the ``thumbnail_large.src`` of the first photo, or None
        if no photos are found or on error.
        """
        try:
            resp = requests.get(
                f"{PLANESPOTTERS_API}/{registration}",
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
            LOGGER.debug("Image lookup failed for %s: %s", registration, exc)
            return None

    async def _async_enrich_aircraft_metadata(
        self, aircraft_list: list[dict[str, Any]]
    ) -> None:
        """Background task: fetch aircraft metadata for tracked aircraft.

        Queries ``_fetch_aircraft_metadata`` for each unique ICAO24 whose
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

        LOGGER.debug(
            "Fetching aircraft metadata for %d aircraft: %s",
            len(icao24s_to_fetch),
            ", ".join(sorted(icao24s_to_fetch)),
        )

        tasks = [
            self.hass.async_add_executor_job(
                self._fetch_aircraft_metadata, icao24
            )
            for icao24 in icao24s_to_fetch
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for icao24, result in zip(icao24s_to_fetch, results):
            if isinstance(result, Exception):
                LOGGER.debug("Metadata lookup failed for %s: %s", icao24, result)
                continue

            registration = None
            if result and isinstance(result, dict):
                registration = result.get(ATTR_REGISTRATION)

            if registration:
                LOGGER.debug(
                    "Aircraft metadata for %s: registration=%s",
                    icao24,
                    registration,
                )
            else:
                LOGGER.debug(
                    "No registration found for %s (result=%s)", icao24, result
                )

            # Fetch image if we have a registration
            image_url = None
            if registration:
                image_url = self._fetch_aircraft_image(registration)
                if image_url:
                    LOGGER.debug(
                        "Aircraft %s: registration=%s, image=%s",
                        icao24,
                        registration,
                        image_url,
                    )
                else:
                    LOGGER.debug(
                        "No image found for %s (registration=%s)", icao24, registration
                    )

            self._aircraft_metadata_cache[icao24] = {
                ATTR_REGISTRATION: registration,
                ATTR_AIRCRAFT_IMAGE_URL: image_url,
                "last_updated": now,
            }

            # Update aircraft dict in-place so data propagates immediately
            for ac in aircraft_list:
                if ac.get(ATTR_ICAO24) == icao24:
                    ac[ATTR_REGISTRATION] = registration
                    ac[ATTR_AIRCRAFT_IMAGE_URL] = image_url
                    break

        # Notify entities so they re-read the updated attributes
        self.async_update_listeners()

    async def _async_enrich_routes(
        self, aircraft_list: list[dict[str, Any]]
    ) -> None:
        """Background task: fetch flight data for tracked aircraft.

        Queries ``get_flights_by_aircraft`` for each unique ICAO24 whose
        cache is stale and populates ``self._flight_cache``.
        """
        if self._api is None:
            return

        now = int(datetime.now(timezone.utc).timestamp())
        icao24s_to_fetch: set[str] = set()

        for ac in aircraft_list:
            icao24 = ac.get(ATTR_ICAO24)
            if icao24 and self._should_fetch_flight(icao24, now):
                icao24s_to_fetch.add(icao24)

        if not icao24s_to_fetch:
            return

        LOGGER.debug(
            "Fetching flight data for %d aircraft: %s",
            len(icao24s_to_fetch),
            ", ".join(sorted(icao24s_to_fetch)),
        )
        begin = now - 12 * 3600  # look back 12 hours

        tasks = [
            self.hass.async_add_executor_job(
                self._api.get_flights_by_aircraft, icao24, begin, now
            )
            for icao24 in icao24s_to_fetch
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for icao24, result in zip(icao24s_to_fetch, results):
            if isinstance(result, Exception):
                LOGGER.debug("Flight lookup failed for %s: %s", icao24, result)
                continue
            if not result:
                LOGGER.debug("No flight data returned for %s (empty result)", icao24)
                # Still cache with Nones so we don't retry every cycle
                self._flight_cache[icao24] = {
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
                    if ac.get(ATTR_ICAO24) == icao24:
                        ac[ATTR_DEPARTURE_AIRPORT] = None
                        ac[ATTR_DEPARTURE_CITY] = None
                        ac[ATTR_DEPARTURE_COUNTRY] = None
                        ac[ATTR_ARRIVAL_AIRPORT] = None
                        ac[ATTR_ARRIVAL_CITY] = None
                        ac[ATTR_ARRIVAL_COUNTRY] = None
                        break
                continue

            # Use the latest flight in the time window
            flight = result[-1] if len(result) > 1 else result[0]
            dep = getattr(flight, "estDepartureAirport", None)
            arr = getattr(flight, "estArrivalAirport", None)

            dep_city = _airport_city(dep)
            arr_city = _airport_city(arr)
            dep_country = _airport_country(dep)
            arr_country = _airport_country(arr)

            LOGGER.debug(
                "Flight enrichment for %s: dep=%s (%s, %s) arr=%s (%s, %s) "
                "[callsign=%s, flights_in_window=%d]",
                icao24,
                dep, dep_city, dep_country,
                arr, arr_city, arr_country,
                getattr(flight, "callsign", "?"),
                len(result),
            )

            self._flight_cache[icao24] = {
                ATTR_DEPARTURE_AIRPORT: dep,
                ATTR_DEPARTURE_CITY: dep_city,
                ATTR_DEPARTURE_COUNTRY: dep_country,
                ATTR_ARRIVAL_AIRPORT: arr,
                ATTR_ARRIVAL_CITY: arr_city,
                ATTR_ARRIVAL_COUNTRY: arr_country,
                "last_updated": now,
            }

            # Update aircraft dict in-place so data propagates immediately
            for ac in aircraft_list:
                if ac.get(ATTR_ICAO24) == icao24:
                    ac[ATTR_DEPARTURE_AIRPORT] = dep
                    ac[ATTR_DEPARTURE_CITY] = dep_city
                    ac[ATTR_DEPARTURE_COUNTRY] = dep_country
                    ac[ATTR_ARRIVAL_AIRPORT] = arr
                    ac[ATTR_ARRIVAL_CITY] = arr_city
                    ac[ATTR_ARRIVAL_COUNTRY] = arr_country
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
            LOGGER.debug("OpenSky REST fetching is disabled, skipping update")
            return self._empty_result()

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
            self._handle_boundary(entries, EVENT_OPENSKY_ENTRY, flight_metadata)
            self._handle_boundary(exits, EVENT_OPENSKY_EXIT, flight_metadata)

        self._previously_tracked = currently_tracked

        # Compute statistics
        stats = self._compute_stats(all_aircraft)

        # Spawn background enrichments (don't block the main update)
        self.hass.async_create_task(self._async_enrich_routes(all_aircraft))
        self.hass.async_create_task(
            self._async_enrich_aircraft_metadata(all_aircraft)
        )

        return {
            ATTR_COUNT: len(currently_tracked),
            ATTR_AIRCRAFT: all_aircraft,
            ATTR_STATS: stats,
        }

    def _empty_result(self) -> dict[str, Any]:
        """Return an empty result structure."""
        return {
            ATTR_COUNT: 0,
            ATTR_AIRCRAFT: [],
            ATTR_STATS: {
                "total": 0,
                "avg_altitude_ft": None,
                "max_speed_kts": None,
                "avg_speed_kts": None,
                "highest_callsign": None,
                "fastest_callsign": None,
                "airlines": {},
            },
        }

    def _compute_stats(
        self, aircraft_list: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Compute aggregate statistics from current aircraft data."""
        if not aircraft_list:
            return self._empty_result()[ATTR_STATS]

        altitudes_ft = [
            a[ATTR_ALTITUDE_FT]
            for a in aircraft_list
            if a.get(ATTR_ALTITUDE_FT) is not None
        ]
        speeds_kts = [
            a[ATTR_SPEED_KTS]
            for a in aircraft_list
            if a.get(ATTR_SPEED_KTS) is not None
        ]
        airlines: dict[str, int] = {}
        for a in aircraft_list:
            al = a.get(ATTR_AIRLINE) or "Unknown"
            airlines[al] = airlines.get(al, 0) + 1

        # Top aircraft
        highest = max(
            aircraft_list,
            key=lambda a: a.get(ATTR_ALTITUDE_FT) or 0,
        )
        fastest = max(
            aircraft_list,
            key=lambda a: a.get(ATTR_SPEED_KTS) or 0,
        )

        return {
            "total": len(aircraft_list),
            "avg_altitude_ft": round(sum(altitudes_ft) / len(altitudes_ft), 0)
            if altitudes_ft
            else None,
            "max_speed_kts": max(speeds_kts) if speeds_kts else None,
            "avg_speed_kts": round(sum(speeds_kts) / len(speeds_kts), 1)
            if speeds_kts
            else None,
            "highest_callsign": highest.get(ATTR_CALLSIGN),
            "highest_altitude_ft": highest.get(ATTR_ALTITUDE_FT),
            "fastest_callsign": fastest.get(ATTR_CALLSIGN),
            "fastest_speed_kts": fastest.get(ATTR_SPEED_KTS),
            "airlines": dict(
                sorted(airlines.items(), key=lambda x: x[1], reverse=True)[:20]
            ),
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
                    ATTR_REGISTRATION: data.get(ATTR_REGISTRATION),
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


