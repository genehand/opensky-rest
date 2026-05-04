# OpenSky REST - Home Assistant Custom Integration

## Overview

This project is a **custom Home Assistant integration** that provides real-time aircraft tracking data from the [OpenSky Network](https://opensky-network.org) REST API. It wraps the official [`opensky-api`](https://github.com/openskynetwork/opensky-api) Python library (v1.4.0) in HA's `async_add_executor_job` pattern to keep the event loop responsive.

The integration monitors a configurable geographic area (bounding box defined by lat/lon/radius) and exposes a sensor showing the number of aircraft with rich attributes (callsign, airline, registration, altitude, speed, heading, origin country, Planespotters link, etc.). It also fires events when aircraft enter or leave the monitored airspace.

## Directory Structure

```
opensky-rest/
├── AGENTS.md                          # This file
├── custom_components/
│   └── opensky_rest/
│       ├── __init__.py                # HA entry point: async_setup_entry / async_unload_entry
│       ├── manifest.json              # Metadata: domain, version, pip dependency
│       ├── airports.py                # Airport ICAO → (name, city, country) lookup (1170 large airports)
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

Following the existing `opensky` integration pattern, a single sensor entity (`sensor.opensky_rest_flight_count`) shows the flight count as its state, with all aircraft data and statistics in `extra_state_attributes`.

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

- **`sensor.opensky_rest_flight_count`**: Number of airborne aircraft in the monitored area
  - State class: `measurement`
  - Unit: `flights`
  - Attributes: full aircraft list (with per-aircraft registration, Planespotters URLs, departure/arrival cities), avg altitude/speed, highest/fastest aircraft, airline breakdown

### Events

- **`opensky_rest_entry`**: Fired when an aircraft enters the monitored airspace
  - Event data: callsign, airline, altitude, position, icao24, origin_country, speed, heading, registration, image_url, departure/arrival airport/city/country
- **`opensky_rest_exit`**: Fired when an aircraft leaves the monitored airspace
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

## Coding Style

- Follow HA core style (PEP 8, type hints with `from __future__ import annotations`)
- Use `Final` for constants, `Protocol` where appropriate
- Use `CoordinatorEntity[CoordinatorType]` generic typing
- Translation files in `translations/` contain fully resolved strings
- Keep the integration self-contained - no external services beyond OpenSky API
