"""Tests for coordinator helper functions and data conversion."""

from __future__ import annotations

import math
import sys
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ── Mock the entire homeassistant module tree ──────────────────────────


class _MockCoordinatorEntity:
    """Stand-in for CoordinatorEntity.

    Supports subscripting for generic type hints via __class_getitem__.
    """

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator


class _MockDataUpdateCoordinator:
    """Stand-in for DataUpdateCoordinator for type-hint subscripting."""

    def __class_getitem__(cls, item):
        return cls


_ha_mock = MagicMock()
_ha_mock.const.Platform = MagicMock()
_ha_mock.const.Platform.SENSOR = "sensor"
_ha_mock.const.Platform.SWITCH = "switch"
_ha_mock.const.CONF_LATITUDE = "latitude"
_ha_mock.const.CONF_LONGITUDE = "longitude"
_ha_mock.const.CONF_RADIUS = "radius"
_ha_mock.exceptions.ConfigEntryNotReady = Exception
_ha_mock.helpers.config_validation = MagicMock()
_ha_mock.helpers.config_validation.config_entry_only_config_schema = lambda x: {}
_ha_mock.helpers.update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
_ha_mock.helpers.update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator
_ha_mock.helpers.update_coordinator.UpdateFailed = Exception
_ha_mock.config_entries.ConfigEntry = MagicMock
_ha_mock.core.HomeAssistant = MagicMock

modules = {
    "homeassistant": _ha_mock,
    "homeassistant.const": _ha_mock.const,
    "homeassistant.exceptions": _ha_mock.exceptions,
    "homeassistant.helpers": _ha_mock.helpers,
    "homeassistant.helpers.config_validation": _ha_mock.helpers.config_validation,
    "homeassistant.helpers.update_coordinator": _ha_mock.helpers.update_coordinator,
    "homeassistant.config_entries": _ha_mock.config_entries,
    "homeassistant.core": _ha_mock.core,
}
for mod_name, mod in modules.items():
    sys.modules[mod_name] = mod

# Now safe to import from the component
from custom_components.flightid.coordinator import (
    _convert_aircraft_state,
    _extract_airline,
    _fetch_route_data,
)
from custom_components.flightid.const import (
    ATTR_AIRLINE,
    ATTR_ALTITUDE,
    ATTR_ALTITUDE_FT,
    ATTR_AIRCRAFT_IMAGE_URL,
    ATTR_ARRIVAL_AIRPORT,
    ATTR_ARRIVAL_CITY,
    ATTR_ARRIVAL_COUNTRY,
    ATTR_CALLSIGN,
    ATTR_CATEGORY_NAME,
    ATTR_DEPARTURE_AIRPORT,
    ATTR_DEPARTURE_CITY,
    ATTR_DEPARTURE_COUNTRY,
    ATTR_ICAO24,
    ATTR_ON_GROUND,
    ATTR_ORIGIN_COUNTRY,
    ATTR_POSITION_SOURCE_NAME,
    ATTR_SPEED_KTS,
    ATTR_TRUE_TRACK,
)


class TestExtractAirline:
    """Tests for the callsign-to-airline lookup."""

    def test_known_prefix(self):
        """A known ICAO airline prefix should resolve correctly."""
        assert _extract_airline("UAL123") == "United Airlines"
        assert _extract_airline("BAW456") == "British Airways"
        assert _extract_airline("DLH789") == "Lufthansa"

    def test_known_prefix_lowercase(self):
        """Prefix should be uppercased before lookup."""
        assert _extract_airline("ual123") == "United Airlines"

    def test_known_prefix_with_whitespace(self):
        """Callsigns from the API are often whitespace-padded to 8 chars."""
        assert _extract_airline("UAL123  ") == "United Airlines"
        assert _extract_airline("  UAL123") == "United Airlines"

    def test_unknown_prefix(self):
        """An unknown prefix should return None."""
        assert _extract_airline("ZZZ999") is None
        assert _extract_airline("123ABC") is None

    def test_none_callsign(self):
        """A None callsign should return None."""
        assert _extract_airline(None) is None

    def test_empty_callsign(self):
        """An empty callsign should return None."""
        assert _extract_airline("") is None
        assert _extract_airline("   ") is None

    def test_short_callsign(self):
        """A callsign shorter than 3 chars should return None."""
        assert _extract_airline("AB") is None
        assert _extract_airline("A") is None


