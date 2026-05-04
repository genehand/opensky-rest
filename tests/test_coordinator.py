"""Tests for coordinator helper functions and data conversion."""

from __future__ import annotations

import math

import pytest

from custom_components.opensky_rest.coordinator import (
    _convert_aircraft_state,
    _extract_airline,
)
from custom_components.opensky_rest.const import (
    ATTR_AIRLINE,
    ATTR_ALTITUDE,
    ATTR_ALTITUDE_FT,
    ATTR_CALLSIGN,
    ATTR_CATEGORY_NAME,
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
