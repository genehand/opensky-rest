"""Switch platform for the OpenSky REST integration.

Provides an "Enabled" toggle that pauses/resumes API fetching.
State is persisted across HA restarts via RestoreEntity.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    TRANSLATION_KEY_ENABLED,
)
from .coordinator import OpenSkyRestDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Default state when no prior saved state is found
_DEFAULT_ENABLED = True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the OpenSky REST switch platform."""
    coordinator: OpenSkyRestDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OpenSkyRestEnabledSwitch(coordinator, entry),
        ],
    )


class OpenSkyRestEnabledSwitch(
    CoordinatorEntity[OpenSkyRestDataUpdateCoordinator],
    SwitchEntity,
    RestoreEntity,
):
    """Switch to enable or disable OpenSky REST API fetching.

    When turned off the coordinator's ``_async_update_data`` short-circuits
    and returns an empty result, suppressing all API calls, background
    enrichments, and entry/exit events.  The polling timer keeps running so
    that turning the switch back on immediately resumes fetching on the next
    scheduled tick (or after a manual refresh).

    State is persisted via ``RestoreEntity`` so the last-known on/off state
    survives HA restarts.
    """

    _attr_has_entity_name = True
    _attr_translation_key = TRANSLATION_KEY_ENABLED

    def __init__(
        self,
        coordinator: OpenSkyRestDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{config_entry.entry_id}_opensky_ng_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}")},
            manufacturer=MANUFACTURER,
            name=config_entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
        # Optimistic local state — will be overridden by RestoreEntity on startup.
        self._is_on: bool = _DEFAULT_ENABLED

    async def async_added_to_hass(self) -> None:
        """Restore the last saved state when HA starts."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            restored = last_state.state == "on"
            _LOGGER.debug(
                "Restoring OpenSky REST enabled switch state: %s → %s",
                last_state.state,
                restored,
            )
            self._is_on = restored
        else:
            _LOGGER.debug(
                "No prior state found for OpenSky REST enabled switch; defaulting to %s",
                _DEFAULT_ENABLED,
            )
            self._is_on = _DEFAULT_ENABLED

        # Sync the coordinator flag with the restored state
        self.coordinator.fetching_enabled = self._is_on

    @property
    def is_on(self) -> bool:
        """Return True when fetching is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable API fetching."""
        self._is_on = True
        self.coordinator.fetching_enabled = True
        self.async_write_ha_state()
        _LOGGER.debug("OpenSky REST fetching enabled")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable API fetching."""
        self._is_on = False
        self.coordinator.fetching_enabled = False
        self.async_write_ha_state()
        _LOGGER.debug("OpenSky REST fetching disabled")
