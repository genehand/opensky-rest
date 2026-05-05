# OpenSky REST - Home Assistant Custom Integration

## Overview

This project is a **custom Home Assistant integration** that provides real-time aircraft tracking data from the [OpenSky Network](https://opensky-network.org) REST API. It wraps the official [`opensky-api`](https://github.com/openskynetwork/opensky-api) Python library (v1.4.0) in HA's `async_add_executor_job` pattern to keep the event loop responsive.

The integration monitors a configurable geographic area (bounding box defined by lat/lon/radius) and exposes a sensor showing the number of aircraft with rich attributes (callsign, airline, registration, altitude, speed, heading, origin country, Planespotters link, etc.). It also fires events when aircraft enter or leave the monitored airspace.

## Directory Structure

```
opensky-ng/
├── AGENTS.md                          # This file
├── custom_components/
│   └── opensky_ng/
│       ├── __init__.py                # HA entry point: async_setup_entry / async_unload_entry
│       ├── manifest.json              # Metadata: domain, version, pip dependency
│       ├── airports.py                # Airport ICAO → (name, city, country) lookup (fetched live from adsb.lol)
│       ├── const.py                   # Constants, airline lookup tables (~150 airlines)
│       ├── config_flow.py             # UI-based config (lat/lon/radius) + OAuth2 options
│       ├── coordinator.py             # DataUpdateCoordinator wrapping opensky-api via executor
│       ├── sensor.py                  # Flight count sensor with rich attributes
│       ├── translations/              # Language translations
│       └── icons.json                 # MDI icon mapping (mdi:airplane)
```

## Key Design Decisions

### Sync library wrapped in executor
The official `opensky-api` library uses the synchronous `requests` library. Rather than rewriting it with `aiohttp`, we wrap calls in `hass.async_add_executor_job()` - a well-established HA pattern

### OAuth2 + Anonymous support

- **No credentials** → anonymous access with reduced rate limits (400 credits/day, ~one call per 15 min)
- **OAuth2 client_credentials** → 4000+ credits/day, 90s polling
- `TokenManager` handles automatic token refresh (30-min expiry)

### Single sensor with rich attributes

Following the existing `opensky` integration pattern, a single sensor entity (`sensor.opensky_flights`) shows the flight count as its state, with all aircraft data and statistics in `extra_state_attributes`.

### Airline callsign lookup

Extracts the first 3 characters of each callsign (e.g., "UAL123" → "UAL") and looks up the airline name from a built-in table of ~150 ICAO airline designators. Unknown prefixes result in `None`.

### Departure/arrival city enrichment

Each aircraft's attributes include `departure_city`, `departure_country`, `arrival_city`, and `arrival_country` fields derived from OpenSky's historical flight data. A background task calls `opensky_api.get_flights_by_aircraft(icao24, begin, end)` for each new aircraft entering the monitored area and caches the results for 1 hour. The returned `estDepartureAirport`/`estArrivalAirport` ICAO codes (e.g., `"KLAX"`) are looked up in a built-in table of 1,170 large airports worldwide (sourced from OurAirports). Aircraft whose route data isn't cached yet show `None` for these fields until the background query completes (usually within the next poll cycle).

**API credit impact**: Each `get_flights_by_aircraft` call costs 1 credit per aircraft. With 1-hour caching and 30 unique aircraft/hour, this adds ~30 credits/hour to the main state vector call. Authenticated users (4,000+ credits/day) can comfortably use this.

### Aircraft registration & Planespotters links

Each aircraft's attributes include a `registration` field (tail number like "N12345") resolved from the aircraft's ICAO24 transponder code via the [airplanes.live](https://api.airplanes.live) public API (`https://api.airplanes.live/v2/icao/{icao24}`). A background task calls this endpoint for each new aircraft entering the monitored area and caches the results for 24 hours (registration rarely changes per airframe). A `image_url` field is also provided, linking to `https://t.plnspttrs.net/` for easy photo lookup. Registration data becomes available within 1-2 poll cycles after first detection.

## Architecture & Data Flow

```
OpenSky REST API (cloud)
    ↕ HTTP (requests, via executor thread)
opensky_api.OpenSkyApi (sync)
    ↕ async_add_executor_job
OpenSkyRestDataUpdateCoordinator (async)
    ├── async_config_entry_first_refresh()  ← called on setup
    ├── _async_update_data()                ← called every poll interval
    │   ├── api.get_states(time=0, bbox=...) → OpenSkyStates
    │   ├── filter by altitude
    │   ├── convert StateVectors → dicts (alt_ft, speed_kts, airline name, category name)
    │   ├── compute entry/exit sets → fire HA events
    │   ├── compute statistics (averages, top-N, airline breakdown)
    │   ├── spawn background flight enrichment (get_flights_by_aircraft)
    │   ├── spawn background aircraft metadata enrichment (get registration)
    │   └── return {count, aircraft[], stats{}}
    └── data → sensors read via self.coordinator.data
OpenSkyRestSensor (CoordinatorEntity)
    ├── native_value → count
    └── extra_state_attributes → aircraft list + stats
```

## Entities & Events

### Sensor

- **`sensor.opensky_flights`**: Number of airborne aircraft in the monitored area
  - State class: `measurement`
  - Unit: `flights`
  - Attributes: full aircraft list (with per-aircraft registration, Planespotters URLs, departure/arrival cities), avg altitude/speed, highest/fastest aircraft, airline breakdown

### Events

- **`opensky_ng_entry`**: Fired when an aircraft enters the monitored airspace
  - Event data: callsign, airline, altitude, position, icao24, origin_country, speed, heading, registration, image_url, departure/arrival airport/city/country
- **`opensky_ng_exit`**: Fired when an aircraft leaves the monitored airspace
  - Same event data structure

## Configuration

### Initial Setup (config flow)
| Field | Required | Description |
|-------|----------|-------------|
| `latitude` | Yes | Center latitude (defaults to HA location) |
| `longitude` | Yes | Center longitude (defaults to HA location) |
| `radius` | Yes | Monitoring radius in meters (default 100) |
| `altitude` | No | Max altitude filter in meters (0 = no limit) |
| `client_id` | No | OAuth2 client ID (from OpenSky account page) |
| `client_secret` | No | OAuth2 client secret |

### Options (can be changed after setup)
| Field | Required | Description |
|-------|----------|-------------|
| `radius` | Yes | Monitoring radius in meters |
| `altitude` | No | Max altitude filter in meters |
| `client_id` | No | OAuth2 client ID (from OpenSky account page) |
| `client_secret` | No | OAuth2 client secret |

## Polling Intervals

| Mode | Interval | Credits/Day | API Call Cost |
|------|----------|-------------|---------------|
| Anonymous | 15 minutes | 400 | 1-4 credits (depends on bbox area) |
| Authenticated | 90 seconds | 4000+ | 1-4 credits (depends on bbox area) |

## API Credit Costs

Bounding box area = lat_range × lon_range (in square degrees):

- ≤ 25 sq° → 1 credit
- 25-100 sq° → 2 credits
- 100-400 sq° → 3 credits
- > 400 sq° → 4 credits

## Known Limitations

- **No airline names** from OpenSky directly - we infer from callsign prefix (best-effort, ~150 airlines in lookup)
- **No scheduled times** - OpenSky only provides observed/estimated times
- **Bounding box is approximate** - uses flat-earth approximation (adequate for <500km radius)

## Dependencies

- **Runtime**: `opensky-api @ git+https://github.com/openskynetwork/opensky-api.git#subdirectory=python`
  - This installs the single-module package `opensky_api` (version 1.4.0)
  - The library provides: `OpenSkyApi`, `TokenManager`, `StateVector`, `OpenSkyStates`, `FlightData`, `FlightTrack`, `Waypoint`
  - We only use `OpenSkyApi`, `TokenManager`, `OpenSkyStates`, and `StateVector`
- **HA Core**: Standard HA patterns (`DataUpdateCoordinator`, `CoordinatorEntity`, `ConfigFlow`)
- **External API**: [airplanes.live](https://api.airplanes.live) — free, public API for ICAO24 → registration lookups (no API key required)

## Tests

Located in `tests/`:

```
tests/
├── conftest.py             # Shared fixtures: sample StateVectors, mock config entry
├── test_const.py           # Airline lookup completeness, category/position maps
├── test_coordinator.py     # _extract_airline, _convert_aircraft_state, bounding box
├── test_config_flow.py     # Config flow creation, OAuth2 validation, options flow
└── test_sensor.py          # native_value, extra_state_attributes, unique_id, attribution
```

### Running Tests

```bash
source .venv/bin/activate
PYTHONPATH=".:$PYTHONPATH" python -m pytest tests/ -v
```

### Test Approach

- **Pure unit tests** (`test_const`, `test_coordinator`): Test standalone helper functions with no HA dependency.
- **HA-mocked tests** (`test_config_flow`, `test_sensor`): Mock the entire `homeassistant` module tree via `sys.modules` patching before importing the component. Allows testing config flow logic, sensor state/attributes, and OAuth2 validation without the full HA runtime.

### Key Fixtures (conftest.py)

- `sample_airborne_state` — Typical commercial aircraft (UAL123, 35k ft, 250 m/s)
- `sample_on_ground_state` — Aircraft on the ground (SWA456, 0 altitude)
- `sample_heavy_state` — Heavy aircraft (BAW001, 37k ft, category 6)
- `sample_null_fields_state` — State with None values (simulates API edge cases)
- `multiple_states` — Combined fixture with all the above
- `mock_config_entry` — Simulated HA ConfigEntry

## Common Issues & Troubleshooting

- **"Failed to connect to OpenSky API"**: Network issue or HA cannot reach `opensky-network.org`
- **State shows 0 flights**: Check radius - if too small, no aircraft may be in the area. Try 100km+.
- **Rate limited (None states)**: You get 400 anonymous API credits/day. Each call costs 1-4 credits. Authenticate with OAuth2 for higher limits.
- **OAuth2 "invalid_auth"**: Ensure client_id and client_secret are from the OpenSky account page (API Clients section). Credentials must be for the OAuth2 client credentials flow.
- **Large attribute payloads**: In areas with heavy air traffic (e.g., London, Atlanta), the `aircraft` attribute list can be large. This is a known limitation of the single-sensor approach.

## Testing Patterns

### Mocking Home Assistant

Because the component imports `from homeassistant.X import Y` at module level, you cannot simply `import custom_components.opensky_ng` without `homeassistant` installed. The established pattern is to mock the entire `homeassistant` module tree **before** any component import, using `types.ModuleType` (not `MagicMock`) so that `from X import Y` works:

```python
# tests/conftest.py — at module level, before any component imports

import sys
import types

_ha_const = types.ModuleType("homeassistant.const")
_ha_const.CONF_LATITUDE = "latitude"
_ha_const.CONF_LONGITUDE = "longitude"
_ha_const.CONF_RADIUS = "radius"
_ha_const.Platform = types.SimpleNamespace()
_ha_const.Platform.SENSOR = "sensor"
_ha_const.Platform.SWITCH = "switch"

_ha_exceptions = types.ModuleType("homeassistant.exceptions")
_ha_exceptions.ConfigEntryNotReady = Exception

_ha_config_entries = types.ModuleType("homeassistant.config_entries")
_ha_config_entries.ConfigEntry = types.SimpleNamespace()

_ha_core = types.ModuleType("homeassistant.core")
_ha_core.HomeAssistant = types.SimpleNamespace()

_ha_helpers_update_coordinator = types.ModuleType(
    "homeassistant.helpers.update_coordinator"
)

class _MockCoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls
    def __init__(self, coordinator):
        self.coordinator = coordinator

class _MockDataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

_ha_helpers_update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
_ha_helpers_update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator
_ha_helpers_update_coordinator.UpdateFailed = Exception

for mod_name, mod in {
    "homeassistant": types.ModuleType("homeassistant"),
    "homeassistant.const": _ha_const,
    "homeassistant.exceptions": _ha_exceptions,
    "homeassistant.config_entries": _ha_config_entries,
    "homeassistant.core": _ha_core,
    "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
    "homeassistant.helpers.config_validation": types.ModuleType(
        "homeassistant.helpers.config_validation"
    ),
    "homeassistant.helpers.update_coordinator": _ha_helpers_update_coordinator,
    "homeassistant.helpers.entity_platform": types.ModuleType(
        "homeassistant.helpers.entity_platform"
    ),
}.items():
    sys.modules[mod_name] = mod
```

**Key rule**: This must appear at the top of `conftest.py` (or the test file) **before** any `from custom_components.opensky_ng.X import Y` statements.

### Preventing Real Network Calls

Modules like `airports.py` make HTTP calls at module import time (to fetch the airport lookup table). Mock `requests.get` at the module level in `conftest.py`:

```python
from unittest.mock import MagicMock, patch

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
```

### Handling Lazy Module Initialization

Some modules (e.g., `airports.py`) use `__getattr__` for lazy initialization so that `CACHE_PATH` can be set by `__init__.py` before the lookup is resolved. In tests, you must **pre-resolve** the lazy attribute to avoid triggering a network call:

```python
# In conftest.py, after the requests.get patch:
import custom_components.opensky_ng.airports as _airports_mod
_airports_mod.CACHE_PATH = None  # Disable file cache in tests
_airports_mod._AIRPORT_LOOKUP_CACHE = {
    "EGLL": ("Heathrow Airport", "London", "GB"),
    "KJFK": ("JFK Airport", "New York", "US"),
}
_ = _airports_mod.AIRPORT_LOOKUP  # Trigger lazy resolution with test data
```

If you need an empty lookup for a specific test, set `CACHE_PATH = None` and call `_ = airports.AIRPORT_LOOKUP` before the test runs.

### Testing Module-Level Functions

For pure functions that don't depend on HA (e.g., `_parse_response`, `_extract_airline`), import them directly from the component module. The `sys.modules` + `requests.get` mocks in `conftest.py` ensure these imports work without the full HA runtime or real network calls:

```python
def test_known_prefix(self):
    from custom_components.opensky_ng.coordinator import _extract_airline
    assert _extract_airline("UAL123") == "United Airlines"
```

### Key Patterns Summary

| Pattern | How |
|---------|-----|
| Mock `homeassistant` | `types.ModuleType` in `conftest.py`, before any component import |
| Mock `requests` | `patch("requests.get", ...)` at module level in `conftest.py` |
| Lazy module init | Pre-resolve via `._AIRPORT_LOOKUP_CACHE = {...}` then `_ = mod.AIRPORT_LOOKUP` |
| Pure function tests | `from custom_components.opensky_ng.X import func` — mocks handle the rest |
| Per-test network mocking | `with patch("requests.get", return_value=mock_resp):` |

## Coding Style

- Follow HA core style (PEP 8, type hints with `from __future__ import annotations`)
- Use `Final` for constants, `Protocol` where appropriate
- Use `CoordinatorEntity[CoordinatorType]` generic typing
- Translation files in `translations/` contain fully resolved strings
- Keep the integration self-contained - no external services beyond OpenSky API
