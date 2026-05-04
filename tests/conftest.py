"""Shared fixtures and test data for OpenSky REST tests."""

from __future__ import annotations

from collections import namedtuple

import pytest
from opensky_api import StateVector

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
