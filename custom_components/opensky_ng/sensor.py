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
    ATTR_AIRCRAFT_IMAGE_URL,
    ATTR_ARRIVAL_CITY,
    ATTR_ARRIVAL_COUNTRY,
    ATTR_COUNT,
    ATTR_DEPARTURE_CITY,
    ATTR_DEPARTURE_COUNTRY,
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
        self._attr_unique_id = f"{config_entry.entry_id}_opensky_ng"
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
                "image_url": ac.get(ATTR_AIRCRAFT_IMAGE_URL),
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
                "departure_city": ac.get(ATTR_DEPARTURE_CITY),
                "departure_country": ac.get(ATTR_DEPARTURE_COUNTRY),
                "arrival_city": ac.get(ATTR_ARRIVAL_CITY),
                "arrival_country": ac.get(ATTR_ARRIVAL_COUNTRY),
            }
            aircraft_summary.append(summary)

        attrs: dict[str, Any] = {
            "aircraft": aircraft_summary,
        }

        attrs["attribution"] = "Data from the OpenSky Network, Virtual Radar Server, and Planespotters.net"

        return attrs

    @property
    def entity_picture(self) -> str | None:
        """Return the best available aircraft image as the entity picture.

        Uses the image from the fastest aircraft if available, otherwise
        falls back to the highest aircraft.
        """
        if self.coordinator.data is None:
            return None
        aircraft_list = self.coordinator.data.get(ATTR_AIRCRAFT, [])
        if not aircraft_list:
            return None

        # Prefer the fastest aircraft's image
        fastest = max(
            aircraft_list,
            key=lambda a: a.get("speed_kts") or 0,
        )
        image_url = fastest.get(ATTR_AIRCRAFT_IMAGE_URL)
        if image_url:
            return image_url

        # Fallback to highest aircraft
        highest = max(
            aircraft_list,
            key=lambda a: a.get("altitude_ft") or 0,
        )
        return highest.get(ATTR_AIRCRAFT_IMAGE_URL)
