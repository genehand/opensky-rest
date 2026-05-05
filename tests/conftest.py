"""Shared fixtures and test data for OpenSky REST tests."""

from __future__ import annotations

import sys
import types
from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest
from opensky_api import StateVector

# ── Mock homeassistant before any component module is imported ────────
# This prevents ImportError when the component's __init__.py imports
# from homeassistant.config_entries, etc.  We use ``types.ModuleType``
# so that ``from homeassistant.X import Y`` works (MagicMock does not
# support ``from`` imports in Python 3.14).

_ha_const = types.ModuleType("homeassistant.const")
_ha_const.CONF_LATITUDE = "latitude"
_ha_const.CONF_LONGITUDE = "longitude"
_ha_const.CONF_RADIUS = "radius"
_ha_const.CONF_CLIENT_ID = "client_id"
_ha_const.CONF_CLIENT_SECRET = "client_secret"
_ha_const.Platform = types.SimpleNamespace()
_ha_const.Platform.SENSOR = "sensor"
_ha_const.Platform.SWITCH = "switch"

_ha_exceptions = types.ModuleType("homeassistant.exceptions")
_ha_exceptions.ConfigEntryNotReady = Exception

_ha_config_entries = types.ModuleType("homeassistant.config_entries")
_ha_config_entries.ConfigEntry = types.SimpleNamespace()

_ha_core = types.ModuleType("homeassistant.core")
_ha_core.HomeAssistant = types.SimpleNamespace()

_ha_helpers = types.ModuleType("homeassistant.helpers")
_ha_helpers_config_validation = types.ModuleType(
    "homeassistant.helpers.config_validation"
)
_ha_helpers_config_validation.config_entry_only_config_schema = lambda x: {}
_ha_helpers_update_coordinator = types.ModuleType(
    "homeassistant.helpers.update_coordinator"
)


class _MockCoordinatorEntity:
    """Stand-in for CoordinatorEntity."""

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator


class _MockDataUpdateCoordinator:
    """Stand-in for DataUpdateCoordinator."""

    def __class_getitem__(cls, item):
        return cls


_ha_helpers_update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
_ha_helpers_update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator
_ha_helpers_update_coordinator.UpdateFailed = Exception

_ha_platforms = types.ModuleType("homeassistant.helpers.entity_platform")

for mod_name, mod in {
    "homeassistant": types.ModuleType("homeassistant"),
    "homeassistant.const": _ha_const,
    "homeassistant.exceptions": _ha_exceptions,
    "homeassistant.config_entries": _ha_config_entries,
    "homeassistant.core": _ha_core,
    "homeassistant.helpers": _ha_helpers,
    "homeassistant.helpers.config_validation": _ha_helpers_config_validation,
    "homeassistant.helpers.update_coordinator": _ha_helpers_update_coordinator,
    "homeassistant.helpers.entity_platform": _ha_platforms,
}.items():
    sys.modules[mod_name] = mod

# ── Prevent real network calls during test import ──────────────────────
# The airports module fetches a ~34k-row CSV from adsb.lol at import
# time.  Patch ``requests.get`` *before* any component module is
# imported so the network call is mocked.

_empty_csv = (
    b"Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
    b",Heathrow,EGLL,LHR,London,GB,51.47,-0.46,83\n"
)

_mock_response = MagicMock()
_mock_response.status_code = 200
_mock_response.content = _empty_csv
_mock_response.raise_for_status = MagicMock()
_mock_response.headers = {}

_patch = patch("requests.get", return_value=_mock_response)
_patch.start()

# Pre-resolve AIRPORT_LOOKUP so that lazy __getattr__ won't trigger
# network calls during tests.  The conftest's requests.get patch above
# ensures the fetch gets our empty-CSV mock response.
import custom_components.opensky_ng.airports as _airports_mod
_airports_mod.CACHE_PATH = None  # Disable file cache in tests
_airports_mod._AIRPORT_LOOKUP_CACHE = {
    "EGLL": ("Heathrow Airport", "London", "GB"),
    "OTHH": ("Hamad International Airport", "Doha", "QA"),
    "KDAL": ("Dallas Love Field", "Dallas", "US"),
    "KHOU": ("William P Hobby Airport", "Houston", "US"),
    "KCRP": ("Corpus Christi International Airport", "Corpus Christi", "US"),
    "KJFK": ("John F Kennedy International Airport", "New York", "US"),
}
_ = _airports_mod.AIRPORT_LOOKUP  # Trigger lazy resolution