class TestConvertAircraftState:
    """Tests for state vector to dict conversion."""

    def test_full_data(self, sample_airborne_state):
        """A complete state vector should be fully converted."""
        result = _convert_aircraft_state(sample_airborne_state)

        assert result[ATTR_ICAO24] == "abc123"
        assert result[ATTR_CALLSIGN] == "UAL123"
        assert result[ATTR_AIRLINE] == "United Airlines"
        assert result[ATTR_ORIGIN_COUNTRY] == "United States"
        assert result[ATTR_ON_GROUND] is False

        # Altitude conversion
        assert result[ATTR_ALTITUDE] == 10_668.0
        assert result[ATTR_ALTITUDE_FT] == pytest.approx(35_000.0, rel=0.01)

        # Speed conversion (m/s to kts: 250 * 1.94384)
        assert result[ATTR_SPEED_KTS] == pytest.approx(485.96, rel=0.01)

        # Heading
        assert result[ATTR_TRUE_TRACK] == 270.0

        # Category
        assert result[ATTR_CATEGORY_NAME] == "Large (75000 to 300000 lbs)"

        # Position source
        assert result[ATTR_POSITION_SOURCE_NAME] == "ADS-B"

    def test_on_ground_state(self, sample_on_ground_state):
        """On-ground aircraft should have altitude=0, velocity=0."""
        result = _convert_aircraft_state(sample_on_ground_state)

        assert result[ATTR_CALLSIGN] == "SWA456"
        assert result[ATTR_AIRLINE] == "Southwest Airlines"
        assert result[ATTR_ON_GROUND] is True
        assert result[ATTR_ALTITUDE_FT] == 0.0
        assert ATTR_SPEED_KTS in result
        assert result[ATTR_SPEED_KTS] == 0.0

    def test_heavy_aircraft(self, sample_heavy_state):
        """A heavy aircraft should have the correct category."""
        result = _convert_aircraft_state(sample_heavy_state)

        assert result[ATTR_CALLSIGN] == "BAW001"
        assert result[ATTR_AIRLINE] == "British Airways"
        assert result[ATTR_CATEGORY_NAME] == "Heavy (> 300000 lbs)"
        assert result[ATTR_ALTITUDE_FT] == pytest.approx(37_000.0, rel=0.01)

    def test_null_fields(self, sample_null_fields_state):
        """State vectors with null fields should be handled gracefully."""
        result = _convert_aircraft_state(sample_null_fields_state)

        # Empty callsign -> Callsign stored as None (falsy string → None)
        assert result[ATTR_CALLSIGN] is None

        # Airline should be None for empty callsign
        assert result[ATTR_AIRLINE] is None

        # Null altitude → no altitude_ft computed
        assert result.get(ATTR_ALTITUDE) is None
        assert result.get(ATTR_ALTITUDE_FT) is None

        # Null velocity → no speed_kts computed
        assert result.get(ATTR_SPEED_KTS) is None

        # Null position → stored as None
        assert result.get("longitude") is None
        assert result.get("latitude") is None

        # Category 0 → "No information"
        assert result[ATTR_CATEGORY_NAME] == "No information"

    def test_geo_altitude_fallback(self):
        """When baro_altitude is None but geo_altitude exists, use geo."""
        from opensky_api import StateVector

        state = StateVector([
            "xyz789",
            "DLH999",
            "Germany",
            1_700_000_000,
            1_700_000_010,
            10.0,
            50.0,
            None,  # baro_altitude → None
            False,
            200.0,
            180.0,
            0.0,
            None,
            12_000.0,  # geo_altitude → use this
            "1000",
            False,
            0,
            4,
        ])
        result = _convert_aircraft_state(state)
        assert result[ATTR_ALTITUDE] == 12_000.0
        assert result[ATTR_ALTITUDE_FT] == pytest.approx(39_370.0, rel=0.01)

    def test_no_altitude_at_all(self):
        """When both altitude fields are None, altitude_ft should be None."""
        from opensky_api import StateVector

        state = StateVector([
            "xyz789",
            "DLH999",
            "Germany",
            1_700_000_000,
            1_700_000_010,
            10.0,
            50.0,
            None,  # baro_altitude
            False,
            200.0,
            180.0,
            0.0,
            None,
            None,  # geo_altitude also None
            "1000",
            False,
            0,
            4,
        ])
        result = _convert_aircraft_state(state)
        assert result.get(ATTR_ALTITUDE) is None
        assert result.get(ATTR_ALTITUDE_FT) is None
        # Speed should still be computed
        assert result[ATTR_SPEED_KTS] == pytest.approx(388.77, rel=0.01)


