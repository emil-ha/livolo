"""Data update coordinator for Livolo."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import APP_KEY, APP_SECRET, DOMAIN, TOKEN_EXPIRY_BUFFER_MS
from .livolo_client import LivoloClient
from .mqtt_client import LivoloMqttClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)


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
        )
        self.mqtt_client: LivoloMqttClient | None = None
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
            else:
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

            # Start MQTT client if we have gateway credentials
            session_data = self.client.get_session_data()
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
                "devices": devices,
                "gateway_to_devices": gateway_to_devices,  # Add mapping to coordinator data
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Livolo API: {err}") from err

    def _handle_mqtt_update(self, data: dict[str, Any]) -> None:
        """Handle MQTT update (called from MQTT thread)."""
        # Schedule the update on the Home Assistant event loop
        self.hass.loop.call_soon_threadsafe(self._async_handle_mqtt_update, data)
    
    def _async_handle_mqtt_update(self, data: dict[str, Any]) -> None:
        """Handle MQTT update on the event loop."""
        # Merge MQTT updates with current data
        current_devices = self.data.get("devices", [])
        mqtt_devices = data.get("devices", [])
        
        if not current_devices:
            _LOGGER.warning("No current devices to update, skipping MQTT update")
            return
        
        # Update devices with MQTT data
        device_map = {d.get("iotId") or d.get("elementId"): d.copy() for d in current_devices}
        
        for mqtt_device in mqtt_devices:
            iot_id = mqtt_device.get("iotId") or mqtt_device.get("elementId")
            if not iot_id:
                continue
                
            if iot_id in device_map:
                # Update propertyList
                mqtt_props = {p.get("identifier"): p for p in mqtt_device.get("propertyList", [])}
                prop_list = device_map[iot_id].get("propertyList", [])
                
                # Update existing properties or add new ones
                prop_map = {p.get("identifier"): p for p in prop_list}
                for prop_id, mqtt_prop in mqtt_props.items():
                    if prop_id in prop_map:
                        # Update existing property value
                        prop_map[prop_id]["value"] = mqtt_prop.get("value")
                    else:
                        # Add new property
                        prop_list.append(mqtt_prop)
                
                device_map[iot_id]["propertyList"] = prop_list
                _LOGGER.debug("Updated device %s properties from MQTT", iot_id)
            else:
                _LOGGER.debug("MQTT update for unknown device %s, ignoring", iot_id)
        
        # Update coordinator data, preserving gateway mapping
        self.async_set_updated_data({
            "devices": list(device_map.values()),
            "gateway_to_devices": self.data.get("gateway_to_devices", {}),
        })
        _LOGGER.debug("Coordinator data updated from MQTT")

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
        if self.mqtt_client:
            await self.mqtt_client.disconnect()
        await super().async_shutdown()

    async def set_device_property(self, iot_id: str, property_id: str, value: int) -> None:
        """Set device property."""
        await self.client.set_device_properties(iot_id, {property_id: value})
        await self.async_request_refresh()
