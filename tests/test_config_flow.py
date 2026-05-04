"""Tests for the config flow.

These tests mock the Home Assistant framework since it's not available
in the standalone test environment.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest


class _MockConfigFlow:
    """Stand-in for ConfigFlow that accepts domain= kwarg."""

    DOMAIN = "opensky_ng"
    VERSION = 1

    def __init_subclass__(cls, **kwargs):
        if "domain" in kwargs:
            cls.DOMAIN = kwargs["domain"]

    @staticmethod
    def async_get_options_flow(config_entry):
        raise NotImplementedError

    def async_create_entry(self, *, title, data, options=None):
        return {
            "type": "create_entry",
            "title": title,
            "data": data,
            "options": options,
        }

    def async_show_form(
        self, *, step_id, data_schema=None, errors=None, **kwargs
    ):
        return {
            "type": "show_form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors,
            **kwargs,
        }

    def add_suggested_values_to_schema(self, schema, suggested_values):
        return schema


class _MockOptionsFlow:
    """Stand-in for OptionsFlow."""

    def __init__(self):
        self.hass = MagicMock()
        self.config_entry = MagicMock()

    def async_create_entry(self, *, data):
        raise NotImplementedError

    def async_show_form(
        self, *, step_id, data_schema=None, errors=None, **kwargs
    ):
        raise NotImplementedError

    def add_suggested_values_to_schema(self, schema, suggested_values):
        return schema


class _MockConfigEntry:
    pass


# ── Mock the entire homeassistant module tree ──────────────────────────
# This must happen before any imports from custom_components.

_ha_mock = MagicMock()
_ha_mock.const.Platform = MagicMock()
_ha_mock.const.Platform.SENSOR = "sensor"
_ha_mock.const.CONF_LATITUDE = "latitude"
_ha_mock.const.CONF_LONGITUDE = "longitude"
_ha_mock.const.CONF_RADIUS = "radius"
_ha_mock.exceptions.ConfigEntryNotReady = Exception
_ha_mock.helpers.config_validation = MagicMock()
_ha_mock.helpers.config_validation.latitude = lambda v: float(v)
_ha_mock.helpers.config_validation.longitude = lambda v: float(v)
_ha_mock.helpers.update_coordinator = MagicMock()
_ha_mock.helpers.entity_platform = MagicMock()
_ha_mock.helpers.device_registry = MagicMock()
_ha_mock.helpers.device_registry.DeviceEntryType = MagicMock()
_ha_mock.helpers.device_registry.DeviceEntryType.SERVICE = "service"
_ha_mock.helpers.device_registry.DeviceInfo = MagicMock()
_ha_mock.config_entries = MagicMock()
_ha_mock.config_entries.ConfigEntry = _MockConfigEntry
_ha_mock.config_entries.ConfigFlow = _MockConfigFlow
_ha_mock.config_entries.ConfigFlowResult = dict
_ha_mock.config_entries.OptionsFlow = _MockOptionsFlow
_ha_mock.config_entries.ConfigEntry = _MockConfigEntry
_ha_mock.core.HomeAssistant = MagicMock()
_ha_mock.core.callback = lambda f: f  # Make callback a pass-through

modules = {
    "homeassistant": _ha_mock,
    "homeassistant.const": _ha_mock.const,
    "homeassistant.exceptions": _ha_mock.exceptions,
    "homeassistant.helpers": _ha_mock.helpers,
    "homeassistant.helpers.config_validation": _ha_mock.helpers.config_validation,
    "homeassistant.helpers.update_coordinator": _ha_mock.helpers.update_coordinator,
    "homeassistant.helpers.entity_platform": _ha_mock.helpers.entity_platform,
    "homeassistant.helpers.device_registry": _ha_mock.helpers.device_registry,
    "homeassistant.config_entries": _ha_mock.config_entries,
    "homeassistant.core": _ha_mock.core,
    "homeassistant.components.sensor": MagicMock(),
    "homeassistant.components.sensor.const": MagicMock(),
}
for mod_name, mod in modules.items():
    sys.modules[mod_name] = mod

# Now safe to import from the component
from custom_components.opensky_ng.config_flow import (
    OpenSkyRestConfigFlowHandler,
    OpenSkyRestOptionsFlowHandler,
)
from custom_components.opensky_ng.const import DEFAULT_NAME


class TestOpenSkyRestConfigFlowHandler:
    """Tests for the initial config flow."""

    def _make_flow(self) -> OpenSkyRestConfigFlowHandler:
        """Create a config flow handler with a mocked hass."""
        flow = OpenSkyRestConfigFlowHandler()
        flow.hass = MagicMock()
        flow.hass.config.latitude = 52.52
        flow.hass.config.longitude = 13.405
        flow.hass.async_add_executor_job = AsyncMock()
        return flow

    def test_domain(self):
        """The flow handler should be registered under the correct domain."""
        assert OpenSkyRestConfigFlowHandler.DOMAIN == "opensky_ng"

    def test_version(self):
        """Config flow version should be 1."""
        assert OpenSkyRestConfigFlowHandler.VERSION == 1

    def test_options_flow_type(self):
        """async_get_options_flow should return an OptionsFlow handler."""
        flow = self._make_flow()
        mock_entry = MagicMock()
        options_flow = flow.async_get_options_flow(mock_entry)
        assert isinstance(options_flow, OpenSkyRestOptionsFlowHandler)

    @pytest.mark.asyncio
    async def test_initial_no_oauth_success(self):
        """Initial setup without OAuth2 should succeed (anonymous mode)."""
        flow = self._make_flow()

        with patch.object(flow, "async_create_entry") as mock_create:
            await flow.async_step_user(
                user_input={
                    "latitude": 40.0,
                    "longitude": -74.0,
                    "radius": 50_000,
                    "altitude": 0,
                }
            )
            mock_create.assert_called_once_with(
                title=DEFAULT_NAME,
                data={"latitude": 40.0, "longitude": -74.0},
                options={
                    "radius": 50_000,
                    "altitude": 0,
                    "client_id": "",
                    "client_secret": "",
                },
            )

    @pytest.mark.asyncio
    async def test_initial_missing_client_secret(self):
        """Only client_id without client_secret should show an error."""
        flow = self._make_flow()

        with patch.object(flow, "async_show_form") as mock_show:
            await flow.async_step_user(
                user_input={
                    "latitude": 40.0,
                    "longitude": -74.0,
                    "radius": 50_000,
                    "altitude": 0,
                    "client_id": "my-id",
                }
            )
            kwargs = mock_show.call_args[1]
            assert kwargs["errors"]["base"] == "oauth_missing_fields"

    @pytest.mark.asyncio
    async def test_initial_missing_client_id(self):
        """Only client_secret without client_id should show an error."""
        flow = self._make_flow()

        with patch.object(flow, "async_show_form") as mock_show:
            await flow.async_step_user(
                user_input={
                    "latitude": 40.0,
                    "longitude": -74.0,
                    "radius": 50_000,
                    "altitude": 0,
                    "client_secret": "my-secret",
                }
            )
            kwargs = mock_show.call_args[1]
            assert kwargs["errors"]["base"] == "oauth_missing_fields"

    @pytest.mark.asyncio
    async def test_initial_with_oauth_success(self):
        """Valid OAuth2 credentials in initial setup should succeed."""
        flow = self._make_flow()

        # Mock the async execution — simulate a successful API call
        mock_states = MagicMock()
        mock_states.states = []
        flow.hass.async_add_executor_job = AsyncMock(return_value=mock_states)

        with (
            patch("custom_components.opensky_ng.config_flow.TokenManager"),
            patch("custom_components.opensky_ng.config_flow.OpenSkyApi"),
            patch.object(flow, "async_create_entry") as mock_create,
        ):
            await flow.async_step_user(
                user_input={
                    "latitude": 40.0,
                    "longitude": -74.0,
                    "radius": 50_000,
                    "altitude": 0,
                    "client_id": "valid-id",
                    "client_secret": "valid-secret",
                }
            )
            mock_create.assert_called_once_with(
                title=DEFAULT_NAME,
                data={"latitude": 40.0, "longitude": -74.0},
                options={
                    "radius": 50_000,
                    "altitude": 0,
                    "client_id": "valid-id",
                    "client_secret": "valid-secret",
                },
            )

    @pytest.mark.asyncio
    async def test_initial_with_oauth_failure(self):
        """Invalid OAuth2 credentials in initial setup should show an error."""
        flow = self._make_flow()

        # Simulate failed API call (returns None)
        flow.hass.async_add_executor_job = AsyncMock(return_value=None)

        with (
            patch("custom_components.opensky_ng.config_flow.TokenManager"),
            patch("custom_components.opensky_ng.config_flow.OpenSkyApi"),
            patch.object(flow, "async_show_form") as mock_show,
        ):
            await flow.async_step_user(
                user_input={
                    "latitude": 40.0,
                    "longitude": -74.0,
                    "radius": 50_000,
                    "altitude": 0,
                    "client_id": "bad-id",
                    "client_secret": "bad-secret",
                }
            )
            kwargs = mock_show.call_args[1]
            assert kwargs["errors"]["base"] == "invalid_auth"

    @pytest.mark.asyncio
    async def test_initial_form_has_oauth_fields(self):
        """The initial form should include optional OAuth2 fields."""
        flow = self._make_flow()

        result = await flow.async_step_user(user_input=None)
        schema = result.get("data_schema")
        # The schema should contain client_id and client_secret
        assert schema is not None


class TestOpenSkyRestOptionsFlowHandler:
    """Tests for the options flow."""

    @pytest.mark.asyncio
    async def test_options_missing_both_oauth_fields(self):
        """Submitting only one OAuth2 field should show an error."""
        flow = OpenSkyRestOptionsFlowHandler()
        flow.hass = MagicMock()
        flow.hass.async_add_executor_job = AsyncMock()

        with patch.object(flow, "async_show_form") as mock_show:
            await flow.async_step_init(
                user_input={
                    "radius": 100_000,
                    "altitude": 0,
                    "client_id": "my-id",
                    # client_secret missing
                }
            )
            # Should show error because client_secret is missing
            kwargs = mock_show.call_args[1]
            assert "oauth_missing_fields" in kwargs.get("errors", {}).get("base", "")

    @pytest.mark.asyncio
    async def test_options_missing_both_oauth_fields_reverse(self):
        """Submitting only client_secret should also show an error."""
        flow = OpenSkyRestOptionsFlowHandler()
        flow.hass = MagicMock()
        flow.hass.async_add_executor_job = AsyncMock()

        with patch.object(flow, "async_show_form") as mock_show:
            await flow.async_step_init(
                user_input={
                    "radius": 100_000,
                    "altitude": 0,
                    "client_secret": "my-secret",
                    # client_id missing
                }
            )
            kwargs = mock_show.call_args[1]
            assert "oauth_missing_fields" in kwargs.get("errors", {}).get("base", "")

    @pytest.mark.asyncio
    async def test_options_no_oauth_provided(self):
        """No OAuth2 fields should be valid (anonymous mode)."""
        flow = OpenSkyRestOptionsFlowHandler()
        flow.hass = MagicMock()
        flow.hass.async_add_executor_job = AsyncMock()

        with patch.object(flow, "async_create_entry") as mock_create:
            result = await flow.async_step_init(
                user_input={
                    "radius": 50_000,
                    "altitude": 0,
                }
            )
            mock_create.assert_called_once_with(
                data={
                    "radius": 50_000,
                    "altitude": 0,
                }
            )

    @pytest.mark.asyncio
    async def test_options_with_oauth_success(self):
        """Valid OAuth2 credentials should be accepted."""
        flow = OpenSkyRestOptionsFlowHandler()
        flow.hass = MagicMock()

        # Mock the async execution — simulate a successful API call
        mock_states = MagicMock()
        mock_states.states = []
        flow.hass.async_add_executor_job = AsyncMock(return_value=mock_states)

        with (
            patch("custom_components.opensky_ng.config_flow.TokenManager"),
            patch("custom_components.opensky_ng.config_flow.OpenSkyApi"),
            patch.object(flow, "async_create_entry") as mock_create,
        ):
            result = await flow.async_step_init(
                user_input={
                    "radius": 50_000,
                    "altitude": 0,
                    "client_id": "valid-id",
                    "client_secret": "valid-secret",
                }
            )
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_options_with_oauth_failure(self):
        """Invalid OAuth2 credentials should show an error."""
        flow = OpenSkyRestOptionsFlowHandler()
        flow.hass = MagicMock()

        # Simulate failed API call (returns None)
        flow.hass.async_add_executor_job = AsyncMock(return_value=None)

        with (
            patch("custom_components.opensky_ng.config_flow.TokenManager"),
            patch("custom_components.opensky_ng.config_flow.OpenSkyApi"),
            patch.object(flow, "async_show_form") as mock_show,
        ):
            await flow.async_step_init(
                user_input={
                    "radius": 50_000,
                    "altitude": 0,
                    "client_id": "bad-id",
                    "client_secret": "bad-secret",
                }
            )
            kwargs = mock_show.call_args[1]
            assert kwargs["errors"]["base"] == "invalid_auth"