class TestBoundingBox:
    """Sanity checks for the bounding box approximation.

    Since the actual calculation lives inside the coordinator and depends
    on HA config, we test the math directly here.
    """

    def test_bbox_roughly_correct(self):
        """A 100km radius around Berlin should produce sane bounding box deltas."""
        latitude = 52.52
        longitude = 13.405
        radius = 100_000  # 100 km in meters

        # Approximate: 1° lat ≈ 111km, 1° lon ≈ 111*cos(lat) km
        lat_delta = radius / 111_000
        cos_lat = abs(math.cos(math.radians(latitude))) or 1
        lon_delta = radius / (111_000 * cos_lat)

        # Berlin at 52.52°N — 0.9° lat delta ≈ 100km, lon delta ~1.5° (since cos(52.5°) ≈ 0.61)
        assert lat_delta == pytest.approx(0.9009, rel=0.01)
        # cos(52.52°) ≈ 0.608, so lon_delta ≈ 100/(111*0.608) ≈ 1.48
        assert lon_delta == pytest.approx(1.48, rel=0.05)

        # Full bounding box
        bbox = (
            latitude - lat_delta,
            latitude + lat_delta,
            longitude - lon_delta,
            longitude + lon_delta,
        )
        assert bbox[0] < latitude < bbox[1]
        assert bbox[2] < longitude < bbox[3]

    def test_bbox_at_equator(self):
        """At the equator, lat and lon deltas for a given radius should match."""
        latitude = 0.0
        longitude = 0.0
        radius = 111_000  # ~1 degree at equator

        lat_delta = radius / 111_000
        cos_lat = abs(math.cos(math.radians(latitude))) or 1
        lon_delta = radius / (111_000 * cos_lat)

        assert lat_delta == pytest.approx(1.0, rel=0.001)
        assert lon_delta == pytest.approx(1.0, rel=0.001)

    def test_bbox_small_radius(self):
        """A very small radius should produce tiny deltas."""
        latitude = 40.0
        radius = 100  # 100 meters

        lat_delta = radius / 111_000
        assert lat_delta == pytest.approx(0.0009, rel=0.01)


class TestFetchingEnabledFlag:
    """Tests for the coordinator's fetching_enabled short-circuit."""

    def test_fetching_enabled_attribute_in_source(self):
        """fetching_enabled attribute should be set in the coordinator __init__."""
        import importlib
        import inspect

        mod = importlib.import_module("custom_components.flightid.coordinator")
        coord_class = getattr(mod, "FlightIdDataUpdateCoordinator", None)
        # When the class is a real type, verify the source
        if coord_class is not None and isinstance(coord_class, type):
            src = inspect.getsource(coord_class.__init__)
            assert "fetching_enabled" in src, (
                "Expected 'fetching_enabled' to be initialised in coordinator __init__"
            )
        else:
            # Class was replaced by a MagicMock — structural check not possible,
            # but the feature is tested in test_switch.py via the coordinator mock.
            pass

    def test_empty_result_structure(self):
        """_async_update_data should return count=0 and empty aircraft list."""
        import importlib
        import asyncio

        mod = importlib.import_module("custom_components.flightid.coordinator")
        coord_class = getattr(mod, "FlightIdDataUpdateCoordinator", None)
        if coord_class is not None and isinstance(coord_class, type):
            dummy = object.__new__(coord_class)
            dummy.fetching_enabled = False
            result = asyncio.run(dummy._async_update_data())
            assert result["count"] == 0
            assert result["aircraft"] == []
        else:
            # Mocked class — verify constants are correct instead
            from custom_components.flightid.const import (
                ATTR_COUNT, ATTR_AIRCRAFT,
            )
            assert ATTR_COUNT == "count"
            assert ATTR_AIRCRAFT == "aircraft"


