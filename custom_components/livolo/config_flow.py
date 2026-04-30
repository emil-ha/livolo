"""Config flow for Livolo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from .const import (
    APP_KEY,
    APP_SECRET,
    CONF_HAS_ENTITY_NAME,
    CONF_INVERT_COVER_DIRECTION,
    CONF_MOCK_MODE,
    DOMAIN,
)
from .livolo_client import LivoloClient
from .device_property_utils import has_curtain_cover

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required("country_code", default="DE"): str,
        vol.Required("app_key", default=APP_KEY): str,
        vol.Required("app_secret", default=APP_SECRET): str,
        vol.Optional(CONF_HAS_ENTITY_NAME, default=False): bool,
        vol.Optional(CONF_MOCK_MODE, default=False): bool,
    }
)


class LivoloConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Livolo."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return LivoloOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        # Check if already configured
        await self.async_set_unique_id(user_input[CONF_EMAIL])
        self._abort_if_unique_id_configured()

        try:
            client = LivoloClient(
                async_get_clientsession(self.hass),
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                user_input.get("country_code", "DE"),
                app_key=user_input.get("app_key") or APP_KEY,
                app_secret=user_input.get("app_secret") or APP_SECRET,
                mock_mode=bool(user_input.get(CONF_MOCK_MODE)),
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

        return self.async_create_entry(
            title=f"Livolo ({user_input[CONF_EMAIL]})",
            data=user_input,
            options={CONF_HAS_ENTITY_NAME: bool(user_input.get(CONF_HAS_ENTITY_NAME, False))},
        )


class LivoloOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Livolo options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the Livolo options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = dict(self._config_entry.options)
        invert_current: list[str] = list(current.get(CONF_INVERT_COVER_DIRECTION, []) or [])

        # Build a user-friendly map of curtain device ids -> device names.
        cover_devices: dict[str, str] = {}
        try:
            domain_data = self.hass.data.get(DOMAIN) or {}
            coordinators = (domain_data.get("coordinators") or {}) if isinstance(domain_data, dict) else {}
            coordinator = coordinators.get(self._config_entry.entry_id)
            devices = (coordinator.data or {}).get("devices", []) if coordinator else []
            for d in devices:
                if not has_curtain_cover(d):
                    continue
                iot_id = d.get("iotId") or d.get("elementId")
                if not iot_id:
                    continue
                name = d.get("nickName") or d.get("name") or iot_id
                cover_devices[iot_id] = str(name)
        except Exception:  # noqa: BLE001 - options UI should never crash
            _LOGGER.exception("Failed to build curtain device list for options flow")

        schema_dict: dict[Any, Any] = {
            vol.Optional(
                CONF_HAS_ENTITY_NAME,
                default=current.get(CONF_HAS_ENTITY_NAME, False),
            ): bool,
        }
        if cover_devices:
            schema_dict[
                vol.Optional(
                    CONF_INVERT_COVER_DIRECTION,
                    default=invert_current,
                )
            ] = cv.multi_select(cover_devices)

        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="init", data_schema=schema)
