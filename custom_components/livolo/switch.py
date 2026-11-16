"""Switch platform for Livolo (binary controls)."""
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
from .device_property_utils import get_property_label, iter_binary_switch_identifiers
from .entity_helpers import find_device, get_property_value, is_gateway, normalize_on

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[LivoloDataUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Livolo switch entities."""
    coordinator = entry.runtime_data

    entities: list[SwitchEntity] = []
    devices = coordinator.data.get("devices", [])
    gateway_to_devices = coordinator.data.get("gateway_to_devices", {})

    if not devices:
        _LOGGER.warning("No devices found, entities will be added after first update")
        return

    device_to_gateway: dict[str, str] = {}
    for gateway_id, device_ids in gateway_to_devices.items():
        for device_id in device_ids:
            device_to_gateway[device_id] = gateway_id

    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)

    for device in devices:
        device_is_gateway = is_gateway(device)
        if device_is_gateway:
            gateway_element_id = device.get("iotId") or device.get("elementId")
            if gateway_element_id:
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, gateway_element_id)},
                    name=device.get("nickName") or device.get("name") or "Livolo Gateway",
                    manufacturer="Livolo",
                    model=device.get("categoryKey") or "Livolo Gateway",
                )

    for device in devices:
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue

        device_is_gateway = is_gateway(device)
        gateway_iot_id = device_to_gateway.get(iot_id) if not device_is_gateway else None
        device_name = device.get("nickName") or device.get("name") or iot_id
        pk = device.get("productKey")

        for prop_id in iter_binary_switch_identifiers(device):
            switch_details = device.get("switchDetails", {}).get(prop_id, {})
            btn = switch_details.get("buttonName") or ""
            if btn and "电" not in btn and btn != prop_id:
                disp = btn
            else:
                disp = get_property_label(prop_id, pk) or prop_id.replace("_", " ").title()
            entities.append(
                LivoloSwitchEntity(
                    coordinator,
                    iot_id,
                    prop_id,
                    device_name,
                    display_name=disp,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                )
            )

    async_add_entities(entities)


class LivoloSwitchEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], SwitchEntity):
    """Binary property exposed as a switch."""

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        property_id: str,
        device_name: str,
        display_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._property_id = property_id
        self._attr_unique_id = f"{iot_id}_{property_id}"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = display_name

        device_is_gateway = is_gateway(device_info)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or ("Livolo Gateway" if device_is_gateway else "Livolo"),
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not device_is_gateway else None,
        )

    @property
    def is_on(self) -> bool:
        dev = find_device(self.coordinator.data.get("devices", []), self._iot_id)
        return normalize_on(get_property_value(dev, self._property_id))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, self._property_id, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, self._property_id, 0)
