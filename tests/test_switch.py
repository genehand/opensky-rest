"""Tests for the switch platform.

These tests mock the Home Assistant framework since it's not available
in the standalone test environment.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest

# ── Mock the entire homeassistant module tree ──────────────────────────


class _MockCoordinatorEntity:
    """Stand-in for CoordinatorEntity."""

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_added_to_hass(self):
        pass


class _MockSwitchEntity:
    """Stand-in for SwitchEntity."""

    def __class_getitem__(cls, item):
        return cls


class _MockRestoreEntity:
    """Stand-in for RestoreEntity.

    Tests control the returned last-state by setting ``_last_state`` on the
    instance before calling ``async_added_to_hass``.
    """

    _last_state: Any = None

    async def async_added_to_hass(self):
        pass

    async def async_get_last_state(self):
        return self._last_state

    def async_write_ha_state(self):
        pass


class _MockDataUpdateCoordinator:
    """Stand-in for DataUpdateCoordinator."""

    def __class_getitem__(cls, item):
        return cls


_ha_mock = MagicMock()
_ha_mock.const.Platform = MagicMock()
_ha_mock.const.Platform.SENSOR = "sensor"
_ha_mock.const.Platform.SWITCH = "switch"
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
_ha_mock.helpers.restore_state.RestoreEntity = _MockRestoreEntity
_ha_mock.config_entries.ConfigEntry = MagicMock
_ha_mock.core.HomeAssistant = MagicMock
_ha_mock.components = MagicMock()
_ha_mock.components.switch.SwitchEntity = _MockSwitchEntity

modules = {
    "homeassistant": _ha_mock,
    "homeassistant.const": _ha_mock.const,
    "homeassistant.exceptions": _ha_mock.exceptions,
    "homeassistant.helpers": _ha_mock.helpers,
    "homeassistant.helpers.config_validation": _ha_mock.helpers.config_validation,
    "homeassistant.helpers.update_coordinator": _ha_mock.helpers.update_coordinator,
    "homeassistant.helpers.entity_platform": _ha_mock.helpers.entity_platform,
    "homeassistant.helpers.device_registry": _ha_mock.helpers.device_registry,
    "homeassistant.helpers.restore_state": _ha_mock.helpers.restore_state,
    "homeassistant.config_entries": _ha_mock.config_entries,
    "homeassistant.core": _ha_mock.core,
    "homeassistant.components": _ha_mock.components,
    "homeassistant.components.switch": _ha_mock.components.switch,
}
for mod_name, mod in modules.items():
    sys.modules[mod_name] = mod

# Safe to import now
from custom_components.opensky_rest.switch import OpenSkyRestEnabledSwitch  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────

def _make_coordinator(fetching_enabled: bool = True):
    """Create a minimal mock coordinator."""
    coordinator = MagicMock()
    coordinator.fetching_enabled = fetching_enabled
    coordinator.config_entry = MagicMock()
    return coordinator


def _make_config_entry(entry_id: str = "test_entry"):
    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    config_entry.title = "OpenSky REST"
    return config_entry


def _make_switch(coordinator=None, config_entry=None):
    if coordinator is None:
        coordinator = _make_coordinator()
    if config_entry is None:
        config_entry = _make_config_entry()
    return OpenSkyRestEnabledSwitch(coordinator, config_entry)


def _fake_last_state(state_str: str):
    """Return a minimal fake HA State object."""
    s = MagicMock()
    s.state = state_str
    return s


# ── Tests ──────────────────────────────────────────────────────────────


class TestOpenSkyRestEnabledSwitch:
    """Tests for the enabled switch entity."""

    # ── Initialization ────────────────────────────────────────────────

    def test_default_enabled_on_init(self):
        """Switch should default to True before any state is restored."""
        switch = _make_switch()
        assert switch.is_on is True

    def test_unique_id_format(self):
        """Unique ID should include the config entry ID."""
        switch = _make_switch(config_entry=_make_config_entry("entry_xyz"))
        assert switch._attr_unique_id == "entry_xyz_opensky_rest_enabled"

    # ── RestoreEntity: state restoration ─────────────────────────────

    def test_restore_state_on(self):
        """async_added_to_hass restores an 'on' last state."""

        async def run():
            switch = _make_switch()
            switch._last_state = _fake_last_state("on")
            await switch.async_added_to_hass()
            assert switch.is_on is True
            assert switch.coordinator.fetching_enabled is True

        asyncio.run(run())

    def test_restore_state_off(self):
        """async_added_to_hass restores an 'off' last state."""

        async def run():
            switch = _make_switch()
            switch._last_state = _fake_last_state("off")
            await switch.async_added_to_hass()
            assert switch.is_on is False
            assert switch.coordinator.fetching_enabled is False

        asyncio.run(run())

    def test_restore_no_prior_state_defaults_on(self):
        """When there is no prior state, switch defaults to enabled (True)."""

        async def run():
            switch = _make_switch()
            switch._last_state = None  # No prior state
            await switch.async_added_to_hass()
            assert switch.is_on is True
            assert switch.coordinator.fetching_enabled is True

        asyncio.run(run())

    # ── Toggle behaviour ──────────────────────────────────────────────

    def test_turn_off_disables_coordinator(self):
        """Calling async_turn_off should set is_on=False and coordinator flag=False."""

        async def run():
            coordinator = _make_coordinator(fetching_enabled=True)
            switch = _make_switch(coordinator=coordinator)
            await switch.async_turn_off()
            assert switch.is_on is False
            assert coordinator.fetching_enabled is False

        asyncio.run(run())

    def test_turn_on_enables_coordinator(self):
        """Calling async_turn_on should set is_on=True and coordinator flag=True."""

        async def run():
            coordinator = _make_coordinator(fetching_enabled=False)
            switch = _make_switch(coordinator=coordinator)
            switch._is_on = False  # Simulate disabled state
            await switch.async_turn_on()
            assert switch.is_on is True
            assert coordinator.fetching_enabled is True

        asyncio.run(run())

    def test_turn_off_then_on_roundtrip(self):
        """Toggle off then on should restore enabled state."""

        async def run():
            coordinator = _make_coordinator(fetching_enabled=True)
            switch = _make_switch(coordinator=coordinator)
            await switch.async_turn_off()
            assert switch.is_on is False
            await switch.async_turn_on()
            assert switch.is_on is True
            assert coordinator.fetching_enabled is True

        asyncio.run(run())

    # ── Coordinator short-circuit ─────────────────────────────────────

    def test_coordinator_fetching_enabled_flag_default(self):
        """Coordinator mock used by switch should start with fetching_enabled=True."""
        coordinator = _make_coordinator(fetching_enabled=True)
        switch = _make_switch(coordinator=coordinator)
        # After construction the coordinator's flag is still True
        assert switch.coordinator.fetching_enabled is True

    def test_coordinator_fetching_enabled_toggled_off(self):
        """After turn_off, coordinator.fetching_enabled should be False."""

        async def run():
            coordinator = _make_coordinator(fetching_enabled=True)
            switch = _make_switch(coordinator=coordinator)
            await switch.async_turn_off()
            assert coordinator.fetching_enabled is False

        asyncio.run(run())
