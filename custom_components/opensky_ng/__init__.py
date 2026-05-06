"""The OpenSky REST component."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from . import airports
from .const import DOMAIN, PLATFORMS
from .coordinator import OpenSkyRestDataUpdateCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _resolve_airport_lookup() -> None:
    """Resolve AIRPORT_LOOKUP in an executor thread to avoid blocking the event loop."""
    _ = airports.AIRPORT_LOOKUP


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenSky REST from a config entry."""
    # Set cache path before resolving AIRPORT_LOOKUP so the file cache
    # is used instead of a raw network fetch.
    airports.CACHE_PATH = hass.config.path(
        ".storage", "opensky_ng_airports.json"
    )

    # Force eager resolution of the airport lookup table so it is ready
    # for the very first poll cycle.  This triggers the lazy __getattr__
    # with CACHE_PATH already set.
    await hass.async_add_executor_job(_resolve_airport_lookup)

    coordinator = OpenSkyRestDataUpdateCoordinator(hass, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Failed to connect to OpenSky API: {exc}"
        ) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload OpenSky REST config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
