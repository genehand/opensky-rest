# FlightID

Home Assistant integration that provides real-time aircraft tracking data from the [OpenSky Network](https://opensky-network.org).  This is combined with flight and airport details from [Virtual Radar Server](https://www.virtualradarserver.co.uk/) and images from [Planespotters.net](https://www.planespotters.net/).

Similar to the original [OpenSky integration](https://www.home-assistant.io/integrations/opensky/) but uses the newer OAuth2 API. Provides a sensor with a list of airborne aircraft including callsign, airline, altitude, speed, heading, origin country, departure/arrival cities, and photo links.

## Installation

### Home Assistant Community Store (HACS)

1. Ensure HACS is installed in Home Assistant
2. Add this repository as a custom repository (type: Integration)
3. Search for "FlightID" and install
4. Restart Home Assistant
5. Add the integration via **Settings > Devices & services > Add Integration**

## Configuration

After adding the integration, configure the following:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| Latitude | Yes | HA device location | Center latitude of monitoring area |
| Longitude | Yes | HA device location | Center longitude of monitoring area |
| Radius | Yes | 100 m | Monitoring radius in meters |
| Altitude | No | None | Max altitude filter in meters (0 = no limit) |
| Client ID | No | — | OAuth2 client ID from OpenSky account |
| Client Secret | No | — | OAuth2 client secret |

## Authentication

### OAuth2 (recommended)

Create a client credential with the [OpenSky Network](https://opensky-network.org/my-opensky/account) then enter the Client ID and Client Secret.

- 4,000 API credits per day
- 30-second polling interval
  - **TODO**: make this configurable, assumes disabled at night

### Anonymous

- 400 API credits per day
- ~1 call every 5 minutes

## Known Limitations

- OpenSky does not provide scheduled departure/arrival times

## Use of AI

Definitely vibe-coded, take it or leave it!