"""Tests for constants, mappings, and the airline lookup table."""

from __future__ import annotations

from custom_components.opensky_rest.const import (
    AIRLINE_LOOKUP,
    CATEGORY_MAP,
    DOMAIN,
    MANUFACTURER,
    POSITION_SOURCE_MAP,
    TRANSLATION_KEY_FLIGHTS,
)


class TestAirlineLookup:
    """Verify the airline callsign prefix lookup table."""

    def test_known_major_airlines(self):
        """Major airlines should be present in the lookup."""
        known = {
            "AAL": "American Airlines",
            "DAL": "Delta Air Lines",
            "UAL": "United Airlines",
            "SWA": "Southwest Airlines",
            "BAW": "British Airways",
            "DLH": "Lufthansa",
            "AFR": "Air France",
            "KLM": "KLM Royal Dutch Airlines",
            "RYR": "Ryanair",
            "UAE": "Emirates",
            "QTR": "Qatar Airways",
            "SIA": "Singapore Airlines",
            "CPA": "Cathay Pacific",
            "QFA": "Qantas",
            "JBU": "JetBlue Airways",
            "VIR": "Virgin Atlantic",
            "UPS": "UPS Airlines",
            "FDX": "FedEx Express",
        }
        for prefix, expected_name in known.items():
            assert prefix in AIRLINE_LOOKUP, f"Missing airline prefix: {prefix}"
            assert AIRLINE_LOOKUP[prefix] == expected_name, (
                f"Expected {prefix} -> {expected_name}, "
                f"got {AIRLINE_LOOKUP[prefix]}"
            )

    def test_unknown_prefix_not_in_lookup(self):
        """A made-up prefix should not be in the table."""
        assert "ZZZ" not in AIRLINE_LOOKUP
        assert "123" not in AIRLINE_LOOKUP

    def test_no_duplicate_keys(self):
        """All keys in AIRLINE_LOOKUP must be unique."""
        assert len(AIRLINE_LOOKUP) == len(set(AIRLINE_LOOKUP.keys()))

    def test_all_values_are_nonempty_strings(self):
        """Every airline name should be a non-empty string."""
        for prefix, name in AIRLINE_LOOKUP.items():
            assert isinstance(prefix, str) and len(prefix) == 3, (
                f"Prefix {prefix!r} should be a 3-char string"
            )
            assert isinstance(name, str) and name, (
                f"Name for {prefix!r} should be non-empty"
            )

    def test_lookup_table_has_reasonable_size(self):
        """We should have at least 100 airline entries."""
        assert len(AIRLINE_LOOKUP) >= 100, (
            f"Expected >= 100 airlines, got {len(AIRLINE_LOOKUP)}"
        )


class TestCategoryMap:
    """Verify the aircraft category mapping."""

    def test_all_categories_covered(self):
        """Categories 0 through 20 should all be present."""
        for i in range(21):
            assert i in CATEGORY_MAP, f"Missing category {i}"

    def test_no_extra_categories(self):
        """No categories beyond 20 should exist."""
        assert max(CATEGORY_MAP.keys()) == 20

    def test_category_names(self):
        """Spot-check a few category names."""
        assert CATEGORY_MAP[0] == "No information"
        assert CATEGORY_MAP[2] == "Light (< 15500 lbs)"
        assert CATEGORY_MAP[4] == "Large (75000 to 300000 lbs)"
        assert CATEGORY_MAP[6] == "Heavy (> 300000 lbs)"
        assert CATEGORY_MAP[8] == "Rotorcraft"
        assert CATEGORY_MAP[14] == "Unmanned Aerial Vehicle"


class TestPositionSourceMap:
    """Verify the position source mapping."""

    def test_all_sources_covered(self):
        """Sources 0 through 3 should all be present."""
        for i in range(4):
            assert i in POSITION_SOURCE_MAP, f"Missing position source {i}"

    def test_source_names(self):
        """Spot-check source names."""
        assert POSITION_SOURCE_MAP[0] == "ADS-B"
        assert POSITION_SOURCE_MAP[1] == "ASTERIX"
        assert POSITION_SOURCE_MAP[2] == "MLAT"
        assert POSITION_SOURCE_MAP[3] == "FLARM"


class TestBasicConstants:
    """Verify basic constants are set correctly."""

    def test_domain(self):
        assert DOMAIN == "opensky_rest"

    def test_manufacturer(self):
        assert MANUFACTURER == "OpenSky Network"

    def test_translation_key(self):
        assert TRANSLATION_KEY_FLIGHTS == "flights"
