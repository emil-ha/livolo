"""Data update coordinator for Livolo."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import APP_KEY, APP_SECRET, CONF_MOCK_MODE, DOMAIN, TOKEN_EXPIRY_BUFFER_MS
from .livolo_client import LivoloClient
from .mqtt_client import LivoloMqttClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)
# Delay before re-reading state from the cloud after a command. Reading immediately
# returns the old (not yet reported) value and the entity flips back.
POST_COMMAND_REFRESH_DELAY = 5


class LivoloDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Livolo data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.hass = hass
        self.client = LivoloClient(
            async_get_clientsession(hass),
            entry.data["email"],
            entry.data["password"],
            entry.data.get("country_code", "DE"),
            app_key=entry.data.get("app_key") or APP_KEY,
            app_secret=entry.data.get("app_secret") or APP_SECRET,
            mock_mode=bool(entry.data.get(CONF_MOCK_MODE)),
        )
        self.mqtt_client: LivoloMqttClient | None = None
        self._post_command_refresh_unsub: CALLBACK_TYPE | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict:
        """Fetch data from Livolo."""
        try:
            # Ensure we're logged in
            session_data = self.client.get_session_data()
            if not session_data:
                await self.client.login()
                # If MQTT is already running for some reason, ensure it has the new session data
                await self._update_mqtt_token()
            elif not self.client.is_mock_mode():
                # Check if token needs refresh
                expires_at = session_data.get("iotTokenExpiresAt", 0)
                if expires_at and expires_at <= int(time.time() * 1000) + TOKEN_EXPIRY_BUFFER_MS:
                    _LOGGER.debug("Token expired or expiring soon, refreshing...")
                    refreshed = await self.client.refresh_token()
                    if not refreshed:
                        _LOGGER.warning("Token refresh failed, re-logging in...")
                        await self.client.login()
                    # Update MQTT client with new token if connected
                    await self._update_mqtt_token()

            # Get devices
            devices = await self.client.get_devices()
            # get_devices() can trigger refresh/re-login via LivoloClient retry logic;
            # keep MQTT session data in sync even if refresh didn't happen in the pre-check.
            await self._update_mqtt_token()

            # Build gateway → devices mapping using /subdevices/list
            gateway_to_devices: dict[str, list[str]] = {}
            device_element_ids = {d.get("iotId") or d.get("elementId") for d in devices if d.get("iotId") or d.get("elementId")}
            
            # Find all gateways
            gateways = [
                d for d in devices
                if (d.get("nodeType") == "GATEWAY" or d.get("categoryKey") == "GeneralGateway")
            ]
            
            # Query each gateway for its subdevices
            for gateway in gateways:
                gateway_id = gateway.get("iotId") or gateway.get("elementId")
                if not gateway_id:
                    continue
                try:
                    subdevices = await self.client.get_gateway_subdevices(gateway_id)
                    # Extract elementIds from subdevices
                    subdevice_ids = []
                    for subdevice in subdevices:
                        subdevice_id = subdevice.get("iotId") or subdevice.get("elementId")
                        if subdevice_id and subdevice_id in device_element_ids:
                            subdevice_ids.append(subdevice_id)
                    if subdevice_ids:
                        gateway_to_devices[gateway_id] = subdevice_ids
                        _LOGGER.debug("Gateway %s has %d subdevices", gateway_id, len(subdevice_ids))
                except Exception as e:
                    _LOGGER.warning("Failed to get subdevices for gateway %s: %s", gateway_id, e)

            # Start MQTT client if we have gateway credentials (or restart it if it failed to start)
            session_data = self.client.get_session_data()
            if self.mqtt_client and not self.mqtt_client.is_running():
                _LOGGER.warning("MQTT client is not running, restarting")
                await self.mqtt_client.disconnect()
                self.mqtt_client = None
            if session_data and session_data.get("gatewayCredentials") and not self.mqtt_client:
                # Initialize devices cache in MQTT client before connecting
                devices_cache = {d.get("iotId") or d.get("elementId"): d.copy() for d in devices}
                self.mqtt_client = LivoloMqttClient(
                    session_data,
                    self._handle_mqtt_update,
                    self.hass,
                )
                self.mqtt_client._devices_cache = devices_cache
                await self.mqtt_client.connect()

            return {
                "devices": self._merge_newer_properties(devices),
                "gateway_to_devices": gateway_to_devices,  # Add mapping to coordinator data
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Livolo API: {err}") from err

    def _handle_mqtt_update(self, data: dict[str, Any]) -> None:
        """Handle MQTT update (called from MQTT thread)."""
        # Schedule the update on the Home Assistant event loop
        self.hass.loop.call_soon_threadsafe(self._async_handle_mqtt_update, data)
    
    def _merge_newer_properties(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep property values that are newer than what the REST poll returned.

        An MQTT push can arrive while a poll is in flight; without this the poll
        result would overwrite the fresh value with the stale cloud snapshot.
        """
        if not self.data:
            return devices
        old_by_id = {
            d.get("iotId") or d.get("elementId"): d for d in self.data.get("devices", [])
        }
        for device in devices:
            old = old_by_id.get(device.get("iotId") or device.get("elementId"))
            if not old:
                continue
            old_props = {p.get("identifier"): p for p in old.get("propertyList") or []}
            for prop in device.get("propertyList") or []:
                old_prop = old_props.get(prop.get("identifier"))
                if not old_prop:
                    continue
                old_ts = old_prop.get("latestUpdateMillis") or 0
                new_ts = prop.get("latestUpdateMillis") or 0
                if old_ts > new_ts:
                    prop["value"] = old_prop.get("value")
                    prop["latestUpdateMillis"] = old_ts
        return devices

    def _apply_property_values(
        self, iot_id: str, values: dict[str, Any], timestamp_ms: int | None
    ) -> bool:
        """Write property values into coordinator data. Returns True if the device is known."""
        if not self.data:
            return False
        devices = list(self.data.get("devices", []))
        for idx, device in enumerate(devices):
            if (device.get("iotId") or device.get("elementId")) != iot_id:
                continue
            prop_list = [dict(p) for p in device.get("propertyList") or []]
            prop_map = {p.get("identifier"): p for p in prop_list}
            for prop_id, value in values.items():
                prop = prop_map.get(prop_id)
                if prop is None:
                    prop = {"identifier": prop_id}
                    prop_list.append(prop)
                prop["value"] = value
                if timestamp_ms is not None:
                    prop["latestUpdateMillis"] = timestamp_ms
            devices[idx] = {**device, "propertyList": prop_list}
            # Assign directly instead of async_set_updated_data(): that call reschedules
            # the poll timer, so frequent pushes would postpone polling (and token refresh) forever.
            self.data = {**self.data, "devices": devices}
            self.async_update_listeners()
            return True
        return False

    def _handle_mqtt_update(self, data: dict[str, Any]) -> None:
        """Handle MQTT update (called from MQTT thread)."""
        # Schedule the update on the Home Assistant event loop
        self.hass.loop.call_soon_threadsafe(self._async_handle_mqtt_update, data)

    @callback
    def _async_handle_mqtt_update(self, data: dict[str, Any]) -> None:
        """Handle MQTT update on the event loop."""
        if not self.data or not self.data.get("devices"):
            _LOGGER.debug("No current devices to update, skipping MQTT update")
            return

        for mqtt_device in data.get("devices", []):
            iot_id = mqtt_device.get("iotId") or mqtt_device.get("elementId")
            if not iot_id:
                continue
            values = {}
            timestamp_ms = 0
            for prop in mqtt_device.get("propertyList", []):
                values[prop.get("identifier")] = prop.get("value")
                timestamp_ms = max(timestamp_ms, prop.get("latestUpdateMillis") or 0)
            if self._apply_property_values(iot_id, values, timestamp_ms or int(time.time() * 1000)):
                _LOGGER.debug("Updated device %s properties from MQTT", iot_id)
            else:
                _LOGGER.debug("MQTT update for unknown device %s, ignoring", iot_id)

    async def _update_mqtt_token(self) -> None:
        """Update MQTT client with refreshed session data."""
        if self.mqtt_client:
            session_data = self.client.get_session_data()
            if session_data:
                self.mqtt_client.update_session_data(session_data)
                _LOGGER.debug("Updated MQTT client with new session data")

    async def async_force_refresh_token(self) -> dict[str, Any]:
        """Force an IoT token refresh (or re-login) and keep MQTT in sync.

        Intended for debugging/testing from a Home Assistant service call.
        """
        _LOGGER.info("async_force_refresh_token called for entry_id=%s", self.entry.entry_id)
        
        before = self.client.get_session_data() or {}
        before_expires_at = before.get("iotTokenExpiresAt")
        _LOGGER.info("Before refresh: expires_at=%s (current time=%s)", before_expires_at, int(time.time() * 1000))

        mode = "refreshed"
        _LOGGER.info("Attempting token refresh...")
        ok = await self.client.refresh_token()
        if not ok:
            _LOGGER.warning("Token refresh failed, attempting re-login...")
            mode = "relogin"
            await self.client.login()
        else:
            _LOGGER.info("Token refresh succeeded")

        await self._update_mqtt_token()

        after = self.client.get_session_data() or {}
        after_expires_at = after.get("iotTokenExpiresAt")
        _LOGGER.info("After refresh: expires_at=%s, mode=%s", after_expires_at, mode)

        return {
            "entry_id": self.entry.entry_id,
            "mode": mode,
            "expires_at_before": before_expires_at,
            "expires_at_after": after_expires_at,
        }

    async def async_shutdown(self) -> None:
        """Shutdown coordinator."""
        if self._post_command_refresh_unsub:
            self._post_command_refresh_unsub()
            self._post_command_refresh_unsub = None
        if self.mqtt_client:
            await self.mqtt_client.disconnect()
        await super().async_shutdown()

    async def set_device_property(
        self, iot_id: str, property_id: str, value: int | float | str | dict[str, Any]
    ) -> None:
        """Set device property (value may be a struct dict e.g. HSVColor)."""
        _LOGGER.debug("set_device_property iot_id=%s property_id=%s value=%s", iot_id, property_id, value)
        await self.set_device_properties_bulk(iot_id, {property_id: value})

    async def set_device_properties_bulk(
        self, iot_id: str, items: dict[str, int | float | str | dict[str, Any]]
    ) -> None:
        """Set multiple device properties in one API call."""
        _LOGGER.debug("set_device_properties_bulk iot_id=%s items=%s", iot_id, items)
        await self.client.set_device_properties(iot_id, items)
        # Optimistic update: show the new state right away. No timestamp, so the next
        # poll/MQTT push with the real device state always wins.
        self._apply_property_values(iot_id, items, None)
        self._schedule_post_command_refresh()

    @callback
    def _schedule_post_command_refresh(self) -> None:
        """Re-read state from the cloud a few seconds after a command (debounced)."""
        if self._post_command_refresh_unsub:
            self._post_command_refresh_unsub()

        @callback
        def _refresh(_now: Any) -> None:
            self._post_command_refresh_unsub = None
            self.hass.async_create_task(self.async_request_refresh())

        self._post_command_refresh_unsub = async_call_later(
            self.hass, POST_COMMAND_REFRESH_DELAY, _refresh
        )
