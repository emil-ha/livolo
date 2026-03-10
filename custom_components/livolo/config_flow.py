"""Config flow for Livolo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import APP_KEY, APP_SECRET, DOMAIN
from .livolo_client import LivoloClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required("country_code", default="DE"): str,
        vol.Required("app_key", default=APP_KEY): str,
        vol.Required("app_secret", default=APP_SECRET): str,
    }
)


class LivoloConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Livolo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            client = LivoloClient(
                async_get_clientsession(self.hass),
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                user_input.get("country_code", "DE"),
                app_key=user_input.get("app_key") or APP_KEY,
                app_secret=user_input.get("app_secret") or APP_SECRET,
            )
            session = await client.login()
            if not session:
                errors["base"] = "invalid_auth"
        except Exception as err:
            _LOGGER.exception("Unexpected exception during login: %s", err)
            errors["base"] = "unknown"
            # Re-raise to get proper error handling
            if not errors:
                raise

        if errors:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        # Check if already configured
        await self.async_set_unique_id(user_input[CONF_EMAIL])
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Livolo ({user_input[CONF_EMAIL]})",
            data=user_input,
        )
