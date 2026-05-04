"""Tests for the sensor platform.

These tests mock the Home Assistant framework since it's not available
in the standalone test environment.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, PropertyMock

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


class _MockSensorEntity:
    """Stand-in for SensorEntity.

    Supports subscripting for generic type hints via __class_getitem__.
    """

    def __class_getitem__(cls, item):
        return cls


class _MockDataUpdateCoordinator:
    """Stand-in for DataUpdateCoordinator for type-hint subscripting."""

    def __class_getitem__(cls, item):
        return cls


_ha_mock = MagicMock()
_ha_mock.const.Platform = MagicMock()
_ha_mock.const.Platform.SENSOR = "sensor"
_ha_mock.exceptions.ConfigEntryNotReady = Exception
_ha_mock.helpers.config_validation = MagicMock()
_ha_mock.helpers.update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
_ha_mock.helpers.update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator
_ha_mock.helpers.update_coordinator.UpdateFailed = Exception
_ha_mock.helpers.entity_platform.AddConfigEntryEntitiesCallback = lambda x: x
_ha_mock.helpers.device_registry.DeviceEntryType = type(
    "DeviceEntryType", (), {"SERVICE": "service"}
)
_ha_mock.helpers.device_registry.DeviceInfo = MagicMock
_ha_mock.config_entries.ConfigEntry = MagicMock
_ha_mock.core.HomeAssistant = MagicMock
_ha_mock.components = MagicMock()
_ha_mock.components.sensor.SensorEntity = _MockSensorEntity
_ha_mock.components.sensor.SensorStateClass = type(
    "SensorStateClass", (), {"MEASUREMENT": "measurement"}
)

modules = {
    "homeassistant": _ha_mock,
    "homeassistant.const": _ha_mock.const,
    "homeassistant.exceptions": _ha_mock.exceptions,
    "homeassistant.helpers": _ha_mock.helpers,
    "homeassistant.helpers.config_validation": _ha_mock.helpers.config_validation,
    "homeassistant.helpers.update_coordinator": _ha_mock.helpers.update_coordinator,
    "homeassistant.helpers.entity_platform": _ha_mock.helpers.entity_platform,
    "homeassistant.helpers.device_registry": _ha_mock.helpers.device_registry,
    "homeassistant.config_entries": _ha_mock.config_entries,
    "homeassistant.core": _ha_mock.core,
    "homeassistant.components": _ha_mock.components,
    "homeassistant.components.sensor": _ha_mock.components.sensor,
    "homeassistant.components.sensor.const": _ha_mock.components.sensor,
}
for mod_name, mod in modules.items():
    sys.modules[mod_name] = mod

# Now safe to import from the component
from custom_components.opensky_rest.sensor import OpenSkyRestSensor


class TestOpenSkyRestSensor:
    """Tests for the sensor entity."""

    def _make_mock_coordinator(self, data: dict[str, Any] | None = None):
        """Create a mock coordinator with the given data."""
        mock = MagicMock()
        type(mock).data = PropertyMock(return_value=data)
        mock.config_entry = MagicMock()
        return mock

    def test_native_value_no_data(self):
        """When coordinator has no data, count should be 0."""
        coordinator = self._make_mock_coordinator(data=None)
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert sensor.native_value == 0

    def test_native_value_empty(self):
        """When coordinator's data has no flights, count should be 0."""
        coordinator = self._make_mock_coordinator(
            data={"count": 0, "aircraft": [], "stats": {}}
        )
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert sensor.native_value == 0

    def test_native_value_with_flights(self):
        """Count should reflect the number of tracked aircraft."""
        coordinator = self._make_mock_coordinator(
            data={"count": 5, "aircraft": [], "stats": {}}
        )
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert sensor.native_value == 5

    def test_extra_state_attributes_structure(self):
        """Attributes should include aircraft list and stats."""
        aircraft = [
            {
                "callsign": "UAL123",
                "airline": "United Airlines",
                "registration": "N12345",
                "aircraft_image_url": "https://t.plnspttrs.net/40667/1833758_ce6219854b_280.jpg",
                "altitude_ft": 35_000.0,
                "speed_kts": 485.0,
                "true_track": 270.0,
                "vertical_rate": 0.5,
                "latitude": 37.8,
                "longitude": -122.4,
                "origin_country": "United States",
                "on_ground": False,
                "category_name": "Large",
                "icao24": "abc123",
            }
        ]
        stats = {
            "avg_altitude_ft": 35_000.0,
            "avg_speed_kts": 485.0,
            "max_speed_kts": 500.0,
            "highest_callsign": "UAL123",
            "highest_altitude_ft": 35_000.0,
            "fastest_callsign": "UAL123",
            "fastest_speed_kts": 500.0,
            "airlines": {"United Airlines": 1},
        }
        coordinator = self._make_mock_coordinator(
            data={
                "count": 1,
                "aircraft": aircraft,
                "stats": stats,
            }
        )
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        attrs = sensor.extra_state_attributes

        assert attrs["total_aircraft"] == 1
        assert len(attrs["aircraft"]) == 1
        assert attrs["aircraft"][0]["callsign"] == "UAL123"
        assert attrs["aircraft"][0]["airline"] == "United Airlines"
        assert attrs["aircraft"][0]["registration"] == "N12345"
        assert attrs["aircraft"][0]["image_url"] == "https://t.plnspttrs.net/40667/1833758_ce6219854b_280.jpg"
        assert attrs["avg_altitude_ft"] == 35_000.0
        assert attrs["avg_speed_kts"] == 485.0
        assert attrs["highest_aircraft"] == "UAL123"
        assert attrs["fastest_aircraft"] == "UAL123"
        assert attrs["airlines"] == {"United Airlines": 1}

    def test_extra_state_attributes_no_data(self):
        """When there is no data, attributes should be empty."""
        coordinator = self._make_mock_coordinator(data=None)
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert sensor.extra_state_attributes == {}

    def test_extra_state_attributes_empty_aircraft(self):
        """When no aircraft are tracked, attributes should reflect that."""
        coordinator = self._make_mock_coordinator(
            data={"count": 0, "aircraft": [], "stats": {}}
        )
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        attrs = sensor.extra_state_attributes
        assert attrs["total_aircraft"] == 0
        assert attrs["aircraft"] == []

    def test_sensor_attribution(self):
        """Sensor should have the proper OpenSky attribution."""
        coordinator = self._make_mock_coordinator(data=None)
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert "OpenSky Network" in sensor._attr_attribution

    def test_unique_id_format(self):
        """Unique ID should include the config entry ID."""
        coordinator = self._make_mock_coordinator(data=None)
        config_entry = MagicMock()
        config_entry.entry_id = "entry_abc123"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert sensor._attr_unique_id == "entry_abc123_opensky_rest"

    def test_entity_picture_with_image(self):
        """entity_picture should return the fastest aircraft's image."""
        aircraft = [
            {
                "callsign": "UAL123",
                "altitude_ft": 35_000.0,
                "speed_kts": 485.0,
                "aircraft_image_url": "https://t.plnspttrs.net/fast.jpg",
            },
            {
                "callsign": "BAW456",
                "altitude_ft": 37_000.0,
                "speed_kts": 450.0,
                "aircraft_image_url": "https://t.plnspttrs.net/high.jpg",
            },
        ]
        coordinator = self._make_mock_coordinator(
            data={"count": 2, "aircraft": aircraft, "stats": {}}
        )
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        # Fastest (UAL123 at 485 kts) should be picked
        assert sensor.entity_picture == "https://t.plnspttrs.net/fast.jpg"

    def test_entity_picture_fallback_to_highest(self):
        """entity_picture should fall back to highest when fastest has no image."""
        aircraft = [
            {
                "callsign": "UAL123",
                "altitude_ft": 35_000.0,
                "speed_kts": 485.0,
                "aircraft_image_url": None,
            },
            {
                "callsign": "BAW456",
                "altitude_ft": 37_000.0,
                "speed_kts": 450.0,
                "aircraft_image_url": "https://t.plnspttrs.net/high.jpg",
            },
        ]
        coordinator = self._make_mock_coordinator(
            data={"count": 2, "aircraft": aircraft, "stats": {}}
        )
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        # Fastest has no image, fallback to highest (BAW456)
        assert sensor.entity_picture == "https://t.plnspttrs.net/high.jpg"

    def test_entity_picture_no_data(self):
        """entity_picture should return None when there is no data."""
        coordinator = self._make_mock_coordinator(data=None)
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert sensor.entity_picture is None

    def test_entity_picture_no_aircraft(self):
        """entity_picture should return None when there are no aircraft."""
        coordinator = self._make_mock_coordinator(
            data={"count": 0, "aircraft": [], "stats": {}}
        )
        config_entry = MagicMock()
        config_entry.entry_id = "test_id"

        sensor = OpenSkyRestSensor(coordinator, config_entry)
        assert sensor.entity_picture is None
