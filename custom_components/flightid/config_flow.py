"""Config flow for the flightID integration."""

from __future__ import annotations

from typing import Any

from opensky_api import OpenSkyApi, TokenManager
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ALTITUDE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    DEFAULT_ALTITUDE,
    DEFAULT_NAME,
    DOMAIN,
)


class FlightIdConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow handler for flightID."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> FlightIdOptionsFlowHandler:
        """Get the options flow for this handler."""
        return FlightIdOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate OAuth2 credentials if provided
            client_id = user_input.get(CONF_CLIENT_ID)
            client_secret = user_input.get(CONF_CLIENT_SECRET)

            if (client_id and not client_secret) or (
                client_secret and not client_id
            ):
                errors["base"] = "oauth_missing_fields"
            elif client_id and client_secret:
                try:
                    token_manager = TokenManager(
                        client_id=client_id,
                        client_secret=client_secret,
                    )
                    api = OpenSkyApi(token_manager=token_manager)
                    result = await self.hass.async_add_executor_job(api.get_states)
                    if result is None:
                        errors["base"] = "invalid_auth"
                except Exception:  # pylint: disable=broad-except
                    errors["base"] = "invalid_auth"

            if not errors:
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={
                        CONF_LATITUDE: user_input[CONF_LATITUDE],
                        CONF_LONGITUDE: user_input[CONF_LONGITUDE],
                    },
                    options={
                        CONF_RADIUS: user_input[CONF_RADIUS],
                        CONF_ALTITUDE: user_input.get(CONF_ALTITUDE, DEFAULT_ALTITUDE),
                        CONF_CLIENT_ID: user_input.get(CONF_CLIENT_ID) or "",
                        CONF_CLIENT_SECRET: user_input.get(CONF_CLIENT_SECRET) or "",
                    },
                )

        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_RADIUS, default=100): vol.Coerce(float),
                        vol.Required(CONF_LATITUDE): cv.latitude,
                        vol.Required(CONF_LONGITUDE): cv.longitude,
                        vol.Optional(CONF_ALTITUDE): vol.Coerce(float),
                        vol.Optional(CONF_CLIENT_ID): str,
                        vol.Optional(CONF_CLIENT_SECRET): str,
                    }
                ),
                {
                    CONF_LATITUDE: self.hass.config.latitude,
                    CONF_LONGITUDE: self.hass.config.longitude,
                    CONF_ALTITUDE: DEFAULT_ALTITUDE,
                },
            ),
        )


class FlightIdOptionsFlowHandler(OptionsFlow):
    """flightID options flow handler."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate OAuth2 credentials if provided
            client_id = user_input.get(CONF_CLIENT_ID)
            client_secret = user_input.get(CONF_CLIENT_SECRET)

            if (client_id and not client_secret) or (
                client_secret and not client_id
            ):
                errors["base"] = "oauth_missing_fields"
            elif client_id and client_secret:
                # Test the credentials
                try:
                    token_manager = TokenManager(
                        client_id=client_id,
                        client_secret=client_secret,
                    )
                    api = OpenSkyApi(token_manager=token_manager)
                    result = await self.hass.async_add_executor_job(api.get_states)
                    if result is None:
                        errors["base"] = "invalid_auth"
                except Exception:  # pylint: disable=broad-except
                    errors["base"] = "invalid_auth"

            if not errors:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_RADIUS): vol.Coerce(float),
                        vol.Optional(CONF_ALTITUDE): vol.Coerce(float),
                        vol.Optional(CONF_CLIENT_ID): str,
                        vol.Optional(CONF_CLIENT_SECRET): str,
                    }
                ),
                user_input or self.config_entry.options,
            ),
        )