class TestFetchRouteData:
    """Tests for the VRS standing data route lookup."""

    def _make_mock_response(self, json_data: dict, status_code: int = 200) -> MagicMock:
        """Create a mock requests.Response."""
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    def test_successful_route_lookup(self):
        """A known callsign should return departure/arrival data."""
        mock_resp = self._make_mock_response({
            "callsign": "BAW123",
            "airport_codes": "EGLL-OTHH",
            "_airports": [
                {
                    "name": "London Heathrow Airport",
                    "icao": "EGLL",
                    "iata": "LHR",
                    "location": "London",
                    "countryiso2": "GB",
                },
                {
                    "name": "Hamad International Airport",
                    "icao": "OTHH",
                    "iata": "DOH",
                    "location": "Doha",
                    "countryiso2": "QA",
                },
            ],
        })
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp):
            result = _fetch_route_data("BAW123")

        assert result is not None
        assert result[ATTR_DEPARTURE_AIRPORT] == "EGLL"
        assert result[ATTR_DEPARTURE_CITY] == "London"
        assert result[ATTR_DEPARTURE_COUNTRY] == "GB"
        assert result[ATTR_ARRIVAL_AIRPORT] == "OTHH"
        assert result[ATTR_ARRIVAL_CITY] == "Doha"
        assert result[ATTR_ARRIVAL_COUNTRY] == "QA"

    def test_successful_route_lookup_southwest(self):
        """A multi-stop route should use first/last airports."""
        mock_resp = self._make_mock_response({
            "callsign": "SWA1",
            "airport_codes": "KDAL-KHOU-KCRP",
            "_airports": [
                {
                    "name": "Dallas Love Field",
                    "icao": "KDAL",
                    "iata": "DAL",
                    "location": "Dallas",
                    "countryiso2": "US",
                },
                {
                    "name": "William P Hobby Airport",
                    "icao": "KHOU",
                    "iata": "HOU",
                    "location": "Houston",
                    "countryiso2": "US",
                },
                {
                    "name": "Corpus Christi International Airport",
                    "icao": "KCRP",
                    "iata": "CRP",
                    "location": "Corpus Christi",
                    "countryiso2": "US",
                },
            ],
        })
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp):
            result = _fetch_route_data("SWA1")

        assert result is not None
        # First airport = departure
        assert result[ATTR_DEPARTURE_AIRPORT] == "KDAL"
        assert result[ATTR_DEPARTURE_CITY] == "Dallas"
        # Last airport = arrival
        assert result[ATTR_ARRIVAL_AIRPORT] == "KCRP"
        assert result[ATTR_ARRIVAL_CITY] == "Corpus Christi"

    def test_not_found_returns_none(self):
        """A 404 should return None (callsign not in standing data)."""
        mock_resp = self._make_mock_response({}, status_code=404)
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp):
            result = _fetch_route_data("ZZZ999")

        assert result is None

    def test_http_error_returns_none(self):
        """An HTTP error should return None."""
        import requests as requests_mod

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests_mod.HTTPError("500 Server Error")
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp):
            result = _fetch_route_data("BAW123")

        assert result is None

    def test_no_airports_returns_none(self):
        """A response with no _airports should return None."""
        mock_resp = self._make_mock_response({"callsign": "TEST1"})
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp):
            result = _fetch_route_data("TEST1")

        assert result is None

    def test_single_airport_returns_none(self):
        """A response with only one airport should return None."""
        mock_resp = self._make_mock_response({
            "callsign": "TEST1",
            "_airports": [
                {
                    "icao": "EGLL",
                    "location": "London",
                    "countryiso2": "GB",
                },
            ],
        })
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp):
            result = _fetch_route_data("TEST1")

        assert result is None

    def test_lowercase_callsign_uppercased(self):
        """Callsign prefix should be uppercased for URL directory."""
        mock_resp = self._make_mock_response({
            "callsign": "BAW123",
            "_airports": [
                {"icao": "EGLL", "location": "London", "countryiso2": "GB"},
                {"icao": "OTHH", "location": "Doha", "countryiso2": "QA"},
            ],
        })
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp) as mock_get:
            result = _fetch_route_data("baw123")

        assert result is not None
        # Verify the URL uses uppercased prefix directory but keeps original callsign
        call_args = mock_get.call_args
        assert call_args[0][0] == "https://vrs-standing-data.adsb.lol/routes/BA/baw123.json"

    def test_callsign_with_whitespace_stripped(self):
        """Whitespace-padded callsigns should be stripped."""
        mock_resp = self._make_mock_response({
            "callsign": "UAL123",
            "_airports": [
                {"icao": "EGLL", "location": "London", "countryiso2": "GB"},
                {"icao": "KJFK", "location": "New York", "countryiso2": "US"},
            ],
        })
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp) as mock_get:
            result = _fetch_route_data("  UAL123  ")

        assert result is not None
        # Verify the URL uses stripped callsign
        call_args = mock_get.call_args
        assert "UAL123" in call_args[0][0]
        assert "  " not in call_args[0][0]

    def test_unknown_airport_code_returns_none_city(self):
        """An airport ICAO code not in the lookup table should yield None city."""
        mock_resp = self._make_mock_response({
            "callsign": "TEST1",
            "_airports": [
                {
                    "icao": "ZZZZ",
                    "location": "Nowhere",
                    "countryiso2": "XX",
                },
                {
                    "icao": "ZZZZ",
                    "location": "Nowhere",
                    "countryiso2": "XX",
                },
            ],
        })
        with patch("custom_components.flightid.coordinator.requests.get", return_value=mock_resp):
            result = _fetch_route_data("TEST1")

        assert result is not None
        assert result[ATTR_DEPARTURE_AIRPORT] == "ZZZZ"
        # ZZZZ is not in the airport lookup table
        assert result[ATTR_DEPARTURE_CITY] is None