# A simple named tuple to simulate a mock HA config entry
MockConfigEntryData = namedtuple(
    "MockConfigEntryData",
    ["data", "options", "entry_id"],
)


def make_state_vector(
    icao24: str = "a1b2c3",
    callsign: str = "UAL123",
    origin_country: str = "United States",
    time_position: int = 1_700_000_000,
    last_contact: int = 1_700_000_010,
    longitude: float = -122.4194,
    latitude: float = 37.7749,
    baro_altitude: float = 10_668.0,
    on_ground: bool = False,
    velocity: float = 250.0,
    true_track: float = 270.0,
    vertical_rate: float = 0.5,
    sensors: list[int] | None = None,
    geo_altitude: float = 10_972.8,
    squawk: str | None = "1200",
    spi: bool = False,
    position_source: int = 0,
    category: int = 4,
) -> StateVector:
    """Create a StateVector with sensible defaults."""
    return StateVector([
        icao24,
        callsign,
        origin_country,
        time_position,
        last_contact,
        longitude,
        latitude,
        baro_altitude,
        on_ground,
        velocity,
        true_track,
        vertical_rate,
        sensors,
        geo_altitude,
        squawk,
        spi,
        position_source,
        category,
    ])


@pytest.fixture
def sample_airborne_state() -> StateVector:
    """A typical airborne commercial aircraft."""
    return make_state_vector(
        icao24="abc123",
        callsign="UAL123",
        origin_country="United States",
        baro_altitude=10_668.0,
        on_ground=False,
        velocity=250.0,
        true_track=270.0,
        vertical_rate=0.5,
        category=4,
    )


@pytest.fixture
def sample_on_ground_state() -> StateVector:
    """An aircraft on the ground."""
    return make_state_vector(
        icao24="def456",
        callsign="SWA456",
        origin_country="United States",
        baro_altitude=0.0,
        on_ground=True,
        velocity=0.0,
        true_track=0.0,
        vertical_rate=0.0,
        category=2,
    )


@pytest.fixture
def sample_heavy_state() -> StateVector:
    """A heavy aircraft at cruising altitude."""
    return make_state_vector(
        icao24="ghi789",
        callsign="BAW001",
        origin_country="United Kingdom",
        baro_altitude=11_278.0,  # ~37,000 ft
        on_ground=False,
        velocity=240.0,
        true_track=90.0,
        vertical_rate=0.0,
        category=6,
    )


@pytest.fixture
def sample_null_fields_state() -> StateVector:
    """A state vector with null fields (as the API sometimes returns)."""
    return make_state_vector(
        icao24="null99",
        callsign="",
        origin_country="Unknown",
        time_position=None,
        last_contact=1_700_000_000,
        longitude=None,
        latitude=None,
        baro_altitude=None,
        on_ground=False,
        velocity=None,
        true_track=None,
        vertical_rate=None,
        sensors=None,
        geo_altitude=None,
        squawk=None,
        spi=False,
        position_source=0,
        category=0,
    )


@pytest.fixture
def multiple_states(
    sample_airborne_state: StateVector,
    sample_on_ground_state: StateVector,
    sample_heavy_state: StateVector,
) -> list[StateVector]:
    """A mix of different aircraft states."""
    return [
        sample_airborne_state,
        sample_on_ground_state,
        sample_heavy_state,
    ]


@pytest.fixture
def mock_config_entry() -> MockConfigEntryData:
    """A simulated HA config entry."""
    return MockConfigEntryData(
        data={
            "latitude": 52.52,
            "longitude": 13.405,
        },
        options={
            "radius": 100_000,  # 100 km
            "altitude": 0,
        },
        entry_id="test_entry_1",
    )
