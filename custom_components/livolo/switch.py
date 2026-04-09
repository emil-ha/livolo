"""Switch platform for Livolo."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[LivoloDataUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Livolo switch entities."""
    coordinator = entry.runtime_data

    entities = []
    devices = coordinator.data.get("devices", [])
    gateway_to_devices = coordinator.data.get("gateway_to_devices", {})
    
    if not devices:
        _LOGGER.warning("No devices found, entities will be added after first update")
        return

    # Build reverse mapping: device_id → gateway_id
    device_to_gateway: dict[str, str] = {}
    for gateway_id, device_ids in gateway_to_devices.items():
        for device_id in device_ids:
            device_to_gateway[device_id] = gateway_id

    # First pass: find gateway device(s) and register them in device registry
    from homeassistant.helpers import device_registry as dr
    device_registry = dr.async_get(hass)
    
    for device in devices:
        # Gateways have nodeType: "GATEWAY" or categoryKey: "GeneralGateway"
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        if is_gateway:
            gateway_element_id = device.get("iotId") or device.get("elementId")
            if gateway_element_id:
                # Register gateway device in device registry
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, gateway_element_id)},
                    name=device.get("nickName") or device.get("name") or "Livolo Gateway",
                    manufacturer="Livolo",
                    model=device.get("categoryKey") or "Livolo Gateway",
                )

    # Second pass: create entities for all devices including gateways
    for device in devices:
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue

        # Gateways have nodeType: "GATEWAY" or categoryKey: "GeneralGateway"
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        
        # Find the gateway for this device using the mapping
        gateway_iot_id = device_to_gateway.get(iot_id) if not is_gateway else None
        
        # Get properties from propertyList
        property_list = device.get("propertyList", [])
        device_name = device.get("nickName") or device.get("name") or iot_id
        
        # For all devices, check for switchable properties
        for prop in property_list:
            identifier = prop.get("identifier")
            if identifier and (identifier.startswith("PowerSwitch_") or identifier.startswith("SocketSwitch_")):
                entities.append(
                    LivoloSwitchEntity(
                        coordinator,
                        iot_id,
                        identifier,
                        device_name,
                        device_info=device,
                        gateway_iot_id=gateway_iot_id,
                    )
                )

    async_add_entities(entities)


class LivoloSwitchEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], SwitchEntity):
    """Representation of a Livolo switch."""

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        property_id: str,
        device_name: str,
        device_info: dict[str, Any] = {},
        gateway_iot_id: str | None = None,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._property_id = property_id
        self._device_name = device_name
        self._attr_unique_id = f"{iot_id}_{property_id}"
        self._attr_has_entity_name = bool(getattr(coordinator, "entry", None) and coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False))
        switch_details = device_info.get("switchDetails", {}).get(property_id, {})
        name = switch_details.get("buttonName", property_id)
        if "电" in name or name == property_id or name == "":
            name = property_id.replace('_', ' ').title()

        self._attr_name = name
        
        # Set device info
        if device_info:
            # Gateways have nodeType: "GATEWAY" or categoryKey: "GeneralGateway"
            is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, iot_id)},
                name=device_name,
                manufacturer="Livolo",
                model=device_info.get("categoryKey") or ("Livolo Gateway" if is_gateway else "Livolo Switch"),
                via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
            )

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        devices = self.coordinator.data.get("devices", [])
        for device in devices:
            iot_id = device.get("iotId") or device.get("elementId")
            if iot_id == self._iot_id:
                property_list = device.get("propertyList", [])
                for prop in property_list:
                    if prop.get("identifier") == self._property_id:
                        value = prop.get("value")
                        return value == 1 or value == "1" or value is True
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.set_device_property(self._iot_id, self._property_id, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.set_device_property(self._iot_id, self._property_id, 0)
