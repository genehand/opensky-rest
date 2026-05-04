"""Sensor platform for the OpenSky REST integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_AIRCRAFT,
    ATTR_COUNT,
    ATTR_STATS,
    DOMAIN,
    MANUFACTURER,
    TRANSLATION_KEY_FLIGHTS,
)
from .coordinator import OpenSkyRestDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the OpenSky REST sensor platform."""
    coordinator: OpenSkyRestDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    async_add_entities(
        [
            OpenSkyRestSensor(
                coordinator,
                entry,
            )
        ],
    )


class OpenSkyRestSensor(
    CoordinatorEntity[OpenSkyRestDataUpdateCoordinator], SensorEntity
):
    """Representation of an OpenSky REST sensor."""

    _attr_attribution = (
        "Information provided by the OpenSky Network (https://opensky-network.org)"
    )
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = TRANSLATION_KEY_FLIGHTS
    _attr_native_unit_of_measurement = "flights"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: OpenSkyRestDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{config_entry.entry_id}_opensky_rest"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}")},
            manufacturer=MANUFACTURER,
            name=config_entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int:
        """Return the flight count."""
        if self.coordinator.data is None:
            return 0
        return self.coordinator.data.get(ATTR_COUNT, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes with full aircraft data."""
        if self.coordinator.data is None:
            return {}

        data = self.coordinator.data

        # Build simplified aircraft list for attributes (to keep size manageable)
        aircraft_summary = []
        for ac in data.get(ATTR_AIRCRAFT, []):
            summary = {
                "callsign": ac.get("callsign"),
                "airline": ac.get("airline"),
                "altitude_ft": ac.get("altitude_ft"),
                "speed_kts": ac.get("speed_kts"),
                "heading": ac.get("true_track"),
                "vertical_rate": ac.get("vertical_rate"),
                "latitude": ac.get("latitude"),
                "longitude": ac.get("longitude"),
                "origin_country": ac.get("origin_country"),
                "on_ground": ac.get("on_ground"),
                "category": ac.get("category_name"),
                "icao24": ac.get("icao24"),
            }
            aircraft_summary.append(summary)

        attrs: dict[str, Any] = {
            "aircraft": aircraft_summary,
            "total_aircraft": len(aircraft_summary),
        }

        # Add statistics
        stats = data.get(ATTR_STATS, {})
        if stats:
            attrs["avg_altitude_ft"] = stats.get("avg_altitude_ft")
            attrs["avg_speed_kts"] = stats.get("avg_speed_kts")
            attrs["max_speed_kts"] = stats.get("max_speed_kts")
            attrs["highest_aircraft"] = stats.get("highest_callsign")
            attrs["highest_altitude_ft"] = stats.get("highest_altitude_ft")
            attrs["fastest_aircraft"] = stats.get("fastest_callsign")
            attrs["fastest_speed_kts"] = stats.get("fastest_speed_kts")
            attrs["airlines"] = stats.get("airlines", {})

        return attrs
