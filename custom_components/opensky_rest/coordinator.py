"""DataUpdateCoordinator for the OpenSky REST integration."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from opensky_api import OpenSkyApi, TokenManager

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AIRLINE_LOOKUP,
    ATTR_AIRCRAFT,
    ATTR_AIRLINE,
    ATTR_ALTITUDE,
    ATTR_ALTITUDE_FT,
    ATTR_BARO_ALTITUDE,
    ATTR_CALLSIGN,
    ATTR_CATEGORY,
    ATTR_CATEGORY_NAME,
    ATTR_COUNT,
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

UPDATE_INTERVAL_AUTH: timedelta = timedelta(seconds=90)
UPDATE_INTERVAL_ANON: timedelta = timedelta(minutes=15)


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


def _convert_aircraft_state(state: Any) -> dict[str, Any]:
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

    # Compute derived values
    if state.baro_altitude is not None:
        aircraft[ATTR_ALTITUDE] = state.baro_altitude
        aircraft[ATTR_ALTITUDE_FT] = round(state.baro_altitude * 3.28084, 1)
    elif state.geo_altitude is not None:
        aircraft[ATTR_ALTITUDE] = state.geo_altitude
        aircraft[ATTR_ALTITUDE_FT] = round(state.geo_altitude * 3.28084, 1)

    if state.velocity is not None:
        aircraft[ATTR_SPEED_KTS] = round(state.velocity * 1.94384, 1)

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
            aircraft_data = _convert_aircraft_state(state)
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
                    ATTR_ALTITUDE: data.get(ATTR_ALTITUDE),
                    ATTR_ALTITUDE_FT: data.get(ATTR_ALTITUDE_FT),
                    ATTR_LATITUDE: data.get(ATTR_LATITUDE),
                    ATTR_LONGITUDE: data.get(ATTR_LONGITUDE),
                    ATTR_ICAO24: data.get(ATTR_ICAO24),
                    ATTR_ORIGIN_COUNTRY: data.get(ATTR_ORIGIN_COUNTRY),
                    ATTR_VELOCITY: data.get(ATTR_VELOCITY),
                    ATTR_SPEED_KTS: data.get(ATTR_SPEED_KTS),
                    ATTR_TRUE_TRACK: data.get(ATTR_TRUE_TRACK),
                }
            else:
                event_data = {
                    ATTR_CALLSIGN: flight,
                }
            self.hass.bus.fire(event, event_data)


